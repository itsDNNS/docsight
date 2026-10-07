"""The overview's "Get more out of DOCSight" checklist after setup."""

from types import SimpleNamespace

import pytest

from app.config import ConfigManager
from app.runtime import current_runtime
from app.web import ONBOARDING_CHECKLIST_ID, _onboarding_checklist

ALL_MODULES = ("docsight.speedtest", "docsight.connection_monitor", "docsight.backup")


@pytest.fixture
def config(tmp_path, monkeypatch):
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"modem_password": "test", "modem_type": "fritzbox"})
    loader = SimpleNamespace(get_enabled_modules=lambda: [SimpleNamespace(id=mid) for mid in loader.ids])
    loader.ids = list(ALL_MODULES)
    monkeypatch.setattr(current_runtime(), "config_manager", manager)
    monkeypatch.setattr(current_runtime(), "module_loader", loader)
    manager.loader = loader
    return manager


def _items(checklist):
    return {item["id"]: (item["done"], item["section"]) for item in checklist["items"]}


def test_a_fresh_setup_lists_every_open_item_with_its_settings_section(config):
    checklist = _onboarding_checklist(config, demo_mode=False)

    assert checklist["id"] == ONBOARDING_CHECKLIST_ID
    assert _items(checklist) == {
        "speedtest": (False, "sources"),
        "connection_monitor": (False, "sources"),
        "notifications": (False, "notifications"),
        "backup": (False, "data"),
    }
    assert (checklist["done"], checklist["total"]) == (0, 4)


def test_items_check_themselves_off_from_the_saved_configuration(config):
    config.save({
        "speedtest_tracker_url": "http://tracker", "speedtest_tracker_token": "token",
        "notify_webhook_url": "https://hooks.example/abc",
    })

    checklist = _onboarding_checklist(config, demo_mode=False)

    assert _items(checklist)["speedtest"][0] is True
    assert _items(checklist)["notifications"][0] is True
    assert _items(checklist)["backup"][0] is False
    assert (checklist["done"], checklist["total"]) == (2, 4)


def test_disabled_modules_drop_their_item(config):
    config.loader.ids = ["docsight.speedtest"]

    assert set(_items(_onboarding_checklist(config, demo_mode=False))) == {"speedtest", "notifications"}


def test_the_checklist_disappears_when_done_dismissed_or_in_demo_mode(config):
    assert _onboarding_checklist(config, demo_mode=True) is None

    config.save({
        "speedtest_tracker_url": "http://tracker", "speedtest_tracker_token": "token",
        "connection_monitor_enabled": True,
        "notify_webhook_url": "https://hooks.example/abc",
        "backup_enabled": True, "backup_path": "/backup",
    })
    assert _onboarding_checklist(config, demo_mode=False) is None

    config.save({"notify_webhook_url": "", "dismissed_notice_ids": [ONBOARDING_CHECKLIST_ID]})
    assert _onboarding_checklist(config, demo_mode=False) is None
