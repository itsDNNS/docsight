"""Resolved design tokens for every built-in theme, as a reviewable snapshot.

The page under test loads the shipped token stylesheets and the theme block the
server renders through its own ``theme_css`` filter, then reads every custom
property back from the browser. A change to a token, an alias or a theme shows
up as a line in ``snapshots/theme_tokens.json``.

Regenerate after an intended change with:
    DOCSIGHT_UPDATE_SNAPSHOTS=1 pytest tests/e2e/test_theme_tokens.py
"""

import json
import os
import re
from pathlib import Path

import pytest

from app.theme_registry import BUILTIN_THEMES
from app.web import theme_css_declarations

ROOT = Path(__file__).resolve().parents[2]
CSS_FILES = ("tokens.css", "views.css", "settings.css")
SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "theme_tokens.json"
DEFAULT_THEME = "default"
_PROPERTY = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")


def _stylesheets():
    return [(ROOT / "app" / "static" / "css" / name).read_text(encoding="utf-8") for name in CSS_FILES]


def _theme_block(theme_data):
    # Same selectors as the <style id="theme-module-vars"> block in index.html.
    return (
        ':root, [data-theme="dark"] {' + str(theme_css_declarations(theme_data.get("dark", {}))) + "}\n"
        '[data-theme="light"] {' + str(theme_css_declarations(theme_data.get("light", {}))) + "}"
    )


def _themes():
    yield DEFAULT_THEME, {}
    for theme in BUILTIN_THEMES:
        yield theme["id"], theme["theme_data"]


def _resolve(page, mode, styles, names):
    page.set_content(
        f'<!doctype html><html data-theme="{mode}"><head>'
        + "".join(f"<style>{css}</style>" for css in styles)
        + "</head><body></body></html>"
    )
    return page.evaluate(
        """names => {
            const computed = getComputedStyle(document.documentElement);
            return Object.fromEntries(names.map(name => [name, computed.getPropertyValue(name).trim()]));
        }""",
        names,
    )


def _current_tokens(page):
    base = _stylesheets()
    snapshot = {}
    for theme_id, theme_data in _themes():
        styles = base + ([_theme_block(theme_data)] if theme_data else [])
        names = sorted({name for css in styles for name in _PROPERTY.findall(css)})
        snapshot[theme_id] = {mode: _resolve(page, mode, styles, names) for mode in ("dark", "light")}
    return snapshot


def test_resolved_theme_tokens_match_the_snapshot(page):
    current = _current_tokens(page)
    if os.environ.get("DOCSIGHT_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("theme token snapshot updated")
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert sorted(current) == sorted(expected), "themes were added or removed"
    changes = [
        f"{theme}/{mode} {name}: {expected[theme][mode].get(name)!r} -> {value!r}"
        for theme in current
        for mode in current[theme]
        for name, value in current[theme][mode].items()
        if expected[theme][mode].get(name) != value
    ] + [
        f"{theme}/{mode} {name}: removed"
        for theme in expected
        for mode in expected[theme]
        for name in expected[theme][mode]
        if name not in current.get(theme, {}).get(mode, {})
    ]
    assert not changes, "Theme tokens changed (set DOCSIGHT_UPDATE_SNAPSHOTS=1 if intended):\n" + "\n".join(changes[:40])


def test_every_theme_resolves_the_core_surface_tokens(page):
    """No theme may leave a core token empty, whichever token layer it overrides."""
    core = ("--bg", "--surface", "--card", "--text", "--muted", "--accent", "--good", "--warn", "--crit")
    for theme_id, modes in _current_tokens(page).items():
        for mode, tokens in modes.items():
            missing = [name for name in core if not tokens.get(name)]
            assert not missing, f"{theme_id}/{mode} leaves {missing} empty"
