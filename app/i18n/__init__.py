"""Internationalization - loads translations from JSON files."""

import json
import os

_DIR = os.path.dirname(__file__)
_TRANSLATIONS = {}
LANGUAGES = {}
LANG_FLAGS = {}

for _fname in sorted(os.listdir(_DIR)):
    if not _fname.endswith(".json") or _fname == "template.json":
        continue
    _code = _fname[:-5]  # "en.json" -> "en"
    with open(os.path.join(_DIR, _fname), "r", encoding="utf-8-sig") as _f:
        _data = json.load(_f)
    _meta = _data.pop("_meta", {})
    _TRANSLATIONS[_code] = _data
    LANGUAGES[_code] = _meta.get("language_name", _code)
    LANG_FLAGS[_code] = _meta.get("flag", "")

_CORE_TRANSLATIONS = {lang: dict(strings) for lang, strings in _TRANSLATIONS.items()}


def reset_module_translations() -> None:
    """Drop strings merged in by modules, so a new app starts from the core catalogs."""
    for lang in set(_TRANSLATIONS) - set(_CORE_TRANSLATIONS):
        del _TRANSLATIONS[lang]
    for lang, strings in _CORE_TRANSLATIONS.items():
        _TRANSLATIONS[lang].clear()
        _TRANSLATIONS[lang].update(strings)


def get_translations(lang="en"):
    """Return translation dict for given language code."""
    return _TRANSLATIONS.get(lang, _TRANSLATIONS.get("en", {}))
