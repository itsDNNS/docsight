"""Thread-safe lifecycle boundary for the production WSGI server."""

from __future__ import annotations

import threading
from typing import Protocol


class ControllableServer(Protocol):
    """Small server contract retained by the application owner."""

    def run(self) -> object:
        """Serve requests until the server is closed."""

    def close(self) -> object:
        """Stop accepting requests and release the listener."""


class ServerLifecycleController:
    """Publish and close one server safely across startup and UI threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: ControllableServer | None = None
        self._close_requested = False

    def attach(self, server: ControllableServer) -> None:
        """Retain the server, or close it immediately after an early quit."""
        with self._lock:
            if self._server is not None:
                raise RuntimeError("server lifecycle already has an attached server")
            if self._close_requested:
                close_now = True
            else:
                self._server = server
                close_now = False
        if close_now:
            server.close()

    def close(self) -> None:
        """Request shutdown once; safe to call before or after server creation."""
        with self._lock:
            if self._close_requested:
                return
            self._close_requested = True
            server = self._server
        if server is not None:
            server.close()

    @property
    def close_requested(self) -> bool:
        with self._lock:
            return self._close_requested
