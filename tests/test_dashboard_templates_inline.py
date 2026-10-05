"""Dashboard templates keep styling in the stylesheets and behavior in the scripts."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Templates that have been cleaned up; the rest follow view by view.
TEMPLATES = (
    "app/templates/index.html",
    "app/templates/segment_utilization_tab.html",
    "app/modules/comparison/templates/comparison_tab.html",
    "app/modules/modulation/templates/modulation_tab.html",
    "app/modules/speedtest/templates/speedtest_tab.html",
)


def _declarations(style):
    return [part.strip() for part in style.split(";") if part.strip()]


@pytest.mark.parametrize("template", TEMPLATES)
def test_inline_styles_only_pass_values_through_custom_properties(template):
    offenders = []
    for number, line in enumerate((ROOT / template).read_text(encoding="utf-8").splitlines(), start=1):
        for style in re.findall(r'\sstyle="([^"]*)"', line):
            if not all(declaration.startswith("--") for declaration in _declarations(style)):
                offenders.append(f"{template}:{number}: {style}")
    assert offenders == []


@pytest.mark.parametrize("template", TEMPLATES)
def test_event_handlers_are_delegated_instead_of_inline(template):
    assert re.findall(r'\son[a-z]+="', (ROOT / template).read_text(encoding="utf-8")) == []
