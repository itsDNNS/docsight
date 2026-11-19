"""Focused lifecycle checks for the application entrypoint."""

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
import requests

from app import main


def test_web_thread_exit_returns_normally_in_desktop_mode(monkeypatch):
    calls = []
    stopped_thread = SimpleNamespace(is_alive=lambda: False)
    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")

    main._wait_for_web_thread(
        stopped_thread,
        lambda: calls.append("stop_polling"),
    )

    assert calls == ["stop_polling"]


def test_web_thread_exit_raises_after_stopping_polling_in_server_mode(monkeypatch):
    calls = []
    stopped_thread = SimpleNamespace(is_alive=lambda: False)
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)

    with pytest.raises(RuntimeError, match="Web server stopped unexpectedly"):
        main._wait_for_web_thread(
            stopped_thread,
            lambda: calls.append("stop_polling"),
        )

    assert calls == ["stop_polling"]


def test_keyboard_shutdown_stops_polling_resources(monkeypatch):
    calls = []
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)

    def interrupted():
        raise KeyboardInterrupt

    main._wait_for_web_thread(
        SimpleNamespace(is_alive=interrupted),
        lambda: calls.append("stop_polling"),
    )

    assert calls == ["stop_polling"]


class _NoContentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(204)
        for header in self.server.extra_headers:
            self.send_header(*header)
        self.end_headers()

    def log_message(self, *args):
        pass


# The second case sends a header urllib3 cannot parse, which it reports with the URL.
@pytest.mark.parametrize("extra_headers", [(), [("Cache-Control ", "no-cache")]])
def test_debug_logging_keeps_request_targets_out_of_the_log(caplog, extra_headers):
    server = HTTPServer(("127.0.0.1", 0), _NoContentHandler)
    server.extra_headers = extra_headers
    threading.Thread(target=server.serve_forever, daemon=True).start()
    caplog.set_level(logging.DEBUG)
    try:
        requests.get(
            f"http://127.0.0.1:{server.server_port}/hook/secret-token?key=secret-key",
            timeout=5,
        )
    finally:
        server.shutdown()
        server.server_close()
    logging.getLogger("docsis.main").debug("own debug record")

    assert "own debug record" in caplog.messages
    assert not [message for message in caplog.messages if "secret" in message]
