"""Helpers for replaying stored raw DOCSIS snapshot evidence."""

from __future__ import annotations

from typing import Any, Callable, TypedDict, cast

from .analyzer import analyze
from .types import AnalysisResult, DocsisData


class ReplayComparison(TypedDict):
    """Result of replaying one stored raw payload through the analyzer."""

    timestamp: str
    available: bool
    matches: bool
    differences: list[str]
    stored: AnalysisResult | None
    replayed: AnalysisResult | None


def _comparable(analysis: AnalysisResult) -> dict[str, Any]:
    """Return analyzer-owned fields suitable for replay comparison."""
    return {
        "summary": analysis["summary"],
        "ds_channels": analysis["ds_channels"],
        "us_channels": analysis["us_channels"],
    }


def _differences(stored: AnalysisResult, replayed: AnalysisResult) -> list[str]:
    differences = []
    stored_cmp = _comparable(stored)
    replayed_cmp = _comparable(replayed)
    for section in ("summary", "ds_channels", "us_channels"):
        if stored_cmp[section] != replayed_cmp[section]:
            differences.append(section)
    return differences


def replay_snapshot(
    storage: Any,
    timestamp: str,
    analyzer_fn: Callable[[DocsisData], AnalysisResult] = analyze,
) -> ReplayComparison:
    """Replay a snapshot's stored raw payload and compare it with stored output.

    Snapshots created before raw payload persistence remain valid evidence but are
    not replayable; those return ``available=False`` rather than raising.
    """
    stored = storage.get_snapshot(timestamp)
    if stored is None:
        return {
            "timestamp": timestamp,
            "available": False,
            "matches": False,
            "differences": ["snapshot_missing"],
            "stored": None,
            "replayed": None,
        }
    raw_data = stored.get("raw_data")
    if raw_data is None:
        return {
            "timestamp": timestamp,
            "available": False,
            "matches": False,
            "differences": ["raw_data_missing"],
            "stored": stored,
            "replayed": None,
        }
    replayed = analyzer_fn(cast(DocsisData, raw_data))
    differences = _differences(stored, replayed)
    return {
        "timestamp": timestamp,
        "available": True,
        "matches": not differences,
        "differences": differences,
        "stored": stored,
        "replayed": replayed,
    }
