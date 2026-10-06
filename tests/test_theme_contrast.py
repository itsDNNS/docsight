"""Text and status tokens of shipped themes must meet WCAG 2.2 AA (4.5:1) on every surface."""

import math
import re
from pathlib import Path

import pytest

from app.theme_contrast import (
    AA_TEXT,
    contrast_ratio,
    low_contrast_modes,
    low_contrast_tokens,
    parse_color,
    with_derived_status,
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


def _crit_strong_shares(token):
    """Share of --crit mixed with black in tokens.css, for (dark, light)."""
    css = (ROOT / "app/static/css/tokens.css").read_text(encoding="utf-8")
    dark_block, light_block = css.split('[data-theme="light"]', 1)
    pattern = re.escape(token) + r":\s*color-mix\(in srgb, var\(--crit\) (\d+)%, #000\)"
    return {
        "dark": int(re.search(pattern, dark_block).group(1)) / 100,
        "light": int(re.search(pattern, light_block.split("}", 1)[0]).group(1)) / 100,
    }


@pytest.mark.parametrize("token", ["--crit-strong", "--crit-strong-hover"])
def test_white_text_on_strong_crit_meets_aa_with_every_builtin_crit_color(token):
    for theme in BUILTIN_THEMES:
        for mode, share in _crit_strong_shares(token).items():
            crit = theme["theme_data"][mode]["--crit"]
            mixed = "#" + "".join(
                f"{round(int(crit[index:index + 2], 16) * share):02x}" for index in (1, 3, 5)
            )
            assert _contrast("#ffffff", mixed) >= AA_TEXT, f"{theme['id']} {mode} {token}: {mixed}"


def test_white_text_never_sits_on_a_plain_status_color():
    offenders = []
    for path in [*ROOT.glob("app/static/css/*.css"), *ROOT.glob("app/modules/*/static/*.css")]:
        for rule in re.findall(r"[^{}]+\{[^}]*\}", path.read_text(encoding="utf-8")):
            if re.search(r"color:\s*(#fff|#ffffff|white)\s*;", rule) and re.search(r"background(-color)?:\s*var\(--(good|tolerated|warn|crit|info)\)\s*;", rule):
                offenders.append(f"{path.name}: {rule.split('{')[0].strip()}")
    assert offenders == []


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


def test_button_text_is_judged_against_the_accent():
    assert low_contrast_tokens({"--accent": "#00ff41"}) == ["--text-on-accent"]
    assert low_contrast_tokens({"--accent": "#00ff41", "--text-on-accent": "#0a0a0a"}) == []
    assert low_contrast_tokens({"--accent": "#1d4ed8"}) == []


def _gradient_stops(tokens):
    gradient = tokens.get("--grad-primary")
    if gradient:
        return re.findall(r"#[0-9a-fA-F]{6}", gradient)
    # tokens.css derives the gradient from the accent and --sapphire.
    return [tokens["--accent"], tokens["--sapphire"]]


@pytest.mark.parametrize(
    ("theme_id", "mode"),
    [(theme["id"], mode) for theme in BUILTIN_THEMES for mode in ("dark", "light")],
)
def test_builtin_button_text_meets_aa_on_both_gradient_ends(theme_id, mode):
    tokens = next(theme for theme in BUILTIN_THEMES if theme["id"] == theme_id)["theme_data"][mode]
    for stop in _gradient_stops(tokens):
        ratio = _contrast(tokens["--text-on-accent"], stop)
        assert ratio >= AA_TEXT, f"{tokens['--text-on-accent']} on {stop}: {ratio:.2f}:1"


def test_builtin_themes_produce_no_contrast_warnings():
    assert [theme["id"] for theme in BUILTIN_THEMES if low_contrast_modes(theme["theme_data"])] == []


def _oklch_hue(color):
    def linear(channel):
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(int(color[index:index + 2], 16)) for index in (1, 3, 5))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s_
    b2 = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s_
    return math.degrees(math.atan2(b2, a)) % 360


# Every theme keeps a recognizable green, orange and red for its states: the shade
# follows the theme, the hue family does not.
STATUS_HUE_FAMILIES = {"--good": (123, 167), "--warn": (43, 77), "--crit": (8, 37)}


@pytest.mark.parametrize(
    ("theme_id", "mode"),
    [(theme["id"], mode) for theme in BUILTIN_THEMES for mode in ("dark", "light")],
)
def test_builtin_status_colors_stay_in_their_hue_family(theme_id, mode):
    tokens = next(theme for theme in BUILTIN_THEMES if theme["id"] == theme_id)["theme_data"][mode]
    for name, (low, high) in STATUS_HUE_FAMILIES.items():
        assert low <= _oklch_hue(tokens[name]) <= high, f"{name} = {tokens[name]}"


def test_status_colors_are_judged_including_the_derived_tolerated():
    # Readable green and red, a yellow warning that is too light: the derived mix fails as well.
    tokens = {"--bg": "#ffffff", "--text": "#111111", "--good": "#1a6a01", "--warn": "#f2c200", "--crit": "#b5032e"}
    assert with_derived_status(tokens)["--tolerated"] == "#869600"
    assert low_contrast_tokens(tokens) == ["--tolerated", "--warn"]
    assert with_derived_status({**tokens, "--tolerated": "#5a5200"})["--tolerated"] == "#5a5200"
