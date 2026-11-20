"""Segment utilization API routes."""

import logging

from flask import Blueprint, jsonify, request

from app.i18n import get_translations
from app.storage.segment_utilization import SegmentUtilizationStorage
from app.web_auth import require_auth
from app.runtime import core_derived_storage, current_runtime
from app.tz import utc_cutoff, utc_now

log = logging.getLogger("docsis.web.segment")

segment_bp = Blueprint("segment_bp", __name__)

def _get_lang():
    return request.cookies.get("lang", "en")


def _get_storage():
    """Lazy-init segment storage using core DB path."""
    return core_derived_storage(SegmentUtilizationStorage)


RANGE_HOURS = {"24h": 24, "7d": 168, "30d": 720, "all": 0}


def _normalize_range_key(raw, default):
    """Return ``raw`` if it's a recognized range key, otherwise ``default``."""
    if raw in RANGE_HOURS:
        return raw
    return default


def _window(range_key):
    """The (start, end) UTC timestamps of a range key."""
    hours = RANGE_HOURS[range_key]
    return (utc_cutoff(hours=hours) if hours > 0 else "2000-01-01T00:00:00Z"), utc_now()


def _gated_storage():
    """(storage, None) for the segment views, or (None, error response) while they are unavailable."""
    config = current_runtime().config_manager
    t = get_translations(_get_lang())
    if not config:
        return None, (jsonify({"error": t.get("seg_unavailable", "Configuration unavailable.")}), 503)
    if config.get("modem_type") != "fritzbox":
        return None, (jsonify({"error": t.get("seg_unsupported_driver", "This view is only available for FRITZ!Box cable devices.")}), 400)
    if not config.is_segment_utilization_enabled():
        return None, (jsonify({"error": t.get("seg_disabled", "Segment utilization is disabled in Settings.")}), 400)
    storage = _get_storage()
    if not storage:
        return None, (jsonify({"error": "Storage unavailable"}), 503)
    return storage, None


@segment_bp.route("/api/fritzbox/segment-utilization")
@require_auth
def api_segment_utilization():
    """Return stored segment utilization data for the tab view."""
    storage, error = _gated_storage()
    if error:
        return error
    start, end = _window(_normalize_range_key(request.args.get("range"), "24h"))
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
    storage, error = _gated_storage()
    if error:
        return error
    threshold = _clamp_int(request.args.get("threshold"), default=80, lo=1, hi=100)
    min_minutes = _clamp_int(request.args.get("min_minutes"), default=3, lo=1, hi=1440)
    range_key = _normalize_range_key(request.args.get("range"), "7d")
    start, end = _window(range_key)
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
    config = current_runtime().config_manager
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
