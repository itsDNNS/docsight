"""Tests for glossary i18n key completeness."""

import json
import os

import pytest

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
    "glossary_gaming_index",
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
