"""Event log routes."""

import csv
import io
import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, Response

from app.web import (
    require_auth,
    get_storage,
    _localize_timestamps,
)

log = logging.getLogger("docsis.web")

_EVENTS_EXPORT_LIMIT = 10000
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


events_bp = Blueprint("events_bp", __name__)


def _acknowledged_from_request():
    ack_param = request.args.get("acknowledged")
    if ack_param is None or ack_param == "":
        return None
    try:
        acknowledged = int(ack_param)
    except ValueError as exc:
        raise ValueError("acknowledged must be 0 or 1") from exc
    if acknowledged not in (0, 1):
        raise ValueError("acknowledged must be 0 or 1")
    return acknowledged


def _event_filters_from_request():
    return {
        "severity": request.args.get("severity") or None,
        "event_type": request.args.get("event_type") or None,
        "event_prefix": request.args.get("event_prefix") or None,
        "acknowledged": _acknowledged_from_request(),
        "exclude_operational": request.args.get("exclude_operational", "false").lower() == "true",
    }


def _csv_cell(value):
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def _events_csv_response(events, truncated=False):
    output = io.StringIO(newline="")
    fieldnames = ["timestamp", "severity", "event_type", "message", "acknowledged", "details"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for event in events:
        details = event.get("details")
        details_text = json.dumps(details, ensure_ascii=False, sort_keys=True) if details else ""
        writer.writerow({
            "timestamp": _csv_cell(event.get("timestamp", "")),
            "severity": _csv_cell(event.get("severity", "")),
            "event_type": _csv_cell(event.get("event_type", "")),
            "message": _csv_cell(event.get("message", "")),
            "acknowledged": "true" if event.get("acknowledged") else "false",
            "details": _csv_cell(details_text),
        })
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=docsight-events-{stamp}.csv",
            "X-DOCSight-Export-Limit": str(_EVENTS_EXPORT_LIMIT),
            "X-DOCSight-Export-Truncated": "true" if truncated else "false",
        },
    )


@events_bp.route("/api/events", methods=["GET"])
@require_auth
def api_events_list():
    """Return list of events with optional filters."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"events": [], "unacknowledged_count": 0})
    limit = request.args.get("limit", 200, type=int)
    offset = request.args.get("offset", 0, type=int)
    try:
        filters = _event_filters_from_request()
    except ValueError:
        return jsonify({"error": "Invalid acknowledged filter"}), 400

    events = _storage.get_events(
        limit=limit, offset=offset, severity=filters["severity"],
        event_type=filters["event_type"], acknowledged=filters["acknowledged"],
        exclude_operational=filters["exclude_operational"], event_prefix=filters["event_prefix"]
    )
    unack = _storage.get_event_count(
        acknowledged=0,
        exclude_operational=filters["exclude_operational"],
        event_prefix=filters["event_prefix"],
        severity=filters["severity"]
    )
    _localize_timestamps(events)
    return jsonify({"events": events, "unacknowledged_count": unack})


@events_bp.route("/api/events/export.csv", methods=["GET"])
@require_auth
def api_events_export_csv():
    """Export all events matching the current event-log filters as CSV."""
    _storage = get_storage()
    if not _storage:
        return _events_csv_response([])
    try:
        filters = _event_filters_from_request()
    except ValueError:
        return jsonify({"error": "Invalid acknowledged filter"}), 400
    events = _storage.get_events(
        limit=_EVENTS_EXPORT_LIMIT + 1,
        offset=0,
        severity=filters["severity"],
        event_type=filters["event_type"],
        acknowledged=filters["acknowledged"],
        exclude_operational=filters["exclude_operational"],
        event_prefix=filters["event_prefix"],
    )
    truncated = len(events) > _EVENTS_EXPORT_LIMIT
    return _events_csv_response(events[:_EVENTS_EXPORT_LIMIT], truncated=truncated)


@events_bp.route("/api/events/count", methods=["GET"])
@require_auth
def api_events_count():
    """Return unacknowledged event count (for badge)."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"count": 0})
    event_prefix = request.args.get("event_prefix") or None
    severity = request.args.get("severity") or None
    exclude_operational = request.args.get("exclude_operational", "false").lower() == "true"
    count = _storage.get_event_count(
        acknowledged=0,
        exclude_operational=exclude_operational,
        event_prefix=event_prefix,
        severity=severity
    )
    return jsonify({"count": count})


@events_bp.route("/api/events/<int:event_id>/acknowledge", methods=["POST"])
@require_auth
def api_event_acknowledge(event_id):
    """Acknowledge a single event."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.acknowledge_event(event_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


@events_bp.route("/api/events/acknowledge-all", methods=["POST"])
@require_auth
def api_events_acknowledge_all():
    """Acknowledge all unacknowledged events."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    count = _storage.acknowledge_all_events()
    return jsonify({"success": True, "count": count})
