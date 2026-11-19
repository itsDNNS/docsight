"""Controllable-server adapter for Waitress lifecycle details."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Protocol


TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS = 1.0


class _WaitressChannel(Protocol):
    def close(self) -> object:
        """Close one active HTTP channel."""


class _WaitressTaskDispatcher(Protocol):
    def shutdown(self, *, cancel_pending: bool, timeout: float) -> object:
        """Stop workers and cancel tasks within a bounded timeout."""


class _WaitressServer(Protocol):
    active_channels: Mapping[object, _WaitressChannel]
    task_dispatcher: _WaitressTaskDispatcher

    def run(self) -> object:
        """Serve requests until all Waitress channels are closed."""

    def close(self) -> object:
        """Close the Waitress listener and trigger."""


class WaitressServerAdapter:
    """Expose Waitress through the application's run/close server contract."""

    def __init__(self, server: _WaitressServer) -> None:
        self._server = server
        self._close_lock = threading.Lock()
        self._closed = False
        self._loop_running = False
        self._loop_stopped = threading.Event()

    def run(self) -> object:
        """Delegate serving to Waitress."""
        with self._close_lock:
            self._loop_running = not self._closed
        try:
            return self._server.run()
        finally:
            self._loop_stopped.set()

    def close(self) -> None:
        """Release the listener, active channels, and task workers once."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        first_error: Exception | None = None

        def attempt(operation: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                operation()
            except Exception as error:
                if first_error is None:
                    first_error = error

        # Workers first: a worker that finishes a request wakes the event loop
        # through the server's trigger, which must still be open at that point.
        # Only a worker still busy after the dispatcher timeout can miss it.
        attempt(
            lambda: self._server.task_dispatcher.shutdown(
                cancel_pending=True,
                timeout=TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS,
            )
        )

        def release_sockets() -> None:
            attempt(self._server.close)
            # A MultiSocketServer (several listen addresses) has no active_channels;
            # its close() already closes every channel.
            channels = tuple(getattr(self._server, "active_channels", {}).values())
            for channel in channels:
                attempt(channel.close)

        # Closing the loop's sockets from this thread races with its select()
        # (EBADF), and a loop blocked in select() would only notice after its
        # timeout. So wake the loop and let it close them itself. Holding the
        # trigger lock keeps the loop from running the thunk, which closes the
        # trigger, before the wake-up byte is written. The direct call is a
        # no-op afterwards and covers a loop that is not running or not answering.
        trigger = getattr(self._server, "trigger", None)
        if self._loop_running and trigger is not None:
            with trigger.lock:
                trigger.thunks.append(release_sockets)
                attempt(trigger.pull_trigger)
            self._loop_stopped.wait(TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS)
        release_sockets()

        if first_error is not None:
            raise first_error
