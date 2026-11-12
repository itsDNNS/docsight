"""Every summary health issue the analyzer emits must have a label everywhere it is shown.

The issue keys are plain strings shared by the dashboard, the snapshot panel,
reports, MQTT and the data export. A key added to the analyzer without labels
shows up as a raw key or disappears silently, so this test derives the keys
from the analyzer source instead of from a hand-maintained list.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from app import analyzer
from app.blueprints.data_bp import _ISSUE_LABELS as EXPORT_LABELS
from app.modules.mqtt.publisher import _ISSUE_LABELS as MQTT_LABELS

ROOT = Path(__file__).resolve().parents[1]
APP_CATALOGS = sorted((ROOT / "app" / "i18n").glob("*.json"))
REPORT_CATALOGS = sorted((ROOT / "app" / "modules" / "reports" / "i18n").glob("*.json"))


def _summary_issue_keys() -> set[str]:
    tree = ast.parse(Path(analyzer.__file__).read_text(encoding="utf-8"))
    analyze_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "analyze")
    keys = set()
    for node in ast.walk(analyze_fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "issues"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


SUMMARY_ISSUES = sorted(_summary_issue_keys())


def _template_map(name: str) -> str:
    html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    match = re.search(r"\{% set " + name + r" = \{(.*?)\} %\}", html, re.S)
    assert match, name
    return match.group(1)


def test_issue_keys_are_found():
    assert len(SUMMARY_ISSUES) >= 15
    assert "us_modulation_tolerated" in SUMMARY_ISSUES
    assert "ds_modulation_tolerated" in SUMMARY_ISSUES


@pytest.mark.parametrize("issue", SUMMARY_ISSUES)
def test_issue_has_dashboard_label_and_description(issue):
    assert f'"{issue}":' in _template_map("issue_labels")
    assert f'"{issue}":' in _template_map("issue_descs")


@pytest.mark.parametrize("issue", SUMMARY_ISSUES)
def test_issue_has_export_and_mqtt_label(issue):
    assert EXPORT_LABELS.get(issue)
    assert MQTT_LABELS.get(issue)


@pytest.mark.parametrize("catalog", APP_CATALOGS, ids=lambda p: p.stem)
def test_issue_has_snapshot_label_in_every_language(catalog):
    strings = json.loads(catalog.read_text(encoding="utf-8"))
    missing = [issue for issue in SUMMARY_ISSUES if not strings.get(f"issue_{issue}")]
    assert not missing, f"{catalog.stem}: {missing}"


@pytest.mark.parametrize("catalog", REPORT_CATALOGS, ids=lambda p: p.stem)
def test_issue_has_report_label_in_every_language(catalog):
    labels = json.loads(catalog.read_text(encoding="utf-8"))["issue_labels"]
    missing = [issue for issue in SUMMARY_ISSUES if not labels.get(issue)]
    assert not missing, f"{catalog.stem}: {missing}"
