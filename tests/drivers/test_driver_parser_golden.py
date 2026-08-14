"""Determinism and canonical-byte tests for the golden matrix generator."""

from __future__ import annotations

import json
import math

import pytest

from scripts.driver_parser_golden import (
    build_report,
    canonical_bytes,
    canonical_sha256,
    main,
)
from tests.drivers.driver_format_cases import CASES


def test_canonical_serialization_sorts_only_mapping_keys_and_preserves_list_order():
    value = {"z": [{"b": 2, "a": 1}, {"a": 0}], "a": "ä"}
    assert canonical_bytes(value) == b'{"a":"\xc3\xa4","z":[{"a":1,"b":2},{"a":0}]}'


def test_canonical_digest_is_stable_across_mapping_insertion_order():
    left = {"b": 2, "a": [{"d": 4, "c": 3}]}
    right = {"a": [{"c": 3, "d": 4}], "b": 2}
    assert canonical_bytes(left) == canonical_bytes(right)
    assert canonical_sha256(left) == canonical_sha256(right)


def test_null_zero_and_missing_keys_have_distinct_canonical_bytes_and_digests():
    values = [{"power": None}, {"power": 0}, {}]
    assert len({canonical_bytes(value) for value in values}) == 3
    assert len({canonical_sha256(value) for value in values}) == 3


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_canonical_serialization_rejects_non_finite_numbers(value):
    with pytest.raises(ValueError, match="JSON compliant"):
        canonical_bytes({"value": value})


def test_report_rows_are_sorted_and_contain_only_digests_counts_and_labels():
    report = build_report("c1e4946880a5be8d29d7db92587f987bf426920c")
    rows = report["cases"]
    assert [row["case_id"] for row in rows] == sorted(case.case_id for case in CASES)
    assert all(len(row["output_sha256"]) == 64 for row in rows)
    assert all(
        set(row) <= {
            "case_id",
            "driver",
            "family",
            "output_sha256",
            "diagnostics_sha256",
            "structural_counts",
        }
        for row in rows
    )
    encoded = canonical_bytes(report)
    assert b"modem.invalid" not in encoded
    assert b"/tmp/" not in encoded


def test_cli_writes_identical_bytes_twice_for_same_source_label(tmp_path):
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    label = "source-base-c1e4946"
    assert main(["--source-label", label, "--output", str(first)]) == 0
    assert main(["--source-label", label, "--output", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    parsed = json.loads(first.read_text(encoding="utf-8"))
    assert parsed["source_label"] == label
    assert len(parsed["cases"]) == len(CASES)
