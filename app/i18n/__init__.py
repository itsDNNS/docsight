"""Internationalization - loads translations from JSON files."""

import json
import os

_DIR = os.path.dirname(__file__)
_TRANSLATIONS = {}
LANGUAGES = {}
LANG_FLAGS = {}

# Load all *.json files in this directory
for _fname in sorted(os.listdir(_DIR)):
    if not _fname.endswith(".json"):
        continue
    _code = _fname[:-5]  # "en.json" -> "en"
    with open(os.path.join(_DIR, _fname), "r", encoding="utf-8") as _f:
        _data = json.load(_f)
    _meta = _data.pop("_meta", {})
    _TRANSLATIONS[_code] = _data
    LANGUAGES[_code] = _meta.get("language_name", _code)
    LANG_FLAGS[_code] = _meta.get("flag", "")


def get_translations(lang="en"):
    """Return translation dict for given language code."""
    return _TRANSLATIONS.get(lang, _TRANSLATIONS.get("en", {}))
