"""Guided evidence journey routes."""

from __future__ import annotations

import sqlite3
import logging
from typing import Any

from flask import Blueprint, jsonify, request

from app.tz import local_date_to_utc_range, local_to_utc, local_today
from app.web import require_auth, get_config_manager, get_storage, _get_tz_name
from app.modules.journal.storage import JournalStorage

from .checklist import build_checklist, summarize_checklist

bp = Blueprint("evidence_module", __name__)
log = logging.getLogger("docsight.evidence")

_GENERIC_MODEM_TYPES = {"generic", "generic_router", "none"}


def _get_journal_storage():
    core = get_storage()
    if not core:
        return None
    return JournalStorage(core.db_path)


def _date_from_ts(value: str) -> str:
    return value[:10]


def _normalise_window_ts(value: str, tz_name: str) -> str:
    """Return a UTC timestamp for either UTC ISO or datetime-local input."""
    if value.endswith("Z"):
        return value
    local_value = value if len(value) > 16 else f"{value}:00"
    return local_to_utc(local_value, tz_name)


def _get_journal_entries_for_window(db_path: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    start_date = _date_from_ts(start_ts)
    end_date = _date_from_ts(end_ts)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, date, title, description, icon, incident_id, created_at, updated_at "
            "FROM journal_entries WHERE date >= ? AND date <= ? ORDER BY date DESC, id DESC",
            (start_date, end_date),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_bqm_rows(db_path: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    try:
        from app.modules.bqm.storage import BqmStorage
        bqm = BqmStorage(db_path, _get_tz_name())
        return bqm.get_data_for_range(_date_from_ts(start_ts), _date_from_ts(end_ts))
    except Exception:
        log.warning("Evidence BQM rows unavailable")
        return []


def _capabilities(config_manager) -> dict[str, Any]:
    modem_type = ""
    if config_manager:
        modem_type = str(config_manager.get("modem_type", "") or "").lower()
    docsis_supported = modem_type not in _GENERIC_MODEM_TYPES
    return {
        "docsis_supported": docsis_supported,
        "speedtest_configured": bool(config_manager.is_speedtest_configured()) if config_manager else False,
        "bqm_configured": bool(config_manager.is_bqm_configured()) if config_manager else False,
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


@bp.route("/api/evidence/checklist")
@require_auth
def api_evidence_checklist():
    """Return a guided evidence checklist for an incident or explicit time window."""
    incident_id = request.args.get("incident_id", type=int)
    start_ts = request.args.get("from")
    end_ts = request.args.get("to")

    has_range = bool(start_ts or end_ts)
    if incident_id and has_range:
        return jsonify({"error": "choose incident_id or from/to, not both"}), 400
    if has_range and not (start_ts and end_ts):
        return jsonify({"error": "from and to required together"}), 400
    if not incident_id and not has_range:
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
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        journal_entries = journal.get_entries(limit=9999, incident_id=incident_id)
    else:
        window = _window_from_args(start_ts, end_ts)
        journal_entries = _get_journal_entries_for_window(core.db_path, start_ts, end_ts)

    timeline = core.get_correlation_timeline(window["from"], window["to"])
    bqm_rows = _get_bqm_rows(core.db_path, window["from"], window["to"])
    config_manager = get_config_manager()
    capabilities = _capabilities(config_manager)
    items = build_checklist(
        window,
        timeline=timeline,
        journal_entries=journal_entries,
        bqm_rows=bqm_rows,
        capabilities=capabilities,
    )
    return jsonify({
        "window": window,
        "capabilities": capabilities,
        "summary": summarize_checklist(items),
        "items": items,
    })
