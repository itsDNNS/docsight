"""Modulation performance API routes (v2)."""

from app.runtime import current_runtime
import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify

from app.tz import get_tz_name, local_today, utc_now, utc_cutoff
from app.web_auth import require_auth

from .engine import (
    compute_capacity_history,
    compute_distribution_v2,
    compute_intraday,
    compute_trend,
)

log = logging.getLogger("docsis.web")

bp = Blueprint("modulation_bp", __name__)


def _get_tz():
    """Get the configured timezone name, falling back to the system zone."""
    return get_tz_name(current_runtime().config_manager)


def _direction():
    direction = request.args.get("direction", "us")
    return direction if direction in ("us", "ds") else "us"


def _range_snapshots(storage):
    """Return the snapshots of the last ?days= days (1-30, default 7)."""
    days = max(1, min(request.args.get("days", 7, type=int), 30))
    return storage.get_range_data(utc_cutoff(days=days), utc_now())


@bp.route("/api/modulation/distribution")
@require_auth
def api_modulation_distribution():
    """Return per-protocol-group distribution, health index, and trend per day."""
    storage = current_runtime().storage
    if not storage:
        return jsonify({"error": "No storage available"}), 503

    snapshots = _range_snapshots(storage)
    tz_name = _get_tz()
    result = compute_distribution_v2(snapshots, _direction(), tz_name)
    result["capacity_history"] = compute_capacity_history(
        snapshots,
        tz_name,
    )
    return jsonify(result)


@bp.route("/api/modulation/intraday")
@require_auth
def api_modulation_intraday():
    """Return per-channel modulation timeline for a single day."""
    storage = current_runtime().storage
    if not storage:
        return jsonify({"error": "No storage available"}), 503

    tz_name = _get_tz()
    date_str = request.args.get("date", "") or local_today(tz_name)

    # Fetch data covering the requested date (± 1 day for timezone edge cases)
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        target = datetime.now(timezone.utc)
    start_ts = (target - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    end_ts = (target + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")

    snapshots = storage.get_range_data(start_ts, end_ts)

    result = compute_intraday(snapshots, _direction(), tz_name, date_str)
    result["capacity_history"] = compute_capacity_history(
        snapshots,
        tz_name,
        target_date=date_str,
    )
    return jsonify(result)


# Legacy trend endpoint kept for backwards compatibility
@bp.route("/api/modulation/trend")
@require_auth
def api_modulation_trend():
    """Return per-day trend data (health index + low-QAM %) for the trend chart."""
    storage = current_runtime().storage
    if not storage:
        return jsonify({"error": "No storage available"}), 503

    return jsonify(compute_trend(_range_snapshots(storage), _direction(), _get_tz()))
