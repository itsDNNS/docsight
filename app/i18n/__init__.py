"""Internationalization - loads translations from JSON files."""

import json
import os

_DIR = os.path.dirname(__file__)
_TRANSLATIONS = {}
LANGUAGES = {}

# ISP brand colors for visual indicator dot
ISP_COLORS = {
    "Vodafone": "#e60000",
    "PYUR": "#512d6d",
    "eazy": "#00b900",
    "NetCologne": "#ec1c24",
    "SFR": "#e2001a",
    "Euskaltel": "#e30613",
    "R": "#ff6600",
    "Telecable": "#0066b3",
}

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


def get_translations(lang="en"):
    """Return translation dict for given language code."""
    return _TRANSLATIONS.get(lang, _TRANSLATIONS.get("en", {}))
