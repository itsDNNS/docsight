"""Runtime contract tests for portable DOCSight startup."""

import os
import sys
import threading
import types

from app import main as app_main
from app.server_lifecycle import ServerLifecycleController


class _Config:
    def __init__(self, timezone="Europe/Berlin", history_days=14, configured=True):
        self.timezone = timezone
        self.history_days = history_days
        self.configured = configured
        self.load_calls = 0

    def get(self, key, default=None):
        if key == "timezone":
            return self.timezone
        if key == "history_days":
            return self.history_days
        return default

    def _load(self):
        self.load_calls += 1

    def is_configured(self):
        return self.configured


class _Storage:
    def __init__(self):
        self.max_days = None


def test_run_web_defaults_to_public_bind(monkeypatch):
    calls = []
    server_calls = []

    class FakeServer:
        active_channels = {}

        class task_dispatcher:
            @staticmethod
            def shutdown(*, cancel_pending, timeout):
                server_calls.append(("shutdown", cancel_pending, timeout))

        def run(self):
            server_calls.append("run")

        def close(self):
            server_calls.append("close")

    def fake_create_server(app, **kwargs):
        calls.append(kwargs)
        return FakeServer()

    monkeypatch.delenv("WEB_HOST", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "waitress",
        types.SimpleNamespace(create_server=fake_create_server),
    )
    lifecycle = ServerLifecycleController()

    app_main.run_web(8765, lifecycle)
    lifecycle.close()

    assert calls == [{"host": "0.0.0.0", "port": 8765, "threads": 4}]
    assert server_calls == ["run", "close", ("shutdown", True, 1.0)]


def test_run_web_honors_web_host_env(monkeypatch):
    calls = []

    class FakeServer:
        def run(self):
            calls.append("run")

        def close(self):
            calls.append("close")

    def fake_create_server(app, **kwargs):
        calls.append(kwargs)
        return FakeServer()

    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setitem(
        sys.modules,
        "waitress",
        types.SimpleNamespace(create_server=fake_create_server),
    )

    app_main.run_web(8770)

    assert calls == [
        {"host": "127.0.0.1", "port": 8770, "threads": 4},
        "run",
    ]


def test_server_lifecycle_close_is_idempotent_and_closes_late_server():
    calls = []
    server = types.SimpleNamespace(
        run=lambda: calls.append("run"),
        close=lambda: calls.append("close"),
    )
    lifecycle = ServerLifecycleController()

    lifecycle.close()
    lifecycle.close()
    lifecycle.attach(server)
    lifecycle.close()

    assert calls == ["close"]


def test_server_lifecycle_concurrent_close_reaches_server_once():
    calls = []
    lifecycle = ServerLifecycleController()
    lifecycle.attach(
        types.SimpleNamespace(
            run=lambda: None,
            close=lambda: calls.append("close"),
        )
    )
    threads = [threading.Thread(target=lifecycle.close) for _index in range(8)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == ["close"]


def test_apply_timezone_skips_missing_tzset(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delattr(app_main.time, "tzset", raising=False)

    app_main._apply_timezone(_Config())

    assert os.environ["TZ"] == "Europe/Berlin"


def test_apply_timezone_calls_tzset_when_available(monkeypatch):
    calls = []

    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(app_main.time, "tzset", lambda: calls.append("tzset"), raising=False)

    app_main._apply_timezone(_Config("UTC"))

    assert os.environ["TZ"] == "UTC"
    assert calls == ["tzset"]


def test_config_save_handler_stops_then_restarts_when_configured(monkeypatch):
    lifecycle_calls = []
    cfg = _Config(timezone="Europe/Berlin", history_days=30, configured=True)
    storage = _Storage()

    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delattr(app_main.time, "tzset", raising=False)

    app_main._handle_config_changed(
        cfg,
        storage,
        lambda: lifecycle_calls.append("stop"),
        lambda: lifecycle_calls.append("start"),
    )

    assert cfg.load_calls == 1
    assert os.environ["TZ"] == "Europe/Berlin"
    assert storage.max_days == 30
    assert lifecycle_calls == ["stop", "start"]


def test_config_save_handler_stops_without_restart_when_unconfigured(monkeypatch):
    lifecycle_calls = []
    cfg = _Config(timezone="UTC", configured=False)
    storage = _Storage()

    monkeypatch.setattr(app_main, "_apply_timezone", lambda _cfg: None)

    app_main._handle_config_changed(
        cfg,
        storage,
        lambda: lifecycle_calls.append("stop"),
        lambda: lifecycle_calls.append("start"),
    )

    assert lifecycle_calls == ["stop"]
