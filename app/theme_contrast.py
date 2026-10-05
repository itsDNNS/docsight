"""Text contrast checks for theme color tokens (WCAG 2.2, normal-size text)."""

from __future__ import annotations

import re

AA_TEXT = 4.5
TEXT_TOKENS = ("--text", "--text-secondary", "--muted")
# --bg comes first: a theme that only sets the core tokens paints the page from it.
SURFACE_TOKENS = ("--bg", "--surface", "--void", "--elevated", "--void-deep")
# Button text on the accent color; DOCSight uses white unless the theme sets it.
ON_ACCENT_DEFAULT = "#ffffff"

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)$"
)


def parse_color(value: object) -> tuple[int, int, int] | None:
    """Return an opaque sRGB color, or None when it cannot be judged on its own.

    Translucent colors depend on what is underneath, so they are not judged.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _HEX.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))
    match = _RGB.match(text)
    if match:
        if match.group(4) is not None and float(match.group(4)) < 1:
            return None
        channels = tuple(int(match.group(index)) for index in (1, 2, 3))
        if all(0 <= channel <= 255 for channel in channels):
            return channels
    return None


def _luminance(color: tuple[int, int, int]) -> float:
    linear = []
    for channel in color:
        value = channel / 255
        linear.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def worst_contrast(tokens: dict, name: str) -> float | None:
    """Lowest ratio of a text token against the theme's own opaque surfaces."""
    foreground = parse_color(tokens.get(name))
    backgrounds = [color for color in (parse_color(tokens.get(key)) for key in SURFACE_TOKENS) if color]
    if foreground is None or not backgrounds:
        return None
    return min(contrast_ratio(foreground, background) for background in backgrounds)


def low_contrast_tokens(tokens: dict) -> list[str]:
    """Text tokens below 4.5:1 on at least one of the theme's surfaces, and button
    text below 4.5:1 on the accent color."""
    issues = []
    for name in TEXT_TOKENS:
        ratio = worst_contrast(tokens, name)
        if ratio is not None and ratio < AA_TEXT:
            issues.append(name)
    accent = parse_color(tokens.get("--accent"))
    on_accent = parse_color(tokens.get("--text-on-accent", ON_ACCENT_DEFAULT))
    if accent and on_accent and contrast_ratio(on_accent, accent) < AA_TEXT:
        issues.append("--text-on-accent")
    return issues


def low_contrast_modes(theme_data: dict | None) -> list[str]:
    """Color modes ("dark", "light") in which some text falls below AA."""
    if not isinstance(theme_data, dict):
        return []
    return [
        mode for mode in ("dark", "light")
        if isinstance(theme_data.get(mode), dict) and low_contrast_tokens(theme_data[mode])
    ]
