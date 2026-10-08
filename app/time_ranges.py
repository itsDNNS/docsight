"""Shared UI time-range normalization helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from app.tz import local_to_utc

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


def parse_window_end(value: str | None, tz_name: str | None) -> datetime | None | bool:
    """End of a window in the past as an aware UTC datetime.

    ``value`` is wall-clock time in the configured zone, as the charts show it
    (``YYYY-MM-DDTHH:MM`` or with seconds). Returns None for no end or an end
    that is not in the past (the window ends now), and False when the value
    cannot be read.
    """
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            local = datetime.strptime(value[:19], fmt)
            break
        except ValueError:
            continue
    else:
        return False
    utc = local_to_utc(local.strftime("%Y-%m-%dT%H:%M:%S"), tz_name)
    end = datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return end if end < datetime.now(timezone.utc) else None
