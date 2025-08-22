# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# To use libvirt callbacks, one has to setup a single process-wide event loop for
# libvirt. This module provisions the event loop in a python thread dedicated to
# handling libvirt events.

import asyncio
from threading import Event, Lock, Thread
from typing import Any, Callable, Optional

import libvirtaio

_callbacks_thread_lock = Lock()
_callbacks_thread: Optional[Thread] = None
_callbacks_thread_running = Event()
_callbacks_loop: Optional[asyncio.AbstractEventLoop] = None


# Entry-point for the libvirt events thread.
def _libvirt_events_thread() -> None:
    global _callbacks_loop

    # Provision this thread as an asyncio thread.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _callbacks_loop = loop

    # Initialize this thread as the libvirt events thread.
    libvirtaio.virEventRegisterAsyncIOImpl()

    # Signal that thread is initialized.
    _callbacks_thread_running.set()

    # Run the asyncio loop.
    loop.run_forever()


def init() -> None:
    global _callbacks_thread

    # Check if the events thread is already running.
    if _callbacks_thread_running.is_set():
        return

    _callbacks_thread_lock.acquire()
    try:
        # Check if the events thread already exists.
        if not _callbacks_thread:
            # Start the thread.
            thread = Thread(target=_libvirt_events_thread)
            thread.daemon = True
            thread.start()

            _callbacks_thread = thread
    finally:
        _callbacks_thread_lock.release()

    # Wait for the events thread to initialize.
    _callbacks_thread_running.wait()


# Run a callback on the libvirt events thread.
def run_callback(callback: Callable[..., Any], *args: Any) -> asyncio.Handle:
    assert _callbacks_thread_running.is_set()

    assert _callbacks_loop
    return _callbacks_loop.call_soon_threadsafe(callback, *args)
