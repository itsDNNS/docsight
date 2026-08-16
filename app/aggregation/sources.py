"""Small pure projections for non-snapshot evidence sources."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .window import canonical_utc_timestamp


def source_coverage(
    rows: Iterable[Mapping[str, Any]], timestamp_key: str = "timestamp"
) -> dict[str, Any]:
    """Return additive row count and latest valid timestamp for a source."""
    count = 0
    latest: tuple[str, Any] | None = None
    for row in rows:
        raw_count = row.get("sample_count") or row.get("count") or 1
        try:
            count += int(raw_count)
        except (TypeError, ValueError):
            count += 1
        raw_timestamp = row.get(timestamp_key)
        canonical = canonical_utc_timestamp(raw_timestamp)
        if not raw_timestamp or len(canonical) != 20 or not canonical.endswith("Z"):
            continue
        if latest is None or canonical > latest[0]:
            latest = canonical, raw_timestamp
    return {
        "count": count,
        "last_observed_at": latest[1] if latest else None,
    }


def select_preferred_bnetz(
    rows: Sequence[Mapping[str, Any]] | None,
) -> Mapping[str, Any] | None:
    """Select the newest deviation measurement, otherwise the newest row."""
    for row in reversed(rows or []):
        if row.get("verdict_download") == "deviation" or row.get("verdict_upload") == "deviation":
            return row
    return rows[-1] if rows else None
