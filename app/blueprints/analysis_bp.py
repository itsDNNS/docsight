"""Analysis routes: connection, channels, device, thresholds, gaming, channel history, correlation."""

import logging
from datetime import datetime

from flask import Blueprint, request, jsonify

from app.web import (
    require_auth,
    get_storage, get_config_manager, get_state,
    _localize_timestamps, _get_lang, _get_tz_name,
)
from app.gaming_index import compute_gaming_index
from app.i18n import get_translations

log = logging.getLogger("docsis.web")

analysis_bp = Blueprint("analysis_bp", __name__)


def _gaming_genres(grade):
    """Return genre suitability verdicts for a given grade.

    Verdicts: 'ok', 'warn', or 'bad'.
    """
    g = (grade or "").lower()
    return {
        "fps":      "ok"   if g in ("a", "b")           else "bad",
        "moba":     "ok"   if g in ("a", "b", "c")      else "bad",
        "mmo":      "ok"   if g in ("a", "b", "c", "d") else "bad",
        "strategy": "ok"   if g in ("a", "b", "c")      else ("warn" if g == "d" else "bad"),
    }


@analysis_bp.route("/api/connection")
@require_auth
def api_connection():
    """Return connection details: ISP name, connection type, and detected speeds.

    isp_name comes from user config. The remaining fields are populated
    by the modem driver and may be absent if the modem has not been polled yet.
    """
    _config_manager = get_config_manager()
    isp_name = _config_manager.get("isp_name", "") if _config_manager else ""
    conn_info = get_state().get("connection_info") or {}
    return jsonify({
        "isp_name": isp_name or None,
        "connection_type": conn_info.get("connection_type"),
        "max_downstream_kbps": conn_info.get("max_downstream_kbps"),
        "max_upstream_kbps": conn_info.get("max_upstream_kbps"),
    })


@analysis_bp.route("/api/channels")
@require_auth
def api_channels():
    """Return current DS and US channels with overall health summary."""
    _storage = get_storage()
    state = get_state()
    analysis = state.get("analysis")
    summary = analysis["summary"] if analysis else None
    if not _storage:
        return jsonify({"ds_channels": [], "us_channels": [], "summary": summary})
    result = _storage.get_current_channels()
    result["summary"] = summary
    return jsonify(result)


@analysis_bp.route("/api/device")
@require_auth
def api_device():
    """Return modem device information."""
    state = get_state()
    return jsonify(state.get("device_info") or {})


@analysis_bp.route("/api/thresholds")
@require_auth
def api_thresholds():
    """Return active analysis thresholds (read-only)."""
    from app.analyzer import get_thresholds
    return jsonify(get_thresholds())


@analysis_bp.route("/api/gaming-score")
@require_auth
def api_gaming_score():
    """Return the current Gaming Quality Index score and its components.

    Response includes:
      enabled      - whether Gaming Quality is enabled in settings
      score        - 0-100 numeric score (null if no data)
      grade        - letter grade A-F (null if no data)
      has_speedtest - whether speedtest data was included in the calculation
      components   - per-component scores and weights used for calculation
      genres       - suitability verdict (ok/warn/bad) per game genre
      raw          - raw measured values that fed into the calculation
    """
    _config_manager = get_config_manager()
    enabled = _config_manager.is_gaming_quality_enabled() if _config_manager else False
    state = get_state()
    analysis = state.get("analysis")
    speedtest_latest = state.get("speedtest_latest")
    result = compute_gaming_index(analysis, speedtest_latest)
    if result is None:
        return jsonify({
            "enabled": enabled,
            "score": None,
            "grade": None,
            "has_speedtest": False,
            "components": {},
            "genres": _gaming_genres(None),
            "raw": {},
        })
    summary = (analysis or {}).get("summary", {})
    raw = {
        "docsis_health": summary.get("health"),
        "ds_snr_min": summary.get("ds_snr_min"),
    }
    if result.get("has_speedtest") and speedtest_latest:
        raw["ping_ms"] = speedtest_latest.get("ping_ms")
        raw["jitter_ms"] = speedtest_latest.get("jitter_ms")
        raw["packet_loss_pct"] = speedtest_latest.get("packet_loss_pct")
    return jsonify({
        "enabled": enabled,
        **result,
        "genres": _gaming_genres(result.get("grade")),
        "raw": raw,
    })


@analysis_bp.route("/api/channel-history")
@require_auth
def api_channel_history():
    """Return per-channel time series data.
    ?channel_id=X&direction=ds|us&days=7"""
    _storage = get_storage()
    if not _storage:
        return jsonify([])
    channel_id = request.args.get("channel_id", type=int)
    direction = request.args.get("direction", "ds")
    days = request.args.get("days", 7, type=int)
    if channel_id is None:
        return jsonify({"error": "channel_id is required"}), 400
    if direction not in ("ds", "us"):
        return jsonify({"error": "direction must be 'ds' or 'us'"}), 400
    days = max(1, min(days, 90))
    data = _storage.get_channel_history(channel_id, direction, days)
    _localize_timestamps(data)
    return jsonify(data)


@analysis_bp.route("/api/channel-compare")
@require_auth
def api_channel_compare():
    """Return per-channel time series for multiple channels.
    ?channels=1,2,3&direction=ds|us&days=7"""
    _storage = get_storage()
    if not _storage:
        return jsonify({})
    channels_param = request.args.get("channels", "")
    direction = request.args.get("direction", "ds")
    days = request.args.get("days", 7, type=int)
    if not channels_param:
        return jsonify({"error": "channels parameter is required"}), 400
    if direction not in ("ds", "us"):
        return jsonify({"error": "direction must be 'ds' or 'us'"}), 400
    days = max(1, min(days, 90))
    try:
        channel_ids = [int(c.strip()) for c in channels_param.split(",") if c.strip()]
    except ValueError:
        return jsonify({"error": "channels must be comma-separated integers"}), 400
    if len(channel_ids) > 6:
        return jsonify({"error": "maximum 6 channels"}), 400
    if not channel_ids:
        return jsonify({"error": "at least one channel required"}), 400
    result = _storage.get_multi_channel_history(channel_ids, direction, days)
    # Convert int keys to strings for JSON
    return jsonify({str(k): v for k, v in result.items()})


# ── Cross-Source Correlation API ──

@analysis_bp.route("/api/correlation")
@require_auth
def api_correlation():
    """Return unified timeline with data from all sources for cross-source correlation.
    Query params:
      hours: int (default 24, max 168)
      sources: comma-separated list of modem,speedtest,events (default all)
    """
    _storage = get_storage()
    if not _storage:
        return jsonify([])
    from app.tz import utc_now, utc_cutoff
    hours = request.args.get("hours", 24, type=int)
    hours = max(1, min(hours, 168))
    end_ts = utc_now()
    start_ts = utc_cutoff(hours=hours)

    sources_param = request.args.get("sources", "")
    if sources_param:
        valid = {"modem", "speedtest", "events", "bnetz"}
        sources = valid & set(s.strip() for s in sources_param.split(","))
        if not sources:
            sources = valid
    else:
        sources = None

    timeline = _storage.get_correlation_timeline(start_ts, end_ts, sources)

    # Enrich speedtest entries with closest modem health
    modem_entries = [e for e in timeline if e["source"] == "modem"]
    for entry in timeline:
        if entry["source"] == "speedtest" and modem_entries:
            closest = min(modem_entries, key=lambda m: abs(
                datetime.fromisoformat(m["timestamp"]).timestamp() -
                datetime.fromisoformat(entry["timestamp"]).timestamp()
            ))
            delta_min = abs(
                datetime.fromisoformat(closest["timestamp"]).timestamp() -
                datetime.fromisoformat(entry["timestamp"]).timestamp()
            ) / 60
            if delta_min <= 120:
                entry["modem_health"] = closest.get("health")
                entry["modem_ds_snr_min"] = closest.get("ds_snr_min")
                entry["modem_ds_power_avg"] = closest.get("ds_power_avg")

    _localize_timestamps(timeline)
    return jsonify(timeline)
