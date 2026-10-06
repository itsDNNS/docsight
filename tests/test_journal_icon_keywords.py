"""Keyword lists for automatic journal entry icons."""

import json
from pathlib import Path

from app.modules.journal.routes import ICON_KEYWORD_CATEGORIES

I18N = Path(__file__).resolve().parents[1] / "app" / "modules" / "journal" / "i18n"


def test_every_language_defines_keywords_for_every_icon_category():
    missing = []
    for catalog_path in sorted(I18N.glob("*.json")):
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for category in ICON_KEYWORD_CATEGORIES:
            words = [word.strip() for word in catalog.get(f"icon_keywords_{category}", "").split(",")]
            if not any(words):
                missing.append(f"{catalog_path.stem}: {category}")
    assert missing == []


def test_icon_keywords_combine_ui_language_with_english_and_german(make_config, make_app, builtin_module_loader_factory):
    manager = make_config()
    client = make_app(config_manager=manager, module_loader_factory=builtin_module_loader_factory(manager)).test_client()
    response = client.get("/api/journal/icon-keywords?lang=pl")

    assert response.status_code == 200
    keywords = response.get_json()
    assert set(keywords) == set(ICON_KEYWORD_CATEGORIES)
    technician = keywords["technician"]
    assert {"technik", "technician", "techniker"} <= set(technician)
    assert len(technician) == len(set(technician))
    assert all(word == word.lower() and word == word.strip() for words in keywords.values() for word in words)
