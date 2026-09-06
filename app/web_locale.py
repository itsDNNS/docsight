"""Request and setup language selection for HTTP adapters."""

from flask import request

from .config import DEFAULTS
from .i18n import LANGUAGES
from .runtime import current_runtime


def get_lang():
    """Get language from query param or config."""
    _config_manager = current_runtime().config_manager
    lang = request.args.get("lang")
    if lang and lang in LANGUAGES:
        return lang
    if _config_manager:
        return _config_manager.get("language", "en")
    return "en"


def get_setup_lang():
    """Resolve and persist the language for the unconfigured setup route."""
    _config_manager = current_runtime().config_manager
    lang = request.args.get("lang")
    if lang in LANGUAGES:
        if _config_manager:
            _config_manager.save({"language": lang})
        return lang

    if _config_manager and _config_manager.has_stored_value("language"):
        return _config_manager.get("language", DEFAULTS["language"])

    inferred = DEFAULTS["language"]
    for requested, quality in request.accept_languages:
        if quality <= 0:
            continue
        normalized = requested.lower().replace("_", "-")
        if normalized in LANGUAGES:
            inferred = normalized
            break
        base = normalized.split("-", 1)[0]
        if base in LANGUAGES:
            inferred = base
            break

    if _config_manager:
        _config_manager.save({"language": inferred})
    return inferred
