"""Contracts for the Graphite UI token layer in tokens.css."""

import re
from pathlib import Path

import pytest

from app.theme_contrast import AA_TEXT, contrast_ratio, parse_color

ROOT = Path(__file__).resolve().parents[1]
TOKENS_CSS = ROOT / "app/static/css/tokens.css"
AA_GRAPHICS = 3.0

SURFACES = ("--ui-bg", "--ui-surface", "--ui-surface-alt")
TEXT = ("--ui-ink", "--ui-text", "--ui-muted", "--ui-accent")
STATUS = ("--ui-good", "--ui-tolerated", "--ui-marginal", "--ui-critical")
DATA = ("--ui-data-ds", "--ui-data-us", "--ui-data-snr", "--ui-data-errors", "--ui-data-latency", "--ui-data-jitter")


def _ui_colors(block):
    return dict(re.findall(r"(--ui-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def _modes():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    dark_block, light_block = css.split('[data-theme="light"]', 1)
    return {"dark": _ui_colors(dark_block), "light": _ui_colors(light_block.split("}", 1)[0])}


def _ratio(tokens, foreground, background):
    return contrast_ratio(parse_color(tokens[foreground]), parse_color(tokens[background]))


def test_light_mode_defines_every_ui_color_token():
    modes = _modes()

    assert set(modes["dark"]) == set(modes["light"])
    assert set(SURFACES + TEXT + STATUS + DATA) <= set(modes["dark"])


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("foreground", TEXT + STATUS)
def test_text_and_status_colors_meet_aa_on_every_surface(mode, foreground):
    tokens = _modes()[mode]
    for surface in SURFACES:
        assert _ratio(tokens, foreground, surface) >= AA_TEXT, f"{mode}: {foreground} on {surface}"


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("foreground", DATA + ("--ui-control",))
def test_data_series_and_controls_meet_graphics_contrast(mode, foreground):
    tokens = _modes()[mode]
    for surface in SURFACES:
        assert _ratio(tokens, foreground, surface) >= AA_GRAPHICS, f"{mode}: {foreground} on {surface}"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_text_on_accent_meets_aa(mode):
    assert _ratio(_modes()[mode], "--ui-on-accent", "--ui-accent") >= AA_TEXT


def test_ui_fonts_are_self_hosted_with_licenses():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    fonts_css = (ROOT / "app/static/css/fonts.css").read_text(encoding="utf-8")
    fonts_dir = ROOT / "app/static/fonts"

    for family, license_file in (("Bricolage Grotesque", "OFL-BricolageGrotesque.txt"), ("DM Sans", "OFL-DMSans.txt")):
        assert f"'{family}'" in css
        assert f"font-family: '{family}';" in fonts_css
        assert "SIL Open Font License" in (fonts_dir / license_file).read_text(encoding="utf-8")


def test_graphite_theme_matches_ui_tokens():
    """The default theme maps legacy tokens to the same Graphite values as the UI layer."""
    from app.theme_registry import BUILTIN_THEMES, DEFAULT_THEME_ID

    graphite = next(theme for theme in BUILTIN_THEMES if theme["id"] == DEFAULT_THEME_ID)
    pairs = {
        "--bg": "--ui-bg", "--card": "--ui-surface", "--elevated": "--ui-surface-alt",
        "--text": "--ui-ink", "--text-secondary": "--ui-text", "--muted": "--ui-muted",
        "--accent": "--ui-accent", "--text-on-accent": "--ui-on-accent",
        "--good": "--ui-good", "--tolerated": "--ui-tolerated", "--warn": "--ui-marginal", "--crit": "--ui-critical",
    }
    for mode, ui in _modes().items():
        legacy = graphite["theme_data"][mode]
        for legacy_token, ui_token in pairs.items():
            assert legacy[legacy_token].lower() == ui[ui_token].lower(), f"{mode}: {legacy_token} != {ui_token}"
