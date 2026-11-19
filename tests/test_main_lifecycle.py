"""Focused lifecycle checks for the application entrypoint."""

import base64
import logging
import sys
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


CREDENTIALS = base64.b64encode(b"admin:secret").decode()


@pytest.mark.parametrize("message, args, cause, expected", [
    ("Manual poll failed", (),
     requests.HTTPError(f"401 Client Error for url: https://modem/status.html?{CREDENTIALS}"),
     "for url: https://modem/status.html?***"),
    ("Speedtest Tracker: %s", ("http://admin:secret@tracker:8080/api",), None,
     "Speedtest Tracker: http://***@tracker:8080/api"),
    ("Modem: %s", ("http://admin:it's-secret@modem/",), None, "Modem: http://***@modem/"),
    ("POST %s failed", ("https://hooks.example/x?key=a(b)&next=secret",), None,
     "POST https://hooks.example/x?*** failed"),
    ("GET %s", ("http://host?token=prefix@secret",), None, "GET http://host?***"),
    ("Manual poll failed", (),
     requests.ConnectionError(f"Max retries exceeded with url: /status.html?{CREDENTIALS} (Caused by SSLError)"),
     "with url: /status.html?*** (Caused by SSLError)"),
    ("ready?yes (disabled?)", (), None, "ready?yes (disabled?)"),
])
def test_log_formatter_masks_url_credentials_and_queries(message, args, cause, expected):
    record = logging.LogRecord("docsis.test", logging.ERROR, __file__, 1, message, args, None)
    if cause:
        try:
            raise RuntimeError("login failed") from cause
        except RuntimeError:
            record.exc_info = sys.exc_info()

    text = main._RedactingFormatter("%(message)s").format(record)

    assert expected in text
    assert "secret" not in text and CREDENTIALS not in text
