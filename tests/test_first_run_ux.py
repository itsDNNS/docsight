"""Template and localization contracts for the demo-first setup UX."""

import json
import re
from pathlib import Path

from app.config import ConfigManager
from app.i18n import LANGUAGES
from app.web import app, init_config, init_storage


ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "app" / "i18n"
SETUP_TEMPLATE = ROOT / "app" / "templates" / "setup.html"
INDEX_TEMPLATE = ROOT / "app" / "templates" / "index.html"
SETTINGS_TEMPLATE = ROOT / "app" / "templates" / "settings.html"
DEMO_BANNER_SCRIPT = ROOT / "app" / "static" / "js" / "demo-banner.js"

FIRST_RUN_KEYS = {
    "setup_value_title",
    "setup_value_desc",
    "setup_demo_title",
    "setup_demo_desc",
    "setup_demo_start",
    "setup_demo_trust",
    "setup_connect_modem",
    "setup_restore_action",
    "setup_demo_starting",
    "setup_demo_waiting",
    "setup_demo_failed",
    "setup_demo_timeout",
    "setup_try_again",
    "setup_try_demo",
    "setup_desktop_preview_note",
    "demo_banner_title",
    "demo_banner_desc",
    "demo_connect_own_modem",
    "demo_exit",
    "demo_action_failed",
    "demo_forced_notice",
}


def test_setup_template_has_value_led_hierarchy_and_recovery_actions():
    template = SETUP_TEMPLATE.read_text(encoding="utf-8")

    assert 'class="first-run-card glass"' in template
    assert 'id="start-demo-btn"' in template
    assert 'class="btn btn-primary first-run-demo-cta"' in template
    assert 'id="connect-modem-btn"' in template
    assert 'id="restore-action"' in template
    assert template.index("setup_demo_start") < template.index("setup_connect_modem")
    assert template.index("setup_connect_modem") < template.index("setup_restore_action")
    assert "showSetupRecovery" in template
    assert "setup_try_demo" in template
    assert "retry.focus({preventScroll: true})" in template
    assert "function startFreshSetup()" in template
    assert "nextStep(1);" in template


def test_demo_banner_is_shared_by_dashboard_and_settings():
    index = INDEX_TEMPLATE.read_text(encoding="utf-8")
    settings = SETTINGS_TEMPLATE.read_text(encoding="utf-8")

    assert "{% include 'demo_banner.html' %}" in index
    assert "{% include 'demo_banner.html' %}" in settings


def test_demo_banner_confirms_exit_and_redirects_expired_sessions():
    script = DEMO_BANNER_SCRIPT.read_text(encoding="utf-8")

    assert "window.docsightConfirm" in script
    assert "demo_migrate_confirm" in script
    assert "response.status === 401 || response.status === 403" in script
    assert "window.location.assign('/login')" in script


def test_demo_banner_actions_render_on_dashboard_and_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"demo_mode": True})
    init_config(manager)
    init_storage(None)
    app.config["TESTING"] = True

    with app.test_client() as client:
        dashboard = client.get("/")
        settings = client.get("/settings")

    for response in (dashboard, settings):
        assert response.status_code == 200
        assert b'id="demo-banner"' in response.data
        assert b"Connect own modem" in response.data
        assert b"Exit demo" in response.data


def test_environment_forced_demo_banner_is_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    manager = ConfigManager(str(tmp_path / "data"))
    init_config(manager)
    init_storage(None)
    app.config["TESTING"] = True

    with app.test_client() as client:
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


def test_desktop_preview_setup_copy_is_env_gated(tmp_path, monkeypatch):
    manager = ConfigManager(str(tmp_path / "data"))
    init_config(manager)
    init_storage(None)
    app.config["TESTING"] = True

    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)
    with app.test_client() as client:
        normal = client.get("/setup")
    assert b"24/7" not in normal.data

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")
    with app.test_client() as client:
        desktop = client.get("/setup")
    assert b"Desktop Preview" in desktop.data
    assert b"24/7" in desktop.data
    assert b"Docker" in desktop.data


def test_first_run_keys_are_complete_nonempty_and_placeholder_compatible():
    locale_paths = sorted(I18N_DIR.glob("*.json"))
    assert {path.stem for path in locale_paths} == set(LANGUAGES)
    english = json.loads((I18N_DIR / "en.json").read_text(encoding="utf-8"))
    placeholder = re.compile(r"\{[^{}]+\}")
    problems = {}

    for path in locale_paths:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        locale_problems = []
        for key in FIRST_RUN_KEYS:
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                locale_problems.append(f"{key}: missing")
                continue
            if set(placeholder.findall(value)) != set(
                placeholder.findall(english[key])
            ):
                locale_problems.append(f"{key}: placeholder mismatch")
        if locale_problems:
            problems[path.name] = locale_problems

    assert problems == {}


def test_german_demo_cta_matches_product_copy():
    german = json.loads((I18N_DIR / "de.json").read_text(encoding="utf-8"))
    assert german["setup_demo_start"] == "Demo ansehen – ohne eigene Modemdaten"
