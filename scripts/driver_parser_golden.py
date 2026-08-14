#!/usr/bin/env python3
"""Generate a deterministic characterization matrix for modem parsers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.drivers.driver_format_cases import CASES, DriverFormatCase


def canonical_bytes(value: Any) -> bytes:
    """Serialize with sorted mapping keys while preserving list semantics."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def structural_counts(value: Any) -> dict[str, int]:
    counts = {"channels": 0, "dicts": 0, "lists": 0, "nulls": 0, "scalars": 0}

    def walk(node: Any) -> None:
        if node is None:
            counts["nulls"] += 1
        elif isinstance(node, dict):
            counts["dicts"] += 1
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            counts["lists"] += 1
            for child in node:
                walk(child)
        else:
            counts["scalars"] += 1

    walk(value)
    if isinstance(value, dict):
        if "channelDs" in value and "channelUs" in value:
            for direction in ("channelDs", "channelUs"):
                lanes = value.get(direction, {})
                if isinstance(lanes, dict):
                    counts["channels"] += sum(
                        len(items) for items in lanes.values() if isinstance(items, list)
                    )
        else:
            counts["channels"] += sum(
                len(value.get(key, []))
                for key in ("downstream", "upstream")
                if isinstance(value.get(key), list)
            )
    return counts


def build_report(source_label: str, cases: Iterable[DriverFormatCase] = CASES) -> dict[str, Any]:
    if not source_label:
        raise ValueError("source_label must not be empty")

    rows = []
    for case in sorted(cases, key=lambda item: item.case_id):
        observation = case.observe()
        row: dict[str, Any] = {
            "case_id": case.case_id,
            "driver": case.driver,
            "family": case.family,
            "output_sha256": canonical_sha256(observation.output),
            "structural_counts": structural_counts(observation.output),
        }
        if observation.diagnostics:
            row["diagnostics_sha256"] = canonical_sha256(observation.diagnostics)
        rows.append(row)

    return {
        "format": "docsight-driver-parser-golden-v1",
        "source_label": source_label,
        "cases": rows,
    }


def write_report(output: Path, source_label: str) -> None:
    report = build_report(source_label)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(report) + b"\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-label", required=True, help="Source/base label embedded verbatim")
    parser.add_argument("--output", required=True, type=Path, help="Explicit JSON output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    write_report(args.output, args.source_label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
