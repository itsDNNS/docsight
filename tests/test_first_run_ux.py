"""Template and localization contracts for the setup start: connect the modem first, demo second."""

import json
import re
from pathlib import Path

from app.config import ConfigManager
from app.runtime import current_runtime


ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "app" / "i18n"


def test_demo_banner_actions_render_on_dashboard_and_settings(tmp_path, monkeypatch, route_app):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"demo_mode": True})
    current_runtime().config_manager = manager
    current_runtime().storage = None

    with route_app.test_client() as client:
        dashboard = client.get("/")
        settings = client.get("/settings")

    for response in (dashboard, settings):
        assert response.status_code == 200
        assert b'id="demo-banner"' in response.data
        assert b"Connect own modem" in response.data
        assert b"Exit demo" in response.data


def test_environment_forced_demo_banner_is_locked(tmp_path, monkeypatch, route_app):
    monkeypatch.setenv("DEMO_MODE", "1")
    manager = ConfigManager(str(tmp_path / "data"))
    current_runtime().config_manager = manager
    current_runtime().storage = None

    with route_app.test_client() as client:
        response = client.get("/settings")

    assert response.status_code == 200
    assert b"Demo mode is enforced by this instance" in response.data
    html = response.data.decode("utf-8")
    for button_id in ("demo-connect-modem", "demo-exit"):
        button = re.search(
            rf'<button[^>]+id="{button_id}"[^>]*>', html
        )
        assert button is not None
        assert "disabled" in button.group(0)


def test_desktop_preview_setup_copy_is_env_gated(tmp_path, monkeypatch, route_app):
    manager = ConfigManager(str(tmp_path / "data"))
    current_runtime().config_manager = manager
    current_runtime().storage = None

    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)
    with route_app.test_client() as client:
        normal = client.get("/setup")
    assert b"24/7" not in normal.data

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")
    with route_app.test_client() as client:
        desktop = client.get("/setup")
    assert b"Desktop Preview" in desktop.data
    assert b"24/7" in desktop.data
    assert b"Docker" in desktop.data


def test_setup_poll_interval_is_labelled_and_defaulted_in_seconds(tmp_path, route_app):
    current_runtime().config_manager = ConfigManager(str(tmp_path / "data"))
    current_runtime().storage = None

    with route_app.test_client() as client:
        html = client.get("/setup", headers={"Accept-Language": "en"}).get_data(as_text=True)

    field = re.search(r'<input[^>]*id="poll_interval"[^>]*>', html).group(0)
    assert 'min="60"' in field and 'max="14400"' in field and 'value="900"' in field
    assert 'for="poll_interval">Interval (seconds)</label>' in html
    assert '<span id="review-poll"></span> s<br>' in html
    assert "Minutes" not in html


def test_german_start_copy_matches_product_copy():
    german = json.loads((I18N_DIR / "de.json").read_text(encoding="utf-8"))
    assert german["setup_connect_modem"] == "Eigenes Modem verbinden"
    assert german["setup_demo_secondary"] == "Erst die Demo ansehen"
