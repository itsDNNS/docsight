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
    """Every saved-secret input must be covered by the frontend masking list."""
    js = (ROOT / "app" / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    match = re.search(r"SECRET_FIELDS\s*=\s*\[(?P<fields>[^\]]+)\]", js)
    assert match is not None

    secret_fields = set(re.findall(r"['\"]([^'\"]+)['\"]", match.group("fields")))
    expected = {
        "modem_password",
        "mqtt_password",
        "speedtest_tracker_token",
        "notify_webhook_token",
    }

    assert expected <= secret_fields


def test_config_save_preserves_masked_saved_secrets(tmp_path):
    """Posting the mask must preserve existing secret values server-side."""
    mgr = ConfigManager(str(tmp_path / "data"))
    original = {
        "modem_password": "modem-secret",
        "mqtt_password": "mqtt-secret",
        "speedtest_tracker_token": "speedtest-secret",
        "notify_webhook_token": "notify-secret",
    }
    mgr.save(original.copy())

    mgr.save({key: PASSWORD_MASK for key in original})

    for key, value in original.items():
        assert mgr.get(key) == value
