# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from threading import Event
from typing import IO, Any, Optional, Union

import libvirt

from . import libvirt_events_thread


# Reads serial console log from libvirt VM and writes it to a file.
class QemuConsoleLogger:
    def __init__(self) -> None:
        self._stream_completed = Event()
        self._console_stream: Optional[libvirt.virStream] = None
        self._console_stream_callback_started = False
        self._console_stream_callback_added = False
        self._log_file: Optional[IO[Any]] = None

    # Attach logger to a libvirt VM.
    def attach(
        self,
        domain: libvirt.virDomain,
        log_file_path: str,
    ) -> None:
        # Open the log file.
        self._log_file = open(log_file_path, "ab")

        # Open the libvirt console stream.
        console_stream = domain.connect().newStream(libvirt.VIR_STREAM_NONBLOCK)
        domain.openConsole(
            None,
            console_stream,
            libvirt.VIR_DOMAIN_CONSOLE_FORCE | libvirt.VIR_DOMAIN_CONSOLE_SAFE,
        )
        self._console_stream = console_stream

        libvirt_events_thread.run_callback(self._register_console_callbacks)
        self._console_stream_callback_started = True

    # Close the logger.
    def close(self, abort: bool = True) -> None:
        # Check if attach() run successfully.
        if self._console_stream_callback_started:
            if abort:
                # Close the stream on libvirt callbacks thread.
                libvirt_events_thread.run_callback(self._close_stream, True)

            # Wait for stream to close.
            self._stream_completed.wait()

        else:
            if self._console_stream:
                self._console_stream.abort()

            if self._log_file:
                self._log_file.close()

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
        if events & libvirt.VIR_STREAM_EVENT_READABLE:
            # Data is available to be read.
            while True:
                try:
                    data = stream.recv(libvirt.virStorageVol.streamBufSize)
                except libvirt.libvirtError:
                    # An error occured. So, close the stream.
                    self._close_stream(True)
                    break

                if data == -2:
                    # No more data available at the moment.
                    assert self._log_file
                    self._log_file.flush()
                    break

                if len(data) == 0:
                    # EOF reached.
                    self._close_stream(False)
                    break

                assert self._log_file
                self._log_file.write(data)

        if (
            events & libvirt.VIR_STREAM_EVENT_ERROR
            or events & libvirt.VIR_STREAM_EVENT_HANGUP
        ):
            # Stream is shutting down. So, close it.
            self._close_stream(True)

    # Close the stream resource.
    # Threading: Must only be called on libvirt events thread.
    def _close_stream(self, abort: bool) -> None:
        if self._stream_completed.is_set():
            # Already closed. Nothing to do.
            return

        try:
            # Close the log file
            assert self._log_file
            self._log_file.close()

            # Close the stream
            assert self._console_stream
            if self._console_stream_callback_added:
                self._console_stream.eventRemoveCallback()

            if abort:
                self._console_stream.abort()
            else:
                self._console_stream.finish()

        finally:
            # Signal that the stream has closed.
            self._stream_completed.set()
