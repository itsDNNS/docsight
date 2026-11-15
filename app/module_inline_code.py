"""Find community modules whose templates still carry inline JavaScript.

DOCSight's Content-Security-Policy blocks inline scripts. A community module
written before that rule needs them, so while such a module is enabled the
policy keeps allowing them and Doctor names the module.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

DATA_SCRIPT_TYPES = {"application/json", "application/ld+json"}
URL_ATTRIBUTES = {"href", "src", "action", "formaction"}


def template_has_inline_code(text: str) -> bool:
    """True for an executable inline <script>, an on*= attribute or a javascript: URL."""
    for tag in BeautifulSoup(text, "html.parser").find_all(True):
        if tag.name == "script" and not tag.get("src"):
            if str(tag.get("type", "")).strip().lower() not in DATA_SCRIPT_TYPES:
                return True
        for name, value in tag.attrs.items():
            if name.lower().startswith("on") and len(name) > 2:
                return True
            if name.lower() in URL_ATTRIBUTES and str(value).strip().lower().startswith("javascript:"):
                return True
    return False


def module_has_inline_code(module_path: str | Path) -> bool:
    """True when any HTML template of the module carries inline JavaScript."""
    for path in sorted(Path(module_path).rglob("*.html")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if template_has_inline_code(text):
            return True
    return False


def modules_with_inline_code(modules) -> tuple[str, ...]:
    """Ids of enabled community modules that need inline scripts."""
    return tuple(
        mod.id for mod in modules
        if not mod.builtin and mod.enabled and not mod.error and module_has_inline_code(mod.path)
    )
