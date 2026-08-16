"""Plain-data contracts for deterministic snapshot-period aggregation."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypedDict

AGGREGATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Window:
    """Inclusive UTC bounds supplied by the storage adapter."""

    start: str
    end: str


class Coverage(TypedDict):
    """Exhaustive source-value states within all snapshots in a period."""

    samples: int
    nulls: int
    unsupported: int
    invalid: int
    missing: int
    total: int


@dataclass(frozen=True)
class ThresholdContext:
    """Independent active-threshold data and its profile provenance."""

    raw: Mapping[str, Any]
    profile_id: str | None
    profile_version: str | None

    @classmethod
    def from_analyzer_snapshot(cls, snapshot: Mapping[str, Any]) -> ThresholdContext:
        """Build an isolated context from :func:`app.analyzer.threshold_snapshot`."""
        raw = snapshot.get("thresholds")
        copied = copy.deepcopy(raw) if isinstance(raw, Mapping) else {}
        profile = snapshot.get("profile")
        profile = profile if isinstance(profile, Mapping) else {}
        return cls(
            raw=MappingProxyType(copied),
            profile_id=profile.get("id"),
            profile_version=profile.get("version"),
        )


class ThresholdProfileProvenance(TypedDict):
    id: str | None
    version: str | None


class AnalyzerProvenanceEntry(TypedDict):
    analyzer_schema: int | str | None
    app_version: str | None
    threshold_profile: ThresholdProfileProvenance
    count: int


class SnapshotAnalyzerProvenance(TypedDict):
    legacy_no_metadata: int
    metadata: list[AnalyzerProvenanceEntry]


class AggregateProvenance(TypedDict):
    source: str
    active_threshold_profile: ThresholdProfileProvenance
    stored_snapshot_analyzers: SnapshotAnalyzerProvenance


class PeriodAggregate(TypedDict):
    """JSON-serializable deterministic projection of a snapshot period."""

    schema_version: int
    window: dict[str, str]
    snapshot_count: int
    first_observed_at: str | None
    last_observed_at: str | None
    latest_snapshot: Mapping[str, Any] | None
    provenance: AggregateProvenance
    health_distribution: dict[Any, int]
    worst: dict[str, Any]
    metric_coverage: dict[str, Coverage]
    averages: dict[str, float | None]
    totals: dict[str, Any]
    worst_channels: dict[str, list[tuple[Any, int]]]
    samples: list[dict[str, Any]]
    diagnostic_notes: list[dict[str, Any]]
