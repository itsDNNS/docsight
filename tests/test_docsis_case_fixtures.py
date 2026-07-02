"""Golden replay tests for public-safe DOCSIS evidence fixtures."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from app.analyzer import analyze, apply_cumulative_error_baseline
from app.event_detector import EventDetector
from app.modules.evidence.checklist import build_checklist

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "docsis_cases"
FIXTURE_FILES = sorted(FIXTURE_DIR.glob("*.json"))

_PRIVATE_PATTERNS = {
    "ipv4": re.compile(r"\b(?:10|127|169\.254|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
    "mac": re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b"),
}
_SECRET_KEY_MARKERS = (
    "account",
    "authorization",
    "cookie",
    "mac",
    "password",
    "secret",
    "serial",
    "token",
)


def _load_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


ANALYZER_FIXTURE_FILES = [path for path in FIXTURE_FILES if "raw" in _load_case(path)]
EVENT_FIXTURE_FILES = [path for path in FIXTURE_FILES if _load_case(path).get("expect", {}).get("events")]
CHECKLIST_FIXTURE_FILES = [path for path in FIXTURE_FILES if _load_case(path).get("expect", {}).get("checklist")]


def _assert_subset(actual: Any, expected: Any, path: str = "root") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        for key, value in expected.items():
            assert key in actual, f"{path}.{key} missing"
            _assert_subset(actual[key], value, f"{path}.{key}")
        return
    if isinstance(expected, list):
        assert isinstance(actual, list), path
        for item in expected:
            assert item in actual, f"{path} missing {item!r}"
        return
    assert actual == expected, path


def _assert_channel_expectations(channels: Sequence[Mapping[str, Any]], expected_rows: list[dict[str, Any]], path: str) -> None:
    for expected in expected_rows:
        index = expected["index"]
        expected_values = {k: v for k, v in expected.items() if k != "index"}
        assert index < len(channels), f"{path}[{index}] missing"
        _assert_subset(channels[index], expected_values, f"{path}[{index}]")


@pytest.mark.parametrize("fixture_path", ANALYZER_FIXTURE_FILES, ids=lambda p: p.stem)
def test_docsis_fixture_analyzer_golden_contracts(fixture_path: Path):
    case = _load_case(fixture_path)
    previous = analyze(case["previous_raw"]) if "previous_raw" in case else None
    analysis = analyze(case["raw"])
    if case.get("postprocess") == "cumulative_error_baseline":
        apply_cumulative_error_baseline(analysis, previous, recent_spike_active=False)

    expect = case["expect"]
    _assert_subset(analysis["summary"], expect.get("summary", {}), f"{case['id']}.summary")
    _assert_subset(analysis["summary"], expect.get("summary_contains", {}), f"{case['id']}.summary_contains")
    _assert_channel_expectations(analysis["ds_channels"], expect.get("ds_channels", []), f"{case['id']}.ds_channels")
    _assert_channel_expectations(analysis["us_channels"], expect.get("us_channels", []), f"{case['id']}.us_channels")


@pytest.mark.parametrize("fixture_path", EVENT_FIXTURE_FILES, ids=lambda p: p.stem)
def test_docsis_fixture_event_golden_contracts(fixture_path: Path):
    case = _load_case(fixture_path)
    expected_events = case.get("expect", {}).get("events")
    detector = EventDetector()
    detector.check(analyze(case["previous_raw"]))
    events = detector.check(analyze(case["raw"]))
    event_types = [event["event_type"] for event in events]

    for expected in expected_events:
        assert expected in event_types


@pytest.mark.parametrize("fixture_path", CHECKLIST_FIXTURE_FILES, ids=lambda p: p.stem)
def test_docsis_fixture_checklist_golden_contracts(fixture_path: Path):
    case = _load_case(fixture_path)
    checklist_input = case.get("checklist")
    expected = case.get("expect", {}).get("checklist")
    assert checklist_input is not None
    assert expected is not None
    checklist = build_checklist(
        checklist_input["window"],
        timeline=checklist_input.get("timeline", []),
        journal_entries=checklist_input.get("journal_entries", []),
        bqm_rows=checklist_input.get("bqm_rows", []),
        connection_latency_rows=checklist_input.get("connection_latency_rows", []),
        capabilities=checklist_input.get("capabilities", {}),
    )
    by_key = {item["key"]: item for item in checklist}

    for key, status in expected.items():
        assert by_key[key]["status"] == status


def test_docsis_fixture_corpus_is_public_safe():
    assert FIXTURE_FILES, "expected DOCSIS fixture corpus"
    for path in FIXTURE_FILES:
        text = path.read_text(encoding="utf-8")
        for label, pattern in _PRIVATE_PATTERNS.items():
            assert pattern.search(text) is None, f"{path.name} contains private-looking {label}"
        case = json.loads(text)
        _assert_no_secret_keys(case, path.name)


def _assert_no_secret_keys(value: Any, fixture_name: str, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_lower = str(key).lower()
            assert not any(marker in key_lower for marker in _SECRET_KEY_MARKERS), (
                f"{fixture_name} contains private-looking key {path}.{key}"
            )
            _assert_no_secret_keys(child, fixture_name, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_keys(child, fixture_name, f"{path}[{index}]")
