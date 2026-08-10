from __future__ import annotations

import json
from pathlib import Path

from app import web

ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "app" / "i18n"
INDEX_TEMPLATE = ROOT / "app" / "templates" / "index.html"
SETTINGS_TEMPLATE = ROOT / "app" / "templates" / "settings.html"

DESKTOP_KEYS = {
    "desktop_preview_badge",
    "desktop_preview_notice_title",
    "desktop_preview_notice_body",
    "desktop_preview_notice_link",
}


def test_desktop_preview_mode_requires_explicit_env_flag(monkeypatch):
    monkeypatch.delenv("DOCSIGHT_DESKTOP_MODE", raising=False)
    assert web.is_desktop_preview_mode() is False

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "0")
    assert web.is_desktop_preview_mode() is False

    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")
    assert web.is_desktop_preview_mode() is True


def test_desktop_preview_badge_and_notice_are_template_gated():
    for template_path in (INDEX_TEMPLATE, SETTINGS_TEMPLATE):
        template = template_path.read_text(encoding="utf-8")
        assert "{% if desktop_mode" in template
        assert "desktop_preview_badge" in template
        assert "desktop_preview_notice_dismissed" in template
        assert "dismissMaintainerNotice('{{ desktop_preview_notice_id }}')" in template
        assert "desktop_preview_doc_url" in template


def test_desktop_preview_i18n_keys_exist_in_every_core_locale():
    missing: dict[str, set[str]] = {}
    for path in I18N_DIR.glob("*.json"):
        if path.name == "template.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        absent = {key for key in DESKTOP_KEYS if not data.get(key)}
        if absent:
            missing[path.name] = absent

    assert missing == {}
