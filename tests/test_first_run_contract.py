"""Static contracts for the value-led first-run experience."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_TEMPLATE = ROOT / "app" / "templates" / "setup.html"
INDEX_TEMPLATE = ROOT / "app" / "templates" / "index.html"
SETTINGS_TEMPLATE = ROOT / "app" / "templates" / "settings.html"
COMPONENTS_CSS = ROOT / "app" / "static" / "css" / "components.css"
DEMO_SCRIPT = ROOT / "app" / "static" / "js" / "demo-mode.js"
I18N_DIR = ROOT / "app" / "i18n"

FIRST_RUN_KEYS = {
    "first_run_title",
    "first_run_intro",
    "first_run_demo_title",
    "first_run_demo_desc",
    "first_run_demo_button",
    "first_run_connect_button",
    "first_run_restore_button",
    "first_run_other_options",
    "first_run_local_trust",
    "first_run_demo_starting",
    "first_run_demo_loading",
    "first_run_demo_timeout",
    "first_run_demo_retry",
    "first_run_demo_error",
    "first_run_try_demo",
    "first_run_retry_connection",
    "first_run_retry_save",
    "desktop_preview_first_run",
    "demo_banner_title",
    "demo_banner_body",
    "demo_banner_connect",
    "demo_banner_exit",
    "demo_banner_pending",
    "demo_banner_error",
    "demo_banner_managed",
}


def test_setup_demo_activation_waits_for_populated_health_and_is_retryable():
    template = SETUP_TEMPLATE.read_text(encoding="utf-8")

    assert "fetch('/api/demo/start'" in template
    assert "fetch('/health'" in template
    assert "docsis_health" in template
    assert "'waiting'" in template
    assert "DEMO_READY_TIMEOUT_MS" in template
    assert 'data-demo-ready-timeout-ms="45000"' in template
    assert "if (Date.now() >= deadline)" in template
    assert 'id="demo-start-status"' in template
    assert 'aria-live="polite"' in template
    assert "textContent" in template
    assert "innerHTML" not in template


def test_every_modem_dead_end_exposes_retry_and_demo_fallback():
    template = SETUP_TEMPLATE.read_text(encoding="utf-8")

    assert 'id="test-connection-recovery"' in template
    assert 'id="setup-submit-recovery"' in template
    assert template.count("first_run_try_demo") >= 2
    assert "first_run_retry_connection" in template
    assert "retrySetupSave" in template


def test_shared_demo_banner_is_present_on_dashboard_and_settings():
    index = INDEX_TEMPLATE.read_text(encoding="utf-8")
    settings = SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    css = COMPONENTS_CSS.read_text(encoding="utf-8")
    script = DEMO_SCRIPT.read_text(encoding="utf-8")

    for template in (index, settings):
        assert "includes/demo_banner.html" in template
        assert "demo-mode.js" in template
    assert ".demo-mode-banner" in css
    assert "exitDemoMode" in script
    assert "/api/demo/migrate" in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "/setup?connect=1" in script
    assert "/setup" in script
    banner = (ROOT / "app" / "templates" / "includes" / "demo_banner.html").read_text(
        encoding="utf-8"
    )
    assert "demo_mode_locked" in banner
    assert "demo_banner_managed" in banner


def test_first_run_copy_is_localized_without_exact_english_fallbacks():
    english = json.loads((I18N_DIR / "en.json").read_text(encoding="utf-8-sig"))
    assert FIRST_RUN_KEYS <= english.keys()

    for path in sorted(I18N_DIR.glob("*.json")):
        if path.name == "template.json":
            continue
        catalog = json.loads(path.read_text(encoding="utf-8-sig"))
        missing = {key for key in FIRST_RUN_KEYS if not catalog.get(key)}
        assert missing == set(), f"{path.name}: missing {sorted(missing)}"
        if path.stem != "en":
            exact_english = {
                key for key in FIRST_RUN_KEYS if catalog[key] == english[key]
            }
            assert exact_english == set(), (
                f"{path.name}: exact-English values {sorted(exact_english)}"
            )
