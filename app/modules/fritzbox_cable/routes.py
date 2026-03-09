"""FRITZ!Box cable segment utilization routes."""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from app.i18n import get_translations
from app.web import get_config_manager, get_storage, require_auth

log = logging.getLogger("docsis.web.fritzbox_cable")

bp = Blueprint("fritzbox_cable_module", __name__)

_storage_instance = None


def _get_lang():
    return request.cookies.get("lang", "en")


def _get_storage():
    """Lazy-init module storage using core DB path."""
    global _storage_instance
    if _storage_instance is None:
        storage = get_storage()
        if storage:
            from app.modules.fritzbox_cable.storage import SegmentUtilizationStorage
            _storage_instance = SegmentUtilizationStorage(storage.db_path)
    return _storage_instance


RANGE_HOURS = {"24h": 24, "7d": 168, "30d": 720, "all": 0}


@bp.route("/api/fritzbox/segment-utilization")
@require_auth
def api_segment_utilization():
    """Return stored segment utilization data for the tab view."""
    config = get_config_manager()
    t = get_translations(_get_lang())
    if not config:
        return jsonify({"error": t.get("docsight.fritzbox_cable.unavailable", "Configuration unavailable.")}), 503
    if config.get("modem_type") != "fritzbox":
        return jsonify({"error": t.get("docsight.fritzbox_cable.unsupported_driver", "This view is only available for FRITZ!Box cable devices.")}), 400

    storage = _get_storage()
    if not storage:
        return jsonify({"error": "Storage unavailable"}), 503

    range_key = request.args.get("range", "24h")
    hours = RANGE_HOURS.get(range_key, 24)

    if hours > 0:
        start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        start = "2000-01-01T00:00:00Z"
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return jsonify({
        "samples": storage.get_range(start, end),
        "latest": storage.get_latest(1),
        "stats": storage.get_stats(start, end),
    })


@bp.route("/api/fritzbox/segment-utilization/range")
@require_auth
def api_segment_utilization_range():
    """Return segment data for a time range (used by correlation graph)."""
    storage = _get_storage()
    if not storage:
        return jsonify([])
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    if not start or not end:
        return jsonify({"error": "start and end parameters required"}), 400
    return jsonify(storage.get_range(start, end))
