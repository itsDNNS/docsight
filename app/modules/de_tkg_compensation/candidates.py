"""Read-only optional-source adapters and report-window helpers."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.storage.sqlite import open_read


log = logging.getLogger("docsight.de_tkg_compensation")

# These are proposal-generation safety bounds, never limits on a manual claim.
CONNECTION_CANDIDATE_LOOKBACK_DAYS = 30
CONNECTION_CANDIDATE_MAX_TARGETS = 16
CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET = 2_000
CONNECTION_CANDIDATE_MAX_RESULTS = 64
INCIDENT_CANDIDATE_MAX_RESULTS = 64


def _iso_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zone(tz_name: str):
    try:
        return ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_input(value: float, tz_name: str) -> str:
    return datetime.fromtimestamp(value, timezone.utc).astimezone(_zone(tz_name)).strftime(
        "%Y-%m-%dT%H:%M"
    )


def _suggested_local_days(start_epoch: float, end_epoch: float, tz_name: str) -> list[str]:
    zone = _zone(tz_name)
    start = datetime.fromtimestamp(start_epoch, timezone.utc).astimezone(zone).date()
    end = datetime.fromtimestamp(end_epoch, timezone.utc).astimezone(zone).date()
    days = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _merge_outages(outages: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for outage in sorted(outages, key=lambda item: (item["start_epoch"], item["end_epoch"])):
        if merged and outage["start_epoch"] <= merged[-1]["end_epoch"]:
            merged[-1]["end_epoch"] = max(merged[-1]["end_epoch"], outage["end_epoch"])
            merged[-1]["target_count"] += 1
            merged[-1]["ongoing"] = merged[-1]["ongoing"] or outage["ongoing"]
        else:
            merged.append(dict(outage))
    return merged


def load_connection_monitor_candidates(db_path: str, tz_name: str) -> list[dict]:
    """Read bounded outage proposals without mutating the foreign database.

    Lookback, sample, target, and result limits protect this optional adapter only.
    They never constrain manually entered legal claim windows or confirmed days.
    """
    outages: list[dict] = []
    try:
        with open_read(db_path) as conn:
            targets = conn.execute(
                "SELECT id FROM connection_targets WHERE enabled = 1 ORDER BY id LIMIT ?",
                (CONNECTION_CANDIDATE_MAX_TARGETS,),
            ).fetchmany(CONNECTION_CANDIDATE_MAX_TARGETS)
            for target in targets:
                rows = conn.execute(
                    "SELECT timestamp, timeout FROM connection_samples "
                    "WHERE target_id = ? AND timestamp >= ("
                    "SELECT COALESCE(MAX(timestamp), 0) - ? FROM connection_samples "
                    "WHERE target_id = ?) ORDER BY timestamp DESC LIMIT ?",
                    (
                        target["id"],
                        CONNECTION_CANDIDATE_LOOKBACK_DAYS * 86_400,
                        target["id"],
                        CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET,
                    ),
                ).fetchmany(CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET)
                run_start = None
                run_count = 0
                last_timestamp = None
                for row in reversed(rows):
                    timestamp = float(row["timestamp"])
                    last_timestamp = timestamp
                    if row["timeout"]:
                        run_start = timestamp if run_start is None else run_start
                        run_count += 1
                    else:
                        if run_start is not None and run_count >= 5:
                            outages.append({
                                "start_epoch": run_start,
                                "end_epoch": timestamp,
                                "target_count": 1,
                                "ongoing": False,
                            })
                        run_start, run_count = None, 0
                if run_start is not None and run_count >= 5 and last_timestamp is not None:
                    outages.append({
                        "start_epoch": run_start,
                        "end_epoch": last_timestamp,
                        "target_count": 1,
                        "ongoing": True,
                    })
    except (OSError, sqlite3.Error, TypeError, ValueError):
        log.warning("TKG Connection Monitor candidates unavailable")
        return []

    result = []
    merged = _merge_outages(outages)[-CONNECTION_CANDIDATE_MAX_RESULTS:]
    for index, outage in enumerate(merged, start=1):
        result.append({
            "id": f"telemetry-{index}",
            "origin": "telemetry",
            "derived": True,
            "window_from": _iso_epoch(outage["start_epoch"]),
            "window_to": _iso_epoch(outage["end_epoch"]),
            "window_from_local": _local_input(outage["start_epoch"], tz_name),
            "window_to_local": _local_input(outage["end_epoch"], tz_name),
            "suggested_days": _suggested_local_days(
                outage["start_epoch"], outage["end_epoch"], tz_name
            ),
            "target_count": outage["target_count"],
            "ongoing": outage["ongoing"],
            "restoration_suggested": False,
            "proposal_lookback_days": CONNECTION_CANDIDATE_LOOKBACK_DAYS,
            "proposal_sample_limit": CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET,
        })
    return result


def load_incident_candidates(
    db_path: str, tz_name: str, *, local_today_value: str | None = None
) -> list[dict]:
    zone = _zone(tz_name)
    today = date.fromisoformat(local_today_value) if local_today_value else datetime.now(zone).date()
    try:
        with open_read(db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, start_date, end_date FROM incidents "
                "WHERE status = 'open' AND start_date IS NOT NULL "
                "ORDER BY start_date DESC, id DESC LIMIT ?",
                (INCIDENT_CANDIDATE_MAX_RESULTS,),
            ).fetchmany(INCIDENT_CANDIDATE_MAX_RESULTS)
    except (OSError, sqlite3.Error):
        log.warning("TKG incident candidates unavailable")
        return []
    result = []
    for row in rows:
        try:
            start_local = datetime.fromisoformat(f"{row['start_date']}T00:00:00").replace(tzinfo=zone)
            ongoing = not bool(row["end_date"])
            end_date = row["end_date"] or today.isoformat()
            end_local = datetime.fromisoformat(f"{end_date}T23:59:59").replace(tzinfo=zone)
        except (TypeError, ValueError):
            continue
        if end_local < start_local:
            continue
        result.append({
            "id": f"incident-{row['id']}",
            "incident_id": row["id"],
            "label": row["name"],
            "origin": "incident",
            "derived": True,
            "window_from": start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_to": end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_from_local": start_local.strftime("%Y-%m-%dT%H:%M"),
            "window_to_local": end_local.strftime("%Y-%m-%dT%H:%M"),
            "suggested_days": _suggested_local_days(
                start_local.timestamp(), end_local.timestamp(), tz_name
            ),
            "ongoing": ongoing,
            "restoration_suggested": False,
        })
    return result


def chunk_report_windows(window_from: str, window_to: str) -> list[dict[str, str | int]]:
    """Split an evidence range into report-compatible windows of at most 90 days."""
    start = datetime.fromisoformat(window_from.replace("Z", "+00:00"))
    end = datetime.fromisoformat(window_to.replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError("invalid report window")
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=90), end)
        chunks.append({
            "index": len(chunks) + 1,
            "from": cursor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": chunk_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if chunk_end == end:
            break
        cursor = chunk_end + timedelta(seconds=1)
    return chunks
