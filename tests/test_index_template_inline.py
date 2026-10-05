"""The dashboard template keeps styling in the stylesheets and behavior in the scripts."""

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "app" / "templates" / "index.html"


def _declarations(style):
    return [part.strip() for part in style.split(";") if part.strip()]


def test_inline_styles_only_pass_values_through_custom_properties():
    offenders = []
    for number, line in enumerate(INDEX.read_text(encoding="utf-8").splitlines(), start=1):
        for style in re.findall(r'\sstyle="([^"]*)"', line):
            if not all(declaration.startswith("--") for declaration in _declarations(style)):
                offenders.append(f"index.html:{number}: {style}")
    assert offenders == []


def test_event_handlers_are_delegated_instead_of_inline():
    template = INDEX.read_text(encoding="utf-8")
    assert re.findall(r'\son[a-z]+="', template) == []
