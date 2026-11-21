"""Focused lifecycle checks for the application entrypoint."""

import base64
import logging
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
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


def _interrupted():
    raise KeyboardInterrupt


# SIGTERMs recorded at any earlier point, e.g. during startup, and repeated.
@pytest.mark.parametrize("sigterms, is_alive", [(0, _interrupted), (2, lambda: True)],
                         ids=["ctrl_c", "sigterm_twice_before_wait"])
def test_shutdown_signal_stops_polling_resources(monkeypatch, caplog, sigterms, is_alive):
    calls = []
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)
    monkeypatch.setattr(main, "_shutdown_requested", False)
    caplog.set_level(logging.INFO, logger="docsis.main")
    for _ in range(sigterms):
        main._request_shutdown(signal.SIGTERM, None)

    main._wait_for_web_thread(
        SimpleNamespace(is_alive=is_alive),
        lambda: calls.append("stop_polling"),
    )

    assert calls == ["stop_polling"]
    assert "Shutting down" in caplog.messages


# SIGTERM after an early and a steady-state log marker. The marker does not hold
# the child in startup; the unit test above covers a flag set before the wait loop.
@pytest.mark.linux_only
@pytest.mark.parametrize("marker", ["DOCSight starting", "Polling loop started"],
                         ids=["early", "steady"])
def test_sigterm_after_startup_log_marker_exits_cleanly(tmp_path, marker):
    (tmp_path / "config.json").write_text('{"modem_type": "fritzbox"}')
    # Port 9 (discard) is assumed closed, so the modem poll fails at once.
    env = {"DATA_DIR": str(tmp_path), "MODULES_DIR": str(tmp_path / "modules"),
           "WEB_HOST": "127.0.0.1", "WEB_PORT": "0", "MODEM_URL": "http://127.0.0.1:9"}
    proc = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=Path(main.__file__).parents[1],
                            env=env, stderr=subprocess.PIPE, text=True)
    output = []
    reached = threading.Event()

    def read_log():
        for line in proc.stderr:
            output.append(line)
            if marker in line:
                reached.set()
        reached.set()

    reader = threading.Thread(target=read_log, daemon=True)
    reader.start()
    try:
        assert reached.wait(timeout=30)
        proc.send_signal(signal.SIGTERM)
        returncode = proc.wait(timeout=5)
    finally:
        proc.kill()
        proc.wait()
    reader.join(timeout=5)
    log_text = "".join(output)

    assert returncode == 0, log_text
    assert "Shutting down" in log_text and "Polling loop stopped" in log_text, log_text


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
