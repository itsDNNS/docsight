"""Segment utilization API routes."""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from app.i18n import get_translations
from app.storage.segment_utilization import SegmentUtilizationStorage
from app.web import get_config_manager, get_storage, require_auth

log = logging.getLogger("docsis.web.segment")

segment_bp = Blueprint("segment_bp", __name__)

_storage_instance = None


def _get_lang():
    return request.cookies.get("lang", "en")


def _get_storage():
    """Lazy-init segment storage using core DB path."""
    global _storage_instance
    if _storage_instance is None:
        storage = get_storage()
        if storage:
            _storage_instance = SegmentUtilizationStorage(storage.db_path)
    return _storage_instance


RANGE_HOURS = {"24h": 24, "7d": 168, "30d": 720, "all": 0}


def _normalize_range_key(raw, default):
    """Return ``raw`` if it's a recognized range key, otherwise ``default``."""
    if raw in RANGE_HOURS:
        return raw
    return default


@segment_bp.route("/api/fritzbox/segment-utilization")
@require_auth
def api_segment_utilization():
    """Return stored segment utilization data for the tab view."""
    config = get_config_manager()
    t = get_translations(_get_lang())
    if not config:
        return jsonify({"error": t.get("seg_unavailable", "Configuration unavailable.")}), 503
    if config.get("modem_type") != "fritzbox":
        return jsonify({"error": t.get("seg_unsupported_driver", "This view is only available for FRITZ!Box cable devices.")}), 400
    if not config.is_segment_utilization_enabled():
        return jsonify({"error": t.get("seg_disabled", "Segment utilization is disabled in Settings.")}), 400

    storage = _get_storage()
    if not storage:
        return jsonify({"error": "Storage unavailable"}), 503

    range_key = _normalize_range_key(request.args.get("range"), "24h")
    hours = RANGE_HOURS[range_key]

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


def _clamp_int(value, default, lo, hi):
    """Parse an int-ish query param and clamp it to [lo, hi]. Falls back
    to ``default`` on parse errors or None."""
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < lo:
        return lo
    if parsed > hi:
        return hi
    return parsed


@segment_bp.route("/api/fritzbox/segment-utilization/events")
@require_auth
def api_segment_utilization_events():
    """Return detected segment saturation events for the requested range."""
    config = get_config_manager()
    t = get_translations(_get_lang())
    if not config:
        return jsonify({"error": t.get("seg_unavailable", "Configuration unavailable.")}), 503
    if config.get("modem_type") != "fritzbox":
        return jsonify({"error": t.get("seg_unsupported_driver", "This view is only available for FRITZ!Box cable devices.")}), 400
    if not config.is_segment_utilization_enabled():
        return jsonify({"error": t.get("seg_disabled", "Segment utilization is disabled in Settings.")}), 400

    storage = _get_storage()
    if not storage:
        return jsonify({"error": "Storage unavailable"}), 503

    threshold = _clamp_int(request.args.get("threshold"), default=80, lo=1, hi=100)
    min_minutes = _clamp_int(request.args.get("min_minutes"), default=3, lo=1, hi=1440)

    range_key = _normalize_range_key(request.args.get("range"), "7d")
    hours = RANGE_HOURS[range_key]
    if hours > 0:
        start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        start = "2000-01-01T00:00:00Z"
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    events = storage.get_events(start, end, threshold=threshold, min_minutes=min_minutes)
    return jsonify({
        "events": events,
        "threshold": threshold,
        "min_minutes": min_minutes,
        "range": range_key,
    })


@segment_bp.route("/api/fritzbox/segment-utilization/range")
@require_auth
def api_segment_utilization_range():
    """Return segment data for a time range (used by correlation graph).

    Returns an empty list — rather than an error — when configuration is
    unavailable, the driver is unsupported, or the feature is disabled.
    This matches ``/api/weather/range`` so the correlation view degrades
    gracefully when optional data sources are absent.
    """
    config = get_config_manager()
    if not config or config.get("modem_type") != "fritzbox" or not config.is_segment_utilization_enabled():
        return jsonify([])
    storage = _get_storage()
    if not storage:
        return jsonify([])
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    if not start or not end:
        return jsonify({"error": "start and end parameters required"}), 400
    return jsonify(storage.get_range(start, end))
