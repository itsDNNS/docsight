"""Runtime contract tests for portable DOCSight startup."""

import os
import sys
import types

from app import main as app_main


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

    def fake_serve(app, **kwargs):
        calls.append(kwargs)

    monkeypatch.delenv("WEB_HOST", raising=False)
    monkeypatch.setitem(sys.modules, "waitress", types.SimpleNamespace(serve=fake_serve))

    app_main.run_web(8765)

    assert calls == [{"host": "0.0.0.0", "port": 8765, "threads": 4, "_quiet": True}]


def test_run_web_honors_web_host_env(monkeypatch):
    calls = []

    def fake_serve(app, **kwargs):
        calls.append(kwargs)

    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setitem(sys.modules, "waitress", types.SimpleNamespace(serve=fake_serve))

    app_main.run_web(8770)

    assert calls == [{"host": "127.0.0.1", "port": 8770, "threads": 4, "_quiet": True}]


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


def test_config_save_handler_uses_guarded_timezone_path(monkeypatch):
    restart_calls = []
    cfg = _Config(timezone="Europe/Berlin", history_days=30, configured=True)
    storage = _Storage()

    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delattr(app_main.time, "tzset", raising=False)

    app_main._handle_config_changed(cfg, storage, lambda: restart_calls.append("restart"))

    assert cfg.load_calls == 1
    assert os.environ["TZ"] == "Europe/Berlin"
    assert storage.max_days == 30
    assert restart_calls == ["restart"]
