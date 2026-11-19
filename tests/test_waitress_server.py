"""Waitress-specific lifecycle adapter tests."""

import http.client
import select
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from waitress import create_server, wasyncore

from app.server_lifecycle import ServerLifecycleController
from app.waitress_server import (
    TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS,
    WaitressServerAdapter,
)

# A Waitress loop thread that dies on an exception must fail the test, not only warn.
pytestmark = pytest.mark.filterwarnings(
    "error::pytest.PytestUnhandledThreadExceptionWarning"
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

    # Workers stop before the server closes its trigger, which they use to wake the loop.
    assert calls == [
        (
            "dispatcher.shutdown",
            True,
            TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS,
        ),
        "server.close",
        "channel-1.close",
        "channel-2.close",
    ]
    assert TASK_DISPATCHER_SHUTDOWN_TIMEOUT_SECONDS == 1.0


def test_close_handles_waitress_multi_socket_servers():
    calls = []
    server = _fake_server(calls)
    del server.active_channels  # several listen addresses: Waitress returns a MultiSocketServer

    WaitressServerAdapter(server).close()

    assert calls == [("dispatcher.shutdown", True, 1.0), "server.close"]


def test_duplicate_lifecycle_close_runs_adapter_shutdown_once():
    calls = []
    lifecycle = ServerLifecycleController()
    adapter = WaitressServerAdapter(_fake_server(calls))
    lifecycle.attach(adapter)

    lifecycle.close()
    lifecycle.close()
    adapter.close()

    assert calls == [
        ("dispatcher.shutdown", True, 1.0),
        "server.close",
        "channel-1.close",
        "channel-2.close",
    ]


def test_close_before_attach_runs_full_adapter_shutdown_once():
    calls = []
    lifecycle = ServerLifecycleController()
    lifecycle.close()

    lifecycle.attach(WaitressServerAdapter(_fake_server(calls)))
    lifecycle.close()

    assert calls == [
        ("dispatcher.shutdown", True, 1.0),
        "server.close",
        "channel-1.close",
        "channel-2.close",
    ]


@contextmanager
def _keep_alive_server(loop_timeout):
    """Serve one request on a kept-alive connection, then hand over the server."""
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
        asyncore_loop_timeout=loop_timeout,
    )
    lifecycle = ServerLifecycleController()
    adapter = WaitressServerAdapter(server)
    lifecycle.attach(adapter)
    server_thread = threading.Thread(target=adapter.run, daemon=True)
    connection = http.client.HTTPConnection(
        "127.0.0.1", int(server.effective_port), timeout=2
    )

    server_thread.start()
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.read() == b"ok"
        assert response.getheader("Connection") != "close"
        yield server, lifecycle, server_thread
    finally:
        lifecycle.close()
        connection.close()
        server_thread.join(timeout=2)


# A loop timeout longer than the join timeout proves that close() wakes the loop.
@pytest.mark.parametrize("loop_timeout", [0.05, 30], ids=["busy-loop", "idle-loop"])
def test_persistent_http_connection_does_not_pin_waitress_run(loop_timeout):
    with _keep_alive_server(loop_timeout) as (server, lifecycle, server_thread):
        deadline = time.monotonic() + 2
        while not server.active_channels and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.active_channels

        lifecycle.close()
        server_thread.join(timeout=2)

        assert not server_thread.is_alive()
        with socket.socket() as replacement_listener:
            replacement_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            replacement_listener.bind(("127.0.0.1", int(server.effective_port)))


def test_close_from_another_thread_never_hands_select_a_closed_socket(monkeypatch):
    close_requested, loop_parked, close_returned = (threading.Event() for _ in range(3))
    real_select = select.select

    def select_after_close(*args):
        # Park the loop between building its fd lists and select() until close() is done.
        if close_requested.is_set() and not loop_parked.is_set():
            loop_parked.set()
            close_returned.wait(0.5)
        return real_select(*args)

    monkeypatch.setattr(wasyncore.select, "select", select_after_close)
    with _keep_alive_server(0.05) as (_server, lifecycle, server_thread):
        close_requested.set()
        assert loop_parked.wait(2)
        lifecycle.close()
        close_returned.set()
        server_thread.join(timeout=2)

        assert not server_thread.is_alive()
