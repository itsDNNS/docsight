"""UTC window normalization for snapshot aggregation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .contract import Window


def canonical_utc_timestamp(value: Any) -> str:
    """Normalize a timestamp to second-resolution UTC, preserving invalid input."""
    raw = str(value or "").strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return str(value or "")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def report_bounds(
    snapshots: Sequence[Mapping[str, Any]] | None,
    *,
    window: Window | None = None,
) -> tuple[str, str]:
    """Return requested inclusive bounds or deterministic observed extremes."""
    timestamps = sorted(
        canonical_utc_timestamp(snapshot.get("timestamp"))
        for snapshot in snapshots or []
    )
    start = window.start if window and window.start else (timestamps[0] if timestamps else "-")
    end = window.end if window and window.end else (timestamps[-1] if timestamps else "-")
    return start, end
