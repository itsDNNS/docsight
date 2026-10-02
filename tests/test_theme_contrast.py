"""Text tokens of shipped themes must meet WCAG 2.2 AA (4.5:1) on every surface."""

import re
from pathlib import Path

import pytest

from app.theme_registry import BUILTIN_THEMES

ROOT = Path(__file__).resolve().parents[1]
BACKGROUNDS = ("--surface", "--void", "--elevated", "--void-deep")
AA_TEXT = 4.5
# Muted text stays visibly quieter than secondary text.
HIERARCHY_STEP = 1.25
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _luminance(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground, background):
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _worst_contrast(tokens, name):
    backgrounds = [tokens[key] for key in BACKGROUNDS if HEX.match(tokens.get(key, ""))]
    assert backgrounds, "theme defines no solid background tokens"
    return min(_contrast(tokens[name], background) for background in backgrounds)


def _assert_readable(tokens):
    text = _worst_contrast(tokens, "--text")
    secondary = _worst_contrast(tokens, "--text-secondary")
    muted = _worst_contrast(tokens, "--muted")
    assert muted >= AA_TEXT, f"--muted {tokens['--muted']} reaches only {muted:.2f}:1"
    assert secondary >= max(AA_TEXT, muted * HIERARCHY_STEP - 0.05), (
        f"--text-secondary {tokens['--text-secondary']} reaches {secondary:.2f}:1"
    )
    assert text >= max(AA_TEXT, secondary - 0.05), f"--text {tokens['--text']} reaches only {text:.2f}:1"


@pytest.mark.parametrize(
    ("theme_id", "mode"),
    [(theme["id"], mode) for theme in BUILTIN_THEMES for mode in ("dark", "light")],
)
def test_builtin_theme_text_meets_aa_on_all_surfaces(theme_id, mode):
    theme = next(theme for theme in BUILTIN_THEMES if theme["id"] == theme_id)
    _assert_readable(theme["theme_data"][mode])


def _css_tokens(block):
    return dict(re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def test_default_tokens_meet_aa_on_all_surfaces():
    css = (ROOT / "app/static/css/tokens.css").read_text(encoding="utf-8")
    dark_block, light_block = css.split('[data-theme="light"]', 1)
    dark = _css_tokens(dark_block)
    light = {**dark, **_css_tokens(light_block.split("}", 1)[0])}
    _assert_readable(dark)
    _assert_readable(light)
