# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from threading import Event
from typing import IO, Any, Optional, Union

import libvirt

from lisa.util.logger import get_logger

from . import libvirt_events_thread


# Reads serial console log from libvirt VM and writes it to a file.
class QemuConsoleLogger:
    def __init__(self) -> None:
        self._stream_completed = Event()
        self._console_stream: Optional[libvirt.virStream] = None
        self._console_stream_callback_started = False
        self._console_stream_callback_added = False
        self._log_file: Optional[IO[Any]] = None
        self._logger = get_logger("console_logger")
        self._total_bytes_read = 0
        self._read_events_count = 0

    # Attach logger to a libvirt VM.
    def attach(
        self,
        domain: libvirt.virDomain,
        log_file_path: str,
    ) -> None:
        self._logger.debug(
            f"Attaching console logger to domain '{domain.name()}', "
            f"log file: {log_file_path}"
        )
        
        # Open the log file.
        self._log_file = open(log_file_path, "ab")
        self._logger.debug(f"Opened log file for writing: {log_file_path}")

        # Open the libvirt console stream.
        console_stream = domain.connect().newStream(libvirt.VIR_STREAM_NONBLOCK)
        domain.openConsole(
            None,
            console_stream,
            libvirt.VIR_DOMAIN_CONSOLE_FORCE | libvirt.VIR_DOMAIN_CONSOLE_SAFE,
        )
        self._console_stream = console_stream
        self._logger.debug(
            f"Opened console stream for domain '{domain.name()}' with flags: "
            "VIR_DOMAIN_CONSOLE_FORCE | VIR_DOMAIN_CONSOLE_SAFE"
        )

        libvirt_events_thread.run_callback(self._register_console_callbacks)
        self._console_stream_callback_started = True
        self._logger.debug("Console callbacks registered successfully")

    # Close the logger.
    def close(self, abort: bool = True) -> None:
        self._logger.debug(
            f"Closing console logger. Total bytes read: {self._total_bytes_read}, "
            f"Read events: {self._read_events_count}, Abort: {abort}"
        )
        
        # Check if attach() run successfully.
        if self._console_stream_callback_started:
            if abort:
                # Close the stream on libvirt callbacks thread.
                libvirt_events_thread.run_callback(self._close_stream, True)

            # Wait for stream to close.
            self._stream_completed.wait()
            self._logger.debug("Stream closed successfully")

        else:
            if self._console_stream:
                self._console_stream.abort()
                self._logger.debug("Console stream aborted")

            if self._log_file:
                self._log_file.close()
                self._logger.debug("Log file closed")

    # Wait until the stream closes.
    # Typically used when gracefully shutting down a VM.
    def wait_for_close(self) -> None:
        if self._console_stream_callback_started:
            self._stream_completed.wait()

    # Register the console stream events.
    # Threading: Must only be called on libvirt events thread.
    def _register_console_callbacks(self) -> None:
        # Attach callback for stream events.
        assert self._console_stream
        self._console_stream.eventAddCallback(
            libvirt.VIR_STREAM_EVENT_READABLE
            | libvirt.VIR_STREAM_EVENT_ERROR
            | libvirt.VIR_STREAM_EVENT_HANGUP,
            self._stream_event,
            None,
        )
        self._console_stream_callback_added = True

    # Handles events for the console stream.
    # Threading: Must only be called on libvirt events thread.
    def _stream_event(
        self, stream: libvirt.virStream, events: Union[int, bytes], context: Any
    ) -> None:
        event_names = []
        if events & libvirt.VIR_STREAM_EVENT_READABLE:
            event_names.append("READABLE")
        if events & libvirt.VIR_STREAM_EVENT_ERROR:
            event_names.append("ERROR")
        if events & libvirt.VIR_STREAM_EVENT_HANGUP:
            event_names.append("HANGUP")
        
        self._logger.debug(
            f"Console stream event: {' | '.join(event_names)} (0x{events:x})"
        )
        
        if events & libvirt.VIR_STREAM_EVENT_READABLE:
            # Data is available to be read.
            bytes_in_this_event = 0
            chunks_read = 0
            
            while True:
                try:
                    data = stream.recv(libvirt.virStorageVol.streamBufSize)
                except libvirt.libvirtError as e:
                    # An error occured. So, close the stream.
                    self._logger.error(
                        f"Error reading from console stream: {e}. "
                        f"Bytes read in this event: {bytes_in_this_event}, "
                        f"Total bytes: {self._total_bytes_read}"
                    )
                    self._close_stream(True)
                    break

                if data == -2:
                    # No more data available at the moment.
                    self._read_events_count += 1
                    self._logger.debug(
                        f"Read event #{self._read_events_count} complete: "
                        f"{bytes_in_this_event} bytes in {chunks_read} chunks. "
                        f"Total bytes read: {self._total_bytes_read}"
                    )
                    assert self._log_file
                    self._log_file.flush()
                    break

                if len(data) == 0:
                    # EOF reached.
                    self._logger.debug(
                        f"EOF reached on console stream. "
                        f"Total bytes read: {self._total_bytes_read}"
                    )
                    self._close_stream(False)
                    break

                chunk_size = len(data)
                bytes_in_this_event += chunk_size
                self._total_bytes_read += chunk_size
                chunks_read += 1
                
                assert self._log_file
                self._log_file.write(data)

        if (
            events & libvirt.VIR_STREAM_EVENT_ERROR
            or events & libvirt.VIR_STREAM_EVENT_HANGUP
        ):
            # Stream is shutting down. So, close it.
            self._logger.debug("Stream error or hangup detected, closing stream")
            self._close_stream(True)

    # Close the stream resource.
    # Threading: Must only be called on libvirt events thread.
    def _close_stream(self, abort: bool) -> None:
        if self._stream_completed.is_set():
            # Already closed. Nothing to do.
            self._logger.debug("Stream already closed, skipping")
            return

        self._logger.debug(
            f"Closing stream (abort={abort}). "
            f"Final stats: {self._total_bytes_read} bytes read "
            f"in {self._read_events_count} events"
        )

        try:
            # Close the log file
            assert self._log_file
            self._log_file.close()
            self._logger.debug("Log file closed")

            # Close the stream
            assert self._console_stream
            if self._console_stream_callback_added:
                self._console_stream.eventRemoveCallback()
                self._logger.debug("Stream event callback removed")

            if abort:
                self._console_stream.abort()
                self._logger.debug("Stream aborted")
            else:
                self._console_stream.finish()
                self._logger.debug("Stream finished normally")

        finally:
            # Signal that the stream has closed.
            self._stream_completed.set()
            self._logger.debug("Stream close complete")
