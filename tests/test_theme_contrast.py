"""Text tokens of shipped themes must meet WCAG 2.2 AA (4.5:1) on every surface."""

import re
from pathlib import Path

import pytest

from app.theme_contrast import (
    AA_TEXT,
    contrast_ratio,
    low_contrast_modes,
    low_contrast_tokens,
    parse_color,
    worst_contrast,
)
from app.theme_registry import BUILTIN_THEMES

ROOT = Path(__file__).resolve().parents[1]
# Muted text stays visibly quieter than secondary text.
HIERARCHY_STEP = 1.25


def _contrast(foreground, background):
    return contrast_ratio(parse_color(foreground), parse_color(background))


def _assert_readable(tokens):
    text = worst_contrast(tokens, "--text")
    secondary = worst_contrast(tokens, "--text-secondary")
    muted = worst_contrast(tokens, "--muted")
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


def test_navigation_badge_text_meets_aa_with_every_builtin_crit_color():
    css = (ROOT / "app/static/css/main.css").read_text(encoding="utf-8")
    rule = re.search(r"\.nav-badge \{[^}]*\}", css).group(0)
    match = re.search(r"color-mix\(in srgb, var\(--crit\) (\d+)%, #000\)", rule)
    assert match, "the navigation badge background should darken --crit"
    share = int(match.group(1)) / 100
    for theme in BUILTIN_THEMES:
        for mode in ("dark", "light"):
            crit = theme["theme_data"][mode]["--crit"]
            mixed = "#" + "".join(
                f"{round(int(crit[index:index + 2], 16) * share):02x}" for index in (1, 3, 5)
            )
            assert _contrast("#ffffff", mixed) >= AA_TEXT, f"{theme['id']} {mode}: {mixed}"


@pytest.mark.parametrize(("value", "expected"), [
    ("#fff", (255, 255, 255)),
    ("#1f2937", (31, 41, 55)),
    (" rgb(10, 20, 30) ", (10, 20, 30)),
    ("rgba(10, 20, 30, 1)", (10, 20, 30)),
    ("rgba(10, 20, 30, 0.5)", None),
    ("var(--text)", None),
    ("#12345", None),
    ("rgb(300, 0, 0)", None),
    (None, None),
])
def test_parse_color_accepts_opaque_hex_and_rgb_only(value, expected):
    assert parse_color(value) == expected


def test_low_contrast_tokens_report_each_failing_text_token():
    tokens = {"--surface": "#1f2937", "--void": "#111827", "--text": "#f9fafb",
              "--text-secondary": "#6b7280", "--muted": "#4b5563"}
    assert low_contrast_tokens(tokens) == ["--text-secondary", "--muted"]


def test_unjudgeable_themes_do_not_produce_warnings():
    assert low_contrast_tokens({"--text": "#777"}) == []
    assert low_contrast_tokens({"--surface": "rgba(0, 0, 0, 0.4)", "--muted": "#777"}) == []
    assert low_contrast_modes(None) == []
    assert low_contrast_modes({"dark": {"--surface": "#000", "--muted": "#111"}, "light": "broken"}) == ["dark"]


def test_builtin_themes_produce_no_contrast_warnings():
    assert [theme["id"] for theme in BUILTIN_THEMES if low_contrast_modes(theme["theme_data"])] == []
