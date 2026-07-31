"""Waitress-specific lifecycle adapter tests."""

import http.client
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from waitress import create_server

from app.server_lifecycle import ServerLifecycleController
from app.waitress_server import (
    TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS,
    WaitressServerAdapter,
)


class _FakeDispatcher:
    def __init__(self, calls):
        self._calls = calls

    def shutdown(self, *, cancel_pending, timeout):
        self._calls.append(("dispatcher.shutdown", cancel_pending, timeout))


def _fake_server(calls):
    channels = {
        1: SimpleNamespace(close=lambda: calls.append("channel-1.close")),
        2: SimpleNamespace(close=lambda: calls.append("channel-2.close")),
    }
    return SimpleNamespace(
        active_channels=channels,
        task_dispatcher=_FakeDispatcher(calls),
        run=lambda: calls.append("server.run") or "run-result",
        close=lambda: calls.append("server.close"),
    )


def test_run_delegates_to_waitress_server():
    calls = []
    adapter = WaitressServerAdapter(_fake_server(calls))

    assert adapter.run() == "run-result"
    assert calls == ["server.run"]


def test_close_closes_stable_active_channel_snapshot_and_dispatcher():
    calls = []
    server = _fake_server(calls)

    def close_first_channel():
        calls.append("channel-1.close")
        server.active_channels.clear()

    server.active_channels[1].close = close_first_channel

    WaitressServerAdapter(server).close()

    assert calls == [
        "server.close",
        "channel-1.close",
        "channel-2.close",
        (
            "dispatcher.shutdown",
            True,
            TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS,
        ),
    ]
    assert TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS == 1.0


def test_duplicate_lifecycle_close_runs_adapter_shutdown_once():
    calls = []
    lifecycle = ServerLifecycleController()
    adapter = WaitressServerAdapter(_fake_server(calls))
    lifecycle.attach(adapter)

    lifecycle.close()
    lifecycle.close()
    adapter.close()

    assert calls == [
        "server.close",
        "channel-1.close",
        "channel-2.close",
        ("dispatcher.shutdown", True, 1.0),
    ]


def test_close_before_attach_runs_full_adapter_shutdown_once():
    calls = []
    lifecycle = ServerLifecycleController()
    lifecycle.close()

    lifecycle.attach(WaitressServerAdapter(_fake_server(calls)))
    lifecycle.close()

    assert calls == [
        "server.close",
        "channel-1.close",
        "channel-2.close",
        ("dispatcher.shutdown", True, 1.0),
    ]


def test_persistent_http_connection_does_not_pin_waitress_run():
    try:
        socket_probe = socket.socket()
    except PermissionError:
        pytest.skip("the execution sandbox denies socket creation")
    else:
        socket_probe.close()

    def application(_environ, start_response):
        body = b"ok"
        start_response(
            "200 OK",
            [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))],
        )
        return [body]

    server = create_server(
        application,
        host="127.0.0.1",
        port=0,
        threads=1,
        asyncore_loop_timeout=0.05,
    )
    port = int(server.effective_port)
    lifecycle = ServerLifecycleController()
    adapter = WaitressServerAdapter(server)
    lifecycle.attach(adapter)
    server_thread = threading.Thread(target=adapter.run, daemon=True)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)

    server_thread.start()
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.read() == b"ok"
        assert response.getheader("Connection") != "close"

        deadline = time.monotonic() + 2
        while not server.active_channels and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.active_channels

        lifecycle.close()
        server_thread.join(timeout=2)

        assert not server_thread.is_alive()
        with socket.socket() as replacement_listener:
            replacement_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            replacement_listener.bind(("127.0.0.1", port))
    finally:
        lifecycle.close()
        connection.close()
        server_thread.join(timeout=2)
