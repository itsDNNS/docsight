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

    def run(self) -> object:
        """Delegate serving to Waitress."""
        return self._server.run()

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

        attempt(self._server.close)
        channels = tuple(self._server.active_channels.values())
        for channel in channels:
            attempt(channel.close)
        attempt(
            lambda: self._server.task_dispatcher.shutdown(
                cancel_pending=True,
                timeout=TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS,
            )
        )

        if first_error is not None:
            raise first_error
