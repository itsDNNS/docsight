"""Tests for the Windows Desktop Preview launcher."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT / "packaging" / "windows" / "docsight_desktop.py"

spec = importlib.util.spec_from_file_location("docsight_desktop_launcher", LAUNCHER_PATH)
assert spec is not None
assert spec.loader is not None
desktop = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = desktop
spec.loader.exec_module(desktop)


def test_resolve_desktop_paths_uses_localappdata(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "LocalAppData")}

    paths = desktop.resolve_desktop_paths(env)

    assert paths.base_dir == tmp_path / "LocalAppData" / "DOCSight"
    assert paths.data_dir == paths.base_dir / "data"
    assert paths.modules_dir == paths.base_dir / "modules"
    assert paths.logs_dir == paths.base_dir / "logs"
    assert paths.log_file == paths.logs_dir / "docsight.log"


def test_resolve_desktop_paths_falls_back_to_home_localappdata(tmp_path):
    paths = desktop.resolve_desktop_paths({}, home=tmp_path / "User")

    assert paths.base_dir == tmp_path / "User" / "AppData" / "Local" / "DOCSight"


def test_configure_desktop_environment_creates_paths_and_exports_contract(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path)}

    paths = desktop.configure_desktop_environment(env)

    assert paths.data_dir.is_dir()
    assert paths.modules_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert env["DATA_DIR"] == str(paths.data_dir)
    assert env["MODULES_DIR"] == str(paths.modules_dir)
    assert env["WEB_HOST"] == "127.0.0.1"
    assert env["DOCSIGHT_DESKTOP_MODE"] == "1"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "ok", "version": "v2026-07-05.1", "docsis_health": "waiting"}, True),
        ({"status": "ok", "docsis_health": "waiting"}, False),
        ({"status": "error", "version": "v2026-07-05.1"}, False),
        (None, False),
        (["not", "a", "dict"], False),
    ],
)
def test_detects_docsight_health_payload(payload, expected):
    assert desktop.is_docsight_health_payload(payload) is expected


def test_select_port_opens_existing_docsight_instance(monkeypatch):
    env = {"WEB_PORT": "8765"}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: {"status": "ok", "version": "dev"})
    monkeypatch.setattr(desktop, "_can_bind_local_port", lambda port: pytest.fail("existing instance should skip bind probe"))

    selection = desktop.select_port(env)

    assert selection == desktop.PortSelection(port=8765, existing_instance=True)
    assert "WEB_PORT" in env


def test_select_port_walks_when_preferred_port_has_non_docsight_service(monkeypatch):
    env = {"WEB_PORT": "8765"}
    bind_results = {8765: False, 8766: True}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: {"status": "ok", "service": "other"})
    monkeypatch.setattr(desktop, "_can_bind_local_port", lambda port: bind_results[port])

    selection = desktop.select_port(env, max_port=8766)

    assert selection == desktop.PortSelection(port=8766, existing_instance=False)
    assert env["WEB_PORT"] == "8766"


def test_select_port_uses_default_when_web_port_is_invalid(monkeypatch):
    env = {"WEB_PORT": "not-a-port"}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: None)
    monkeypatch.setattr(desktop, "_can_bind_local_port", lambda port: port == 8765)

    selection = desktop.select_port(env, max_port=8765)

    assert selection == desktop.PortSelection(port=8765, existing_instance=False)
    assert env["WEB_PORT"] == "8765"


def test_select_port_raises_when_range_is_unavailable(monkeypatch):
    env = {"WEB_PORT": "8765"}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: None)
    monkeypatch.setattr(desktop, "_can_bind_local_port", lambda port: False)

    with pytest.raises(RuntimeError, match="No free loopback port"):
        desktop.select_port(env, max_port=8766)


def test_configure_logging_uses_rotating_file_handler(tmp_path, monkeypatch):
    log_file = tmp_path / "logs" / "docsight.log"
    calls = {}
    created_handlers = []

    class FakeHandler:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            created_handlers.append(self)

    monkeypatch.setattr(desktop, "RotatingFileHandler", FakeHandler)
    monkeypatch.setattr(desktop.logging, "basicConfig", lambda **kwargs: calls.update(kwargs))

    desktop.configure_logging(log_file)

    assert log_file.parent.is_dir()
    assert created_handlers[0].args == (log_file,)
    assert created_handlers[0].kwargs == {"maxBytes": 1_000_000, "backupCount": 3, "encoding": "utf-8"}
    assert calls["handlers"] == [created_handlers[0]]
    assert calls["force"] is True
