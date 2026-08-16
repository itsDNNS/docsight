"""Deterministic snapshot-period aggregation domain API."""

from .contract import (
    AGGREGATION_SCHEMA_VERSION,
    Coverage,
    PeriodAggregate,
    ThresholdContext,
    Window,
)
from .period import aggregate_snapshot_period
from .provenance import derive_diagnostic_notes, derive_historical
from .sources import select_preferred_bnetz, source_coverage
from .window import canonical_utc_timestamp, report_bounds

__all__ = [
    "AGGREGATION_SCHEMA_VERSION",
    "Coverage",
    "PeriodAggregate",
    "ThresholdContext",
    "Window",
    "aggregate_snapshot_period",
    "canonical_utc_timestamp",
    "derive_diagnostic_notes",
    "derive_historical",
    "report_bounds",
    "select_preferred_bnetz",
    "source_coverage",
]
