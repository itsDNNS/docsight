"""Tests for operator-controlled release update checks."""

from unittest.mock import MagicMock

from app.config import ConfigManager
from app import web
from app.web import app, init_config, init_storage


class _ThreadProbe:
    calls = []

    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon
        self.started = False
        self.__class__.calls.append(self)

    def start(self):
        self.started = True


def _reset_update_cache():
    web._update_cache.update({"latest": None, "checked_at": 0, "checking": False})


def test_update_check_disabled_by_default_does_not_start_fetch_thread(tmp_path, monkeypatch):
    cfg = ConfigManager(str(tmp_path / "config"))
    init_config(cfg)
    _reset_update_cache()
    monkeypatch.setattr(web, "APP_VERSION", "v2026-07-01.1")
    monkeypatch.setattr(web.threading, "Thread", _ThreadProbe)
    _ThreadProbe.calls.clear()

    assert web._check_for_update() is None

    assert _ThreadProbe.calls == []
    assert web._update_cache["checking"] is False


def test_update_check_enabled_starts_background_fetch_thread(tmp_path, monkeypatch):
    cfg = ConfigManager(str(tmp_path / "config"))
    cfg.save({"update_check_enabled": True})
    init_config(cfg)
    _reset_update_cache()
    monkeypatch.setattr(web, "APP_VERSION", "v2026-07-01.1")
    monkeypatch.setattr(web.threading, "Thread", _ThreadProbe)
    _ThreadProbe.calls.clear()

    assert web._check_for_update() is None

    assert len(_ThreadProbe.calls) == 1
    assert _ThreadProbe.calls[0].target is web._fetch_update
    assert _ThreadProbe.calls[0].daemon is True
    assert _ThreadProbe.calls[0].started is True
    assert web._update_cache["checking"] is True


def test_update_check_setting_persists_and_env_can_disable(tmp_path, monkeypatch):
    cfg = ConfigManager(str(tmp_path / "config"))
    cfg.save({"update_check_enabled": "true"})
    assert ConfigManager(str(tmp_path / "config")).get("update_check_enabled") is True

    monkeypatch.setenv("UPDATE_CHECK_ENABLED", "false")
    assert ConfigManager(str(tmp_path / "config")).get("update_check_enabled") is False


def test_settings_renders_release_update_check_toggle(tmp_path):
    cfg = ConfigManager(str(tmp_path / "config"))
    cfg.save({"modem_password": "test", "modem_type": "fritzbox"})
    init_config(cfg)
    init_storage(None)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.get("/settings")

    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'name="update_check_enabled"' in html
    assert 'id="update_check_enabled"' in html
    assert "Check GitHub releases" in html
    assert "disabled by default" in html


def test_api_config_saves_release_update_check_toggle(tmp_path):
    cfg = ConfigManager(str(tmp_path / "config"))
    cfg.save({"modem_password": "test", "modem_type": "fritzbox"})
    on_change = MagicMock()
    init_config(cfg, on_config_changed=on_change)
    init_storage(None)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.post("/api/config", json={"update_check_enabled": "true"})

    assert resp.status_code == 200
    assert resp.get_json() == {"success": True}
    assert cfg.get("update_check_enabled") is True
    on_change.assert_called_once()
