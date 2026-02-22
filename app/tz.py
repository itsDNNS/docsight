"""Timezone utilities — single source of truth for all timestamp operations.

All internal timestamps use UTC with Z-suffix: "YYYY-MM-DDTHH:MM:SSZ"
Conversion to local time happens only at the display boundary (web/charts/reports).
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Canonical UTC format used throughout the application
_UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"
_LOCAL_FMT = "%Y-%m-%dT%H:%M:%S"


def utc_now():
    """Return current UTC time as 'YYYY-MM-DDTHH:MM:SSZ'."""
    return datetime.now(timezone.utc).strftime(_UTC_FMT)


def utc_cutoff(days=0, hours=0):
    """Return UTC timestamp N days/hours in the past as 'YYYY-MM-DDTHH:MM:SSZ'."""
    dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    return dt.strftime(_UTC_FMT)


def to_local(utc_ts, tz_name):
    """Convert UTC timestamp string to local time string (no Z suffix).

    Args:
        utc_ts: UTC timestamp like '2026-01-15T14:30:00Z' or '2026-01-15T14:30:00'
        tz_name: IANA timezone name like 'Europe/Berlin'

    Returns:
        Local time string like '2026-01-15T15:30:00'
    """
    if not utc_ts or not tz_name:
        return (utc_ts or "").rstrip("Z")
    dt = _parse_utc(utc_ts)
    local_dt = dt.astimezone(ZoneInfo(tz_name))
    return local_dt.strftime(_LOCAL_FMT)


def to_local_display(utc_ts, tz_name, fmt="%Y-%m-%d %H:%M:%S"):
    """Convert UTC timestamp to a formatted local display string.

    Args:
        utc_ts: UTC timestamp string
        tz_name: IANA timezone name
        fmt: strftime format string

    Returns:
        Formatted local time string
    """
    if not utc_ts or not tz_name:
        return (utc_ts or "").rstrip("Z")
    dt = _parse_utc(utc_ts)
    local_dt = dt.astimezone(ZoneInfo(tz_name))
    return local_dt.strftime(fmt)


def local_to_utc(local_ts, tz_name):
    """Convert a naive local timestamp string to UTC with Z-suffix.

    Uses ZoneInfo for correct DST handling. For ambiguous times during
    fall-back (fold), assumes the first occurrence (summer time / fold=0).

    Args:
        local_ts: Local time string like '2026-06-15T14:30:00'
        tz_name: IANA timezone name

    Returns:
        UTC string like '2026-06-15T12:30:00Z'
    """
    if not local_ts or not tz_name:
        # No timezone info: assume already UTC, just add Z
        return (local_ts or "") + "Z" if local_ts else ""
    ts_clean = local_ts.rstrip("Z")
    if "." in ts_clean:
        ts_clean = ts_clean.split(".")[0]
    naive = datetime.strptime(ts_clean, _LOCAL_FMT)
    tz = ZoneInfo(tz_name)
    local_dt = naive.replace(tzinfo=tz)
    utc_dt = local_dt.astimezone(timezone.utc)
    return utc_dt.strftime(_UTC_FMT)


def local_now(tz_name, fmt=_LOCAL_FMT):
    """Return current local time in the given timezone.

    Useful for scheduling comparisons (e.g. 'is it past snapshot_time?').
    """
    if not tz_name:
        return datetime.now(timezone.utc).strftime(fmt)
    return datetime.now(ZoneInfo(tz_name)).strftime(fmt)


def local_today(tz_name):
    """Return today's date (YYYY-MM-DD) in the user's timezone."""
    if not tz_name:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def local_date_to_utc_range(date_str, tz_name):
    """Convert a local date (YYYY-MM-DD) to a UTC start/end range.

    Returns (start_utc, end_utc) covering the full local day in UTC.
    E.g. for 'Europe/Berlin' (UTC+1): '2026-01-15' →
         ('2026-01-14T23:00:00Z', '2026-01-15T22:59:59Z')
    """
    if not tz_name:
        return (f"{date_str}T00:00:00Z", f"{date_str}T23:59:59Z")
    start_utc = local_to_utc(f"{date_str}T00:00:00", tz_name)
    # End of day: 23:59:59 local
    end_utc = local_to_utc(f"{date_str}T23:59:59", tz_name)
    return (start_utc, end_utc)


def guess_iana_timezone():
    """Best-effort guess of the current IANA timezone from the system.

    Returns an IANA name like 'Europe/Berlin' or '' if detection fails.
    No Flask dependency — safe to call from main.py or storage.py.
    """
    try:
        link = os.readlink("/etc/localtime")
        for marker in ("/zoneinfo/",):
            if marker in link:
                return link.split(marker, 1)[1]
    except (OSError, ValueError):
        pass
    tz_env = os.environ.get("TZ", "")
    if "/" in tz_env:
        return tz_env
    return ""


def _parse_utc(ts):
    """Parse a UTC timestamp string into a timezone-aware datetime.

    Handles: '2026-01-15T14:30:00Z', '2026-01-15T14:30:00',
             '2026-01-15T14:30:00.123Z'
    """
    ts_clean = ts.rstrip("Z")
    if "." in ts_clean:
        ts_clean = ts_clean.split(".")[0]
    naive = datetime.strptime(ts_clean, _LOCAL_FMT)
    return naive.replace(tzinfo=timezone.utc)
