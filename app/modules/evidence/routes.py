"""Guided evidence journey routes."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, jsonify, request

from app.tz import get_tz_name, local_date_to_utc_range, local_to_utc, local_today
from app.web import require_auth, get_config_manager, get_storage
from app.modules.journal.storage import JournalStorage

from .checklist import build_checklist, summarize_checklist

bp = Blueprint("evidence_module", __name__)
log = logging.getLogger("docsight.evidence")

_GENERIC_MODEM_TYPES = {"generic", "generic_router", "none"}
_INCIDENT_ID_ERROR = "incident_id must be a positive integer"


def _get_journal_storage():
    core = get_storage()
    if not core:
        return None
    return JournalStorage(core.db_path)


def _get_tz_name() -> str:
    """Return the configured timezone without depending on app.web privates."""
    return get_tz_name(get_config_manager())


def _utc_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _zoneinfo_or_utc(tz_name: str) -> ZoneInfo | timezone:
    """Return configured timezone, falling back to UTC for invalid config."""
    if not tz_name:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        log.warning("Evidence timezone unavailable; falling back to UTC")
        return timezone.utc


def _local_date_bounds_for_window(start_ts: str, end_ts: str, tz_name: str) -> tuple[str, str]:
    """Return configured-local date bounds for a normalized UTC window."""
    tz = _zoneinfo_or_utc(tz_name)
    start_date = _utc_datetime(start_ts).astimezone(tz).strftime("%Y-%m-%d")
    end_date = _utc_datetime(end_ts).astimezone(tz).strftime("%Y-%m-%d")
    return start_date, end_date


def _normalise_window_ts(value: str, tz_name: str) -> str:
    """Return a UTC timestamp for UTC, offset-aware, or datetime-local input."""
    if not value:
        raise ValueError("timestamp required")
    timestamp = value.strip()
    timestamp = timestamp if len(timestamp) > 16 else f"{timestamp}:00"
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return local_to_utc(timestamp, tz_name)


def _get_journal_entries_for_window(db_path: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    start_date, end_date = _local_date_bounds_for_window(start_ts, end_ts, _get_tz_name())
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, date, title, description, icon, incident_id, created_at, updated_at "
            "FROM journal_entries WHERE date >= ? AND date <= ? ORDER BY date DESC, id DESC",
            (start_date, end_date),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_bqm_rows(db_path: str, start_ts: str, end_ts: str) -> list[dict[str, Any]] | None:
    try:
        from app.modules.bqm.storage import BqmStorage
        tz_name = _get_tz_name()
        start_date, end_date = _local_date_bounds_for_window(start_ts, end_ts, tz_name)
        start_epoch = _utc_ts_to_epoch(start_ts)
        end_epoch = _utc_ts_to_epoch(end_ts)
        bqm = BqmStorage(db_path, tz_name)
        rows = bqm.get_data_for_range(start_date, end_date)
    except (ImportError, sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        log.warning("Evidence BQM rows unavailable")
        return None

    filtered: list[dict[str, Any]] = []
    for row in rows:
        try:
            timestamp = row.get("timestamp")
            if not timestamp:
                continue
            row_epoch = _utc_ts_to_epoch(str(timestamp))
        except (AttributeError, TypeError, ValueError):
            continue
        if start_epoch <= row_epoch <= end_epoch:
            filtered.append(row)
    return filtered


def _epoch_to_iso(value: float | int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_ts_to_epoch(value: str) -> float:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _get_connection_monitor_db_path() -> str:
    data_dir = os.environ.get("DATA_DIR", "/data")
    return os.path.join(data_dir, "connection_monitor.db")


def _get_connection_latency_rows(start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    """Return compact Connection Monitor latency evidence rows for a UTC window."""
    db_path = _get_connection_monitor_db_path()
    if not os.path.exists(db_path):
        return []
    start_epoch = _utc_ts_to_epoch(start_ts)
    end_epoch = _utc_ts_to_epoch(end_ts)
    rows: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            raw = conn.execute(
                """
                SELECT
                    COUNT(*) AS sample_count,
                    COUNT(CASE WHEN timeout = 0 AND latency_ms IS NOT NULL THEN 1 END) AS latency_count,
                    AVG(CASE WHEN timeout = 0 THEN latency_ms END) AS avg_latency_ms,
                    MAX(timestamp) AS latest_ts
                FROM connection_samples
                WHERE timestamp >= ? AND timestamp <= ?
                """,
                (start_epoch, end_epoch),
            ).fetchone()
            if raw and (raw["sample_count"] or 0) > 0:
                rows.append({
                    "timestamp": _epoch_to_iso(raw["latest_ts"]),
                    "sample_count": raw["sample_count"],
                    "latency_count": raw["latency_count"],
                    "avg_latency_ms": raw["avg_latency_ms"],
                    "source": "connection_monitor",
                    "tier": "raw",
                })
            aggregated = conn.execute(
                """
                SELECT
                    COALESCE(SUM(sample_count), 0) AS sample_count,
                    COUNT(CASE WHEN avg_latency_ms IS NOT NULL THEN 1 END) AS latency_count,
                    AVG(avg_latency_ms) AS avg_latency_ms,
                    MAX(bucket_start) AS latest_ts
                FROM connection_samples_aggregated
                WHERE bucket_start >= ? AND bucket_start <= ?
                """,
                (start_epoch, end_epoch),
            ).fetchone()
            if aggregated and (aggregated["sample_count"] or 0) > 0:
                rows.append({
                    "timestamp": _epoch_to_iso(aggregated["latest_ts"]),
                    "sample_count": aggregated["sample_count"],
                    "latency_count": aggregated["latency_count"],
                    "avg_latency_ms": aggregated["avg_latency_ms"],
                    "source": "connection_monitor",
                    "tier": "aggregated",
                })
    except sqlite3.Error:
        log.warning("Evidence Connection Monitor rows unavailable")
        return []
    return rows


def _capabilities(config_manager) -> dict[str, Any]:
    modem_type = ""
    if config_manager:
        modem_type = str(config_manager.get("modem_type", "") or "").lower()
    docsis_supported = modem_type not in _GENERIC_MODEM_TYPES
    return {
        "docsis_supported": docsis_supported,
        "speedtest_configured": bool(config_manager.is_speedtest_configured()) if config_manager else False,
        "bqm_configured": bool(config_manager.is_bqm_configured()) if config_manager else False,
        "connection_monitor_configured": bool(config_manager.get("connection_monitor_enabled", False)) if config_manager else False,
        "demo_mode": bool(config_manager.is_demo_mode()) if config_manager else False,
    }


def _window_from_incident(incident: dict[str, Any]) -> dict[str, Any]:
    tz = _get_tz_name()
    start_date = incident.get("start_date")
    if not start_date:
        raise ValueError("incident has no start date")
    start_ts, _ = local_date_to_utc_range(start_date, tz)
    end_date = incident.get("end_date") or local_today(tz)
    _, end_ts = local_date_to_utc_range(end_date, tz)
    return {
        "kind": "incident",
        "incident_id": incident.get("id"),
        "label": incident.get("name") or f"Incident {incident.get('id')}",
        "from": start_ts,
        "to": end_ts,
        "start_date": start_date,
        "end_date": end_date,
    }


def _window_from_args(start_ts: str, end_ts: str) -> dict[str, Any]:
    tz = _get_tz_name()
    start_utc = _normalise_window_ts(start_ts, tz)
    end_utc = _normalise_window_ts(end_ts, tz)
    return {
        "kind": "range",
        "label": f"{start_ts} – {end_ts}",
        "from": start_utc,
        "to": end_utc,
    }


def _parse_incident_id_arg(raw_value: str | None) -> int | None:
    """Parse optional incident_id, preserving malformed input as a 400."""
    if raw_value is None:
        return None
    try:
        incident_id = int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(_INCIDENT_ID_ERROR) from None
    if incident_id <= 0:
        raise ValueError(_INCIDENT_ID_ERROR)
    return incident_id


@bp.route("/api/evidence/checklist")
@require_auth
def api_evidence_checklist():
    """Return a guided evidence checklist for an incident or explicit time window."""
    try:
        incident_id = _parse_incident_id_arg(request.args.get("incident_id"))
    except ValueError:
        return jsonify({"error": _INCIDENT_ID_ERROR}), 400
    start_ts = request.args.get("from")
    end_ts = request.args.get("to")

    has_range = bool(start_ts or end_ts)
    if incident_id is not None and has_range:
        return jsonify({"error": "choose incident_id or from/to, not both"}), 400
    if has_range and not (start_ts and end_ts):
        return jsonify({"error": "from and to required together"}), 400
    if incident_id is None and not has_range:
        return jsonify({"error": "incident_id or from/to required"}), 400

    core = get_storage()
    if not core:
        return jsonify({"error": "storage not available"}), 503

    journal_entries: list[dict[str, Any]] = []
    if incident_id:
        journal = _get_journal_storage()
        if not journal:
            return jsonify({"error": "storage not available"}), 503
        incident = journal.get_incident(incident_id)
        if not incident:
            return jsonify({"error": "Not found"}), 404
        try:
            window = _window_from_incident(incident)
        except ValueError:
            return jsonify({"error": "incident has no usable date range"}), 400
        journal_entries = journal.get_entries(limit=9999, incident_id=incident_id)
    else:
        try:
            window = _window_from_args(start_ts, end_ts)
        except ValueError:
            return jsonify({"error": "from/to must be valid ISO timestamps"}), 400
        journal_entries = _get_journal_entries_for_window(core.db_path, window["from"], window["to"])

    timeline = core.get_correlation_timeline(window["from"], window["to"])
    bqm_rows = _get_bqm_rows(core.db_path, window["from"], window["to"])
    connection_latency_rows = _get_connection_latency_rows(window["from"], window["to"])
    config_manager = get_config_manager()
    capabilities = _capabilities(config_manager)
    items = build_checklist(
        window,
        timeline=timeline,
        journal_entries=journal_entries,
        bqm_rows=bqm_rows,
        connection_latency_rows=connection_latency_rows,
        capabilities=capabilities,
    )
    return jsonify({
        "window": window,
        "capabilities": capabilities,
        "summary": summarize_checklist(items),
        "items": items,
    })
