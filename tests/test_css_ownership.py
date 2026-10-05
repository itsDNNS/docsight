"""Shared components are defined once, in components.css."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = "app/static/css/components.css"
# Base button and its variants; context rules such as `.modal-footer .btn` stay allowed.
BUTTON_RULE = re.compile(
    r"(?m)^\s*\.btn(?:-(?:primary|secondary|ghost|danger|accent|muted|sm|small))?(?::[a-z-]+(?:\([^)]*\))?)*(?:\s+svg)?\s*[{,]"
)
# Form fields and the toggle switch, including their states and light-mode variants.
FORM_RULE = re.compile(
    r"(?m)^\s*(?:\[data-theme=\"light\"\]\s+)?(?:\.form-(?:field|label|hint|input|select|grid)|\.toggle(?:-slider)?)(?![\w-])[^{,]*[{,]"
)

# The card and the glass surface.
CARD_RULE = re.compile(
    r"(?m)^\s*(?:\[data-theme=\"light\"\]\s+)?(?:\.card(?:-(?:header|title-group|title|subtitle|icon))?|\.glass)(?![\w-])(?::[a-z-]+)*(?:\s+(?:svg|i|>\s*div))?\s*[{,]"
)

# The save bar.
SAVE_BAR_RULE = re.compile(r"(?m)^\s*(?:\[data-theme=\"light\"\]\s+)?\.save-bar(?:-[a-z]+)?(?![\w-])[^{,]*[{,]")


def _stylesheets():
    tracked = subprocess.run(["git", "ls-files", "app"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [path for path in tracked.split() if path.endswith(".css") and "/vendor/" not in path]


def test_buttons_are_defined_only_in_the_component_stylesheet():
    offenders = [
        f"{path}: {match.group(0).strip()}"
        for path in _stylesheets() if path != OWNER
        for match in BUTTON_RULE.finditer((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert BUTTON_RULE.search((ROOT / OWNER).read_text(encoding="utf-8"))


def test_form_fields_and_the_toggle_are_defined_only_in_the_component_stylesheet():
    offenders = [
        f"{path}: {match.group(0).strip()}"
        for path in _stylesheets() if path != OWNER
        for match in FORM_RULE.finditer((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert FORM_RULE.search((ROOT / OWNER).read_text(encoding="utf-8"))


def test_cards_are_defined_only_in_the_component_stylesheet():
    offenders = [
        f"{path}: {match.group(0).strip()}"
        for path in _stylesheets() if path != OWNER
        for match in CARD_RULE.finditer((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert CARD_RULE.search((ROOT / OWNER).read_text(encoding="utf-8"))



def test_the_save_bar_is_defined_only_in_the_component_stylesheet():
    offenders = [
        f"{path}: {match.group(0).strip()}"
        for path in _stylesheets() if path != OWNER
        for match in SAVE_BAR_RULE.finditer((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert SAVE_BAR_RULE.search((ROOT / OWNER).read_text(encoding="utf-8"))

# One-sided edges and inset side shadows; status shows through icon, badge, text color or tint.
SIDE_EDGE = re.compile(r"(?:border-(?:left|inline-start)(?:-color)?|box-shadow)\s*:\s*([^;}]*)")
COLORED = re.compile(r"var\(--(?:accent|amethyst|good|warn|crit|sapphire)")


def _is_side_stripe(prop, value):
    if prop.startswith("box-shadow"):
        return re.match(r"inset\s+-?[1-9]\d*px\s+0\s+0\s", value) is not None
    if "transparent" in value.split("solid")[-1]:
        return False  # CSS triangles and hidden edges
    width = re.match(r"\s*(\d+)px", value)
    return bool(COLORED.search(value)) or (width is not None and int(width.group(1)) > 2)


def test_no_stylesheet_marks_status_with_a_colored_side_stripe():
    offenders = [
        f"{path}: {match.group(0).strip()}"
        for path in _stylesheets()
        for match in SIDE_EDGE.finditer((ROOT / path).read_text(encoding="utf-8"))
        if _is_side_stripe(match.group(0), match.group(1))
    ]
    assert offenders == []
