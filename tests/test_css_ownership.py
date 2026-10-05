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
