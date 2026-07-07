"""Tests for glossary i18n key completeness."""

import json
import os

import pytest

from app.glossary import (
    GLOSSARY_LEVELS,
    get_glossary_categories,
    get_glossary_localization_languages,
    get_glossary_term,
    get_glossary_terms,
)

I18N_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "i18n")
MOD_I18N_DIR = os.path.join(
    os.path.dirname(__file__), "..", "app", "modules", "modulation", "i18n"
)

CORE_GLOSSARY_KEYS = [
    "glossary_snr",
    "glossary_ds_power",
    "glossary_us_power",
    "glossary_errors",
    "glossary_scqam",
    "glossary_ofdm",
    "glossary_modulation",
    "glossary_docsis",
    "docsis_basics_label",
    "glossary_docsis_basics",
    "glossary_gaming_index",
]

GLOSSARY_PAGE_KEYS = [
    "glossary_page_title",
    "glossary_page_intro",
    "glossary_level_selector",
    "glossary_knowledge_eyebrow",
    "glossary_filter_title",
    "glossary_search_label",
    "glossary_search_placeholder",
    "glossary_category_filter_label",
    "glossary_all_categories",
    "glossary_result_singular",
    "glossary_result_plural",
    "glossary_no_results",
    "glossary_all_levels_heading",
    "glossary_misconceptions_heading",
    "glossary_protected_heading",
    "glossary_related_heading",
    "glossary_no_term_selected",
    "glossary_level_eli5",
    "glossary_level_eli5_desc",
    "glossary_level_basic",
    "glossary_level_basic_desc",
    "glossary_level_advanced",
    "glossary_level_advanced_desc",
    "glossary_level_technician",
    "glossary_level_technician_desc",
]

MOD_GLOSSARY_KEYS = [
    "glossary_health_index",
    "glossary_low_qam",
    "glossary_sample_density",
]

LANGUAGES = ["en", "de", "fr", "es"]


@pytest.mark.parametrize("lang", LANGUAGES)
def test_core_glossary_keys_present(lang):
    path = os.path.join(I18N_DIR, f"{lang}.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key in CORE_GLOSSARY_KEYS:
        assert key in data, f"Missing {key} in {lang}.json"
        assert len(data[key]) > 10, f"Empty/too-short value for {key} in {lang}.json"


def test_glossary_page_keys_present_in_every_offered_language():
    i18n_files = sorted(
        (
            path for path in os.scandir(I18N_DIR)
            if path.name.endswith(".json") and path.name != "template.json"
        ),
        key=lambda path: path.name,
    )
    assert i18n_files
    with open(os.path.join(I18N_DIR, "en.json"), encoding="utf-8-sig") as f:
        english = json.load(f)

    protected_tokens = {"DOCSIS", "SNR", "Speedtest"}
    for entry in i18n_files:
        with open(entry.path, encoding="utf-8-sig") as f:
            data = json.load(f)
        for key in GLOSSARY_PAGE_KEYS:
            assert key in data, f"Missing {key} in {entry.name}"
            assert data[key], f"Empty value for {key} in {entry.name}"
            if key in {"glossary_result_singular", "glossary_result_plural"}:
                assert "{count}" in data[key], f"Missing count placeholder in {key} for {entry.name}"
        placeholder = data["glossary_search_placeholder"]
        no_results = data["glossary_no_results"]
        for token in protected_tokens:
            assert token in placeholder or token in no_results, f"Missing protected search token {token} in {entry.name}"
        if entry.name != "en.json":
            for key in GLOSSARY_PAGE_KEYS:
                if key == "glossary_level_eli5":
                    continue
                assert data[key] != english[key], f"English glossary UI fallback leaked for {key} in {entry.name}"


def test_modulation_glossary_keys_present_in_source_catalog():
    path = os.path.join(MOD_I18N_DIR, "en.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key in MOD_GLOSSARY_KEYS:
        assert key in data, f"Missing {key} in modulation/en.json"
        assert len(data[key]) > 10, f"Empty/too-short value for {key} in modulation/en.json"


def test_modulation_glossary_keys_fall_back_for_core_languages():
    from app.i18n import _TRANSLATIONS
    from app.module_loader import merge_module_i18n

    original = {lang: dict(values) for lang, values in _TRANSLATIONS.items()}
    try:
        merge_module_i18n("docsight.modulation", MOD_I18N_DIR)
        for lang in LANGUAGES:
            data = _TRANSLATIONS[lang]
            for key in MOD_GLOSSARY_KEYS:
                namespaced = f"docsight.modulation.{key}"
                assert namespaced in data, f"Missing {namespaced} fallback in {lang}"
                assert len(data[namespaced]) > 10, f"Empty/too-short fallback for {namespaced} in {lang}"
    finally:
        _TRANSLATIONS.clear()
        _TRANSLATIONS.update(original)


def test_docsis_basics_glossary_preserves_core_meaning_in_every_offered_language():
    """The beginner DOCSIS explanation must not become English-only or lose terms."""
    i18n_files = sorted(
        (
            path for path in os.scandir(I18N_DIR)
            if path.name.endswith(".json") and path.name != "template.json"
        ),
        key=lambda path: path.name,
    )
    assert i18n_files

    protected_terms = {"DOCSight", "DOCSIS", "DSL", "SC-QAM", "Speedtest", "IP"}
    with open(os.path.join(I18N_DIR, "en.json"), encoding="utf-8-sig") as f:
        source_text = json.load(f)["glossary_docsis_basics"]
    for entry in i18n_files:
        with open(entry.path, encoding="utf-8-sig") as f:
            data = json.load(f)
        label = data.get("docsis_basics_label", "")
        text = data.get("glossary_docsis_basics", "")
        assert label, f"Missing docsis_basics_label in {entry.name}"
        assert len(text) > 120, f"DOCSIS basics copy too short in {entry.name}"
        for term in protected_terms:
            assert term in text, f"Missing protected term {term} in {entry.name}"
        if entry.name == "en.json":
            source_text = text
            assert "Cable internet uses DOCSIS, not DSL" in text
            assert "not Speedtest/IP throughput or tariff speed" in text
            assert "shared medium" in text
        else:
            assert label != "DOCSIS basics", f"English label fallback leaked into {entry.name}"
            assert text != source_text, f"English text fallback leaked into {entry.name}"
            assert not text.startswith("Cable internet uses DOCSIS"), f"English text fallback leaked into {entry.name}"


def _offered_core_languages():
    return sorted(
        entry.name[:-5]
        for entry in os.scandir(I18N_DIR)
        if entry.name.endswith(".json") and entry.name != "template.json"
    )


def test_glossary_term_content_localized_for_every_offered_non_english_language():
    offered = set(_offered_core_languages()) - {"en"}
    assert set(get_glossary_localization_languages()) == offered

    english_terms = {term["id"]: term for term in get_glossary_terms("en")}
    english_categories = {category["id"]: category for category in get_glossary_categories("en")}

    for lang in sorted(offered):
        localized_terms = {term["id"]: term for term in get_glossary_terms(lang)}
        localized_categories = {category["id"]: category for category in get_glossary_categories(lang)}
        assert set(localized_terms) == set(english_terms), f"Term IDs differ in {lang}"
        assert set(localized_categories) == set(english_categories), f"Category IDs differ in {lang}"

        for category_id, english_category in english_categories.items():
            category = localized_categories[category_id]
            assert category["title"], f"Missing category title for {category_id} in {lang}"
            assert category["description"], f"Missing category description for {category_id} in {lang}"
            assert category["description"] != english_category["description"], f"English category fallback leaked for {category_id} in {lang}"

        for term_id, english_term in english_terms.items():
            term = localized_terms[term_id]
            assert term["title"].strip(), f"Missing title for {term_id} in {lang}"
            assert set(term["levels"]) == set(GLOSSARY_LEVELS), f"Missing levels for {term_id} in {lang}"
            assert term["aliases"], f"Missing aliases for {term_id} in {lang}"
            assert all(alias.strip() for alias in term["aliases"]), f"Blank alias for {term_id} in {lang}"
            joined = " ".join([term["title"], *term["aliases"], *term["levels"].values(), *term["misconceptions"]])
            english_joined = " ".join([english_term["title"], *english_term["aliases"], *english_term["levels"].values(), *english_term["misconceptions"]])
            assert joined != english_joined, f"English term fallback leaked for {term_id} in {lang}"
            for level in GLOSSARY_LEVELS:
                assert len(term["levels"][level]) > 40, f"Too-short {level} for {term_id} in {lang}"
                assert term["levels"][level] != english_term["levels"][level], f"English {level} fallback leaked for {term_id} in {lang}"
            for token in term["protected_terms"]:
                if token in english_joined:
                    assert token in joined, f"Missing protected token {token} for {term_id} in {lang}"


def test_localized_glossary_lookup_normalizes_region_locale():
    german = get_glossary_term("docsis", "de-DE")
    english = get_glossary_term("docsis", "en")
    assert german is not None and english is not None
    assert german["levels"]["eli5"] != english["levels"]["eli5"]
    assert "DOCSIS" in german["levels"]["eli5"]
