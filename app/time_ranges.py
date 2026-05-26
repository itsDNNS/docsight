"""Shared UI time-range normalization helpers."""

from __future__ import annotations

NORMALIZED_TIME_RANGE_HOURS: dict[str, int] = {
    "1h": 1,
    "6h": 6,
    "1d": 24,
    "2d": 48,
    "3d": 72,
    "7d": 168,
    "30d": 720,
    "90d": 2160,
}

LEGACY_TREND_RANGE_HOURS: dict[str, int] = {
    "day": 24,
    "week": 168,
    "month": 720,
}


def parse_time_range_hours(
    value: str | None,
    *,
    default: str = "1d",
    allow_legacy: bool = False,
) -> int | None:
    """Return a normalized range as hours, or None when unsupported."""
    normalized = (value or default).strip().lower()
    if normalized in NORMALIZED_TIME_RANGE_HOURS:
        return NORMALIZED_TIME_RANGE_HOURS[normalized]
    if allow_legacy and normalized in LEGACY_TREND_RANGE_HOURS:
        return LEGACY_TREND_RANGE_HOURS[normalized]
    return None
