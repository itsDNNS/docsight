"""Tests for the i18n checker helpers."""

import importlib.util
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
