"""Modulation performance API routes (v2)."""

import logging

from flask import Blueprint, request, jsonify

from app.web import require_auth, get_storage, get_config_manager

log = logging.getLogger("docsis.web")

bp = Blueprint("modulation_bp", __name__)


def _get_tz():
    """Get the configured timezone name."""
    cm = get_config_manager()
    if cm:
        return cm.get("timezone", "")
    return ""


@bp.route("/api/modulation/distribution")
@require_auth
def api_modulation_distribution():
    """Return per-protocol-group distribution, health index, and trend per day."""
    from .engine import compute_distribution_v2
    from app.tz import utc_now, utc_cutoff

    storage = get_storage()
    if not storage:
        return jsonify({"error": "No storage available"}), 503

    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 30))
    direction = request.args.get("direction", "us")
    if direction not in ("us", "ds"):
        direction = "us"

    end_ts = utc_now()
    start_ts = utc_cutoff(days=days)

    snapshots = storage.get_range_data(start_ts, end_ts)
    tz_name = _get_tz()

    result = compute_distribution_v2(snapshots, direction, tz_name)
    return jsonify(result)


@bp.route("/api/modulation/intraday")
@require_auth
def api_modulation_intraday():
    """Return per-channel modulation timeline for a single day."""
    from .engine import compute_intraday
    from app.tz import utc_now, utc_cutoff, to_local

    storage = get_storage()
    if not storage:
        return jsonify({"error": "No storage available"}), 503

    direction = request.args.get("direction", "us")
    if direction not in ("us", "ds"):
        direction = "us"

    tz_name = _get_tz()

    # Date parameter: defaults to today in local timezone
    date_str = request.args.get("date", "")
    if not date_str:
        now_local = to_local(utc_now(), tz_name) if tz_name else utc_now().rstrip("Z")
        date_str = now_local[:10]

    # Fetch data covering the requested date (± 1 day for timezone edge cases)
    from datetime import datetime, timedelta
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        target = datetime.utcnow()
    start_ts = (target - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    end_ts = (target + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")

    snapshots = storage.get_range_data(start_ts, end_ts)

    result = compute_intraday(snapshots, direction, tz_name, date_str)
    return jsonify(result)


# Legacy trend endpoint kept for backwards compatibility
@bp.route("/api/modulation/trend")
@require_auth
def api_modulation_trend():
    """Return per-day trend data (health index + low-QAM %) for the trend chart."""
    from .engine import compute_trend
    from app.tz import utc_now, utc_cutoff

    storage = get_storage()
    if not storage:
        return jsonify({"error": "No storage available"}), 503

    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 30))
    direction = request.args.get("direction", "us")
    if direction not in ("us", "ds"):
        direction = "us"

    end_ts = utc_now()
    start_ts = utc_cutoff(days=days)

    snapshots = storage.get_range_data(start_ts, end_ts)
    tz_name = _get_tz()

    result = compute_trend(snapshots, direction, tz_name)
    return jsonify(result)
