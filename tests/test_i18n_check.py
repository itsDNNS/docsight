"""Tests for the i18n checker helpers."""

import importlib.util
import json
import re
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "i18n_check.py"
SPEC = importlib.util.spec_from_file_location("docsight_i18n_check", SCRIPT_PATH)
i18n_check = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(i18n_check)


def test_make_template_recurses_into_nested_dicts():
    source = {
        "_meta": {"language_name": "English", "flag": "gb"},
        "title": "Report",
        "issue_labels": {
            "critical": "Critical",
            "nested": {
                "value": "Value",
            },
        },
        "items": ["keep list shape"],
    }

    template = i18n_check.make_template(source)

    assert template["_meta"] == {"language_name": "", "flag": ""}
    assert template["title"] == ""
    assert template["issue_labels"] == {
        "critical": "",
        "nested": {
            "value": "",
        },
    }
    assert template["items"] == []


def test_flatten_key_paths_includes_nested_keys():
    paths = i18n_check.flatten_key_paths({
        "title": "Report",
        "issue_labels": {
            "critical": "Critical",
            "nested": {"value": "Value"},
        },
    })

    assert "title" in paths
    assert "issue_labels" in paths
    assert "issue_labels.critical" in paths
    assert "issue_labels.nested" in paths
    assert "issue_labels.nested.value" in paths


def _string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_values(child)


def test_german_i18n_uses_real_umlauts_in_user_facing_text():
    german_i18n_files = sorted(Path("app").glob("**/i18n/de.json"))
    assert german_i18n_files
    ascii_umlaut_spellings = re.compile(
        r"\b(?:"
        r"fuer|fuehr\w*|waehl\w*|ueber\w*|loesch\w*|groess\w*|"
        r"stoer\w*|koenn\w*|moeglich\w*|haeufig\w*|spaeter\w*|"
        r"pruef\w*|anhaeng\w*|unveraendert|eintraeg\w*"
        r")\b",
        re.IGNORECASE,
    )
    offenders = []

    for path in german_i18n_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for text in _string_values(data):
            if ascii_umlaut_spellings.search(text):
                offenders.append(f"{path}: {text}")

    assert offenders == []
