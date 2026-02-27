"""Event log routes."""

import logging

from flask import Blueprint, request, jsonify

from app.web import (
    require_auth,
    get_storage,
    _localize_timestamps,
)

log = logging.getLogger("docsis.web")

events_bp = Blueprint("events_bp", __name__)


@events_bp.route("/api/events", methods=["GET"])
@require_auth
def api_events_list():
    """Return list of events with optional filters."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"events": [], "unacknowledged_count": 0})
    limit = request.args.get("limit", 200, type=int)
    offset = request.args.get("offset", 0, type=int)
    severity = request.args.get("severity") or None
    event_type = request.args.get("event_type") or None
    ack_param = request.args.get("acknowledged")
    acknowledged = int(ack_param) if ack_param is not None and ack_param != "" else None
    events = _storage.get_events(
        limit=limit, offset=offset, severity=severity,
        event_type=event_type, acknowledged=acknowledged,
    )
    unack = _storage.get_event_count(acknowledged=0)
    _localize_timestamps(events)
    return jsonify({"events": events, "unacknowledged_count": unack})


@events_bp.route("/api/events/count", methods=["GET"])
@require_auth
def api_events_count():
    """Return unacknowledged event count (for badge)."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"count": 0})
    return jsonify({"count": _storage.get_event_count(acknowledged=0)})


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
