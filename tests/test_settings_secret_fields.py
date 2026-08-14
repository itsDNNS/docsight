"""Regression tests for saved secret settings fields."""

import re
from pathlib import Path

from app.config import ConfigManager, PASSWORD_MASK


ROOT = Path(__file__).resolve().parents[1]


def test_saved_secret_inputs_use_stable_marker():
    """Saved secret fields must not depend on localized placeholder text."""
    templates = list((ROOT / "app" / "templates" / "settings").glob("*.html"))
    templates += list((ROOT / "app" / "modules").glob("*/templates/*settings*.html"))

    offenders: list[str] = []
    for template in templates:
        html = template.read_text(encoding="utf-8")
        for line_no, line in enumerate(html.splitlines(), start=1):
            if 'type="password"' not in line:
                continue
            if "t.saved_ph" not in line:
                continue
            if "data-saved-secret" not in line:
                offenders.append(f"{template.relative_to(ROOT)}:{line_no}")

    assert offenders == []


def test_frontend_secret_fields_cover_saved_secret_inputs():
    """Every core saved-secret input must be covered by the frontend masking list."""
    js = (ROOT / "app" / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    match = re.search(r"SECRET_FIELDS\s*=\s*\[(?P<fields>[^\]]+)\]", js)
    assert match is not None

    secret_fields = set(re.findall(r"['\"]([^'\"]+)['\"]", match.group("fields")))
    expected = {
        "modem_password",
        "mqtt_password",
        "speedtest_tracker_token",
        "notify_webhook_token",
        "notify_apprise_key",
        "notify_apprise_token",
        "notify_pwa_push_vapid_private_key",
    }

    assert expected <= secret_fields


def test_frontend_masks_saved_secret_inputs_without_hardcoded_module_names():
    """Runtime module-secret metadata must cover old and current templates."""
    js = (ROOT / "app" / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    template = (ROOT / "app" / "templates" / "settings.html").read_text(
        encoding="utf-8"
    )
    web = (ROOT / "app" / "web.py").read_text(encoding="utf-8")

    assert "function _isConfigSecretField" in js
    assert "_isSavedSecretField(inp)" in js
    assert "if (_isConfigSecretField(inp))" in js
    assert "MODULE_SECRET_FIELDS" in js
    assert "SAVED_MODULE_SECRET_FIELDS" in js
    assert "SAVED_SECRET_FIELDS.indexOf(el.name) !== -1" in js
    assert "'moduleSecretFields': module_secret_fields" in template
    assert "'savedModuleSecretFields': saved_module_secret_fields" in template
    assert "window.MODULE_SECRET_FIELDS = bootstrap.moduleSecretFields" in (
        ROOT / "app" / "static" / "js" / "settings-bootstrap.js"
    ).read_text(encoding="utf-8")
    assert "module_secret_fields=sorted(MODULE_SECRET_KEYS)" in web
    assert "config.get(key) == PASSWORD_MASK" in web


def test_saved_secret_detection_does_not_parse_placeholder_text():
    """Saved state is explicit metadata, independent of localized copy."""
    js = (ROOT / "app" / "static" / "js" / "settings.js").read_text(encoding="utf-8")

    saved_secret_function = js.split(
        "function _isSavedSecretField", 1
    )[1].split("function _shouldTreatSavedSecretEventAsUserEdit", 1)[0]
    assert "dataset.savedSecret === 'true'" in saved_secret_function
    assert "placeholder" not in saved_secret_function


def test_saved_secret_dirty_detection_requires_active_field_before_user_edit():
    """Password-manager autofill events on inactive saved secrets must stay clean."""
    js = (ROOT / "app" / "static" / "js" / "settings.js").read_text(encoding="utf-8")

    assert "function _shouldTreatSavedSecretEventAsUserEdit" in js
    assert "document.activeElement === target" in js
    assert "e && _isSavedSecretField(e.target) && e.isTrusted" not in js


def test_config_save_preserves_masked_saved_secrets(tmp_path):
    """Posting the mask must preserve existing secret values server-side."""
    mgr = ConfigManager(str(tmp_path / "data"))
    original = {
        "modem_password": "modem-secret",
        "mqtt_password": "mqtt-secret",
        "speedtest_tracker_token": "speedtest-secret",
        "notify_webhook_token": "notify-secret",
        "notify_apprise_key": "apprise-key",
        "notify_apprise_token": "apprise-token",
        "notify_pwa_push_vapid_private_key": "vapid-private-key",
    }
    mgr.save(original.copy())

    mgr.save({key: PASSWORD_MASK for key in original})

    for key, value in original.items():
        assert mgr.get(key) == value
