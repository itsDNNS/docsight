"""Speedtest module routes."""

import logging
import time

import requests
from flask import Blueprint, request, jsonify

from app.web import require_auth, get_config_manager, get_state, get_storage, clear_speedtest_latest
from app.i18n import get_translations

from .client import SpeedtestClient
from .storage import SpeedtestStorage

log = logging.getLogger("docsis.web.speedtest")

bp = Blueprint("speedtest_module", __name__)

# Lazy-initialized module-local storage
_storage = None

# Rate-limit: track last manual trigger timestamp
_last_trigger_ts = 0
_TRIGGER_COOLDOWN = 60  # seconds


def _get_speedtest_storage():
    global _storage
    if _storage is None:
        core_storage = get_storage()
        if core_storage:
            _storage = SpeedtestStorage(core_storage.db_path)
    return _storage


def _classify_speed(actual, booked):
    """Classify speed as good/warn/poor based on ratio to booked speed."""
    if not booked or booked <= 0:
        return None
    ratio = actual / booked
    if ratio >= 0.8:
        return "good"
    elif ratio >= 0.5:
        return "warn"
    return "poor"


def _enrich_speedtest(result):
    """Add speed_health, download_class, upload_class to a speedtest result."""
    _config_manager = get_config_manager()
    booked_dl = _config_manager.get("booked_download", 0) if _config_manager else 0
    booked_ul = _config_manager.get("booked_upload", 0) if _config_manager else 0
    if not booked_dl or not booked_ul:
        conn_info = get_state().get("connection_info") or {}
        if not booked_dl:
            booked_dl = conn_info.get("max_downstream_kbps", 0) // 1000 if conn_info.get("max_downstream_kbps") else 0
        if not booked_ul:
            booked_ul = conn_info.get("max_upstream_kbps", 0) // 1000 if conn_info.get("max_upstream_kbps") else 0
    dl_class = _classify_speed(result.get("download_mbps", 0), booked_dl)
    ul_class = _classify_speed(result.get("upload_mbps", 0), booked_ul)
    # speed_health is the worse of the two
    if dl_class and ul_class:
        order = {"poor": 0, "warn": 1, "good": 2}
        speed_health = dl_class if order.get(dl_class, 2) <= order.get(ul_class, 2) else ul_class
    else:
        speed_health = dl_class or ul_class
    result["download_class"] = dl_class
    result["upload_class"] = ul_class
    result["speed_health"] = speed_health
    return result


def _annotate_smart_capture(results, db_path):
    """Annotate speedtest results with smart_capture flag."""
    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT linked_result_id FROM smart_capture_executions "
                "WHERE status = 'completed' AND linked_result_id IS NOT NULL"
            ).fetchall()
            sc_ids = {r[0] for r in rows}
        for r in results:
            r["smart_capture"] = r.get("id") in sc_ids
    except Exception:
        for r in results:
            r["smart_capture"] = False


def _get_lang():
    return request.cookies.get("lang", "en")


@bp.route("/api/speedtest")
@require_auth
def api_speedtest():
    """Return speedtest results from local cache, with delta fetch from STT."""
    _config_manager = get_config_manager()
    ss = _get_speedtest_storage()
    if not _config_manager or not _config_manager.is_speedtest_configured():
        return jsonify([])
    count = request.args.get("count", 2000, type=int)
    count = max(1, min(count, 5000))
    # Demo mode: return seeded data without external API call
    if _config_manager.is_demo_mode() and ss:
        results = ss.get_speedtest_results(limit=count)
        enriched = [_enrich_speedtest(r) for r in results]
        _annotate_smart_capture(enriched, ss.db_path)
        return jsonify(enriched)
    # Delta fetch: get new results from STT API and cache them
    if ss:
        try:
            stt_url = _config_manager.get("speedtest_tracker_url")
            client = SpeedtestClient(
                stt_url,
                _config_manager.get("speedtest_tracker_token"),
            )
            # Detect server switch and clear stale cache
            ss.check_source_url(stt_url)
            cached_count = ss.get_speedtest_count()
            last_id = ss.get_latest_speedtest_id()
            # ID-reset detection: compare remote max ID with cache max ID
            if cached_count > 0 and last_id > 0:
                remote_latest, fetch_err = client.get_latest_with_error(1)
                if fetch_err is None and not remote_latest:
                    # Remote is reachable but empty — server was wiped
                    log.info("Remote has no results but cache has %d, clearing", cached_count)
                    ss.clear_cache()
                    clear_speedtest_latest()
                    cached_count = 0
                elif remote_latest and remote_latest[0].get("id", 0) < last_id:
                    log.info(
                        "Speedtest ID reset detected (cache max=%d, remote max=%d), rebuilding",
                        last_id, remote_latest[0]["id"],
                    )
                    ss.clear_cache()
                    cached_count = 0
            if cached_count < 50:
                new_results = client.get_results(per_page=2000)
            else:
                new_results = client.get_newer_than(last_id)
            if new_results:
                ss.save_speedtest_results(new_results)
                log.info("Cached %d new speedtest results", len(new_results))
        except Exception as e:
            log.warning("Speedtest delta fetch failed: %s", e)
        results = ss.get_speedtest_results(limit=count)
        enriched = [_enrich_speedtest(r) for r in results]
        _annotate_smart_capture(enriched, ss.db_path)
        return jsonify(enriched)
    # Fallback: no storage, fetch directly
    client = SpeedtestClient(
        _config_manager.get("speedtest_tracker_url"),
        _config_manager.get("speedtest_tracker_token"),
    )
    results = client.get_results(per_page=count)
    return jsonify([_enrich_speedtest(r) for r in results])


@bp.route("/api/speedtest/<int:result_id>")
@require_auth
def api_speedtest_detail(result_id):
    """Return full speedtest result by ID."""
    ss = _get_speedtest_storage()
    if not ss:
        return jsonify({"error": "Storage not initialized"}), 500
    result = ss.get_speedtest_by_id(result_id)
    if not result:
        return jsonify({"error": "Speedtest result not found"}), 404
    return jsonify(_enrich_speedtest(result))


@bp.route("/api/speedtest/<int:result_id>/signal")
@require_auth
def api_speedtest_signal(result_id):
    """Return the closest DOCSIS snapshot signal data for a speedtest result."""
    ss = _get_speedtest_storage()
    core_storage = get_storage()
    if not ss:
        return jsonify({"error": "Storage not initialized"}), 500
    result = ss.get_speedtest_by_id(result_id)
    if not result:
        return jsonify({"error": "Speedtest result not found"}), 404
    if not core_storage:
        return jsonify({"error": "Core storage not initialized"}), 500
    snap = core_storage.get_closest_snapshot(result["timestamp"])
    if not snap:
        lang = _get_lang()
        t = get_translations(lang)
        return jsonify({
            "found": False,
            "message": t.get("signal_no_snapshot", "No signal snapshot found within 2 hours of this speedtest."),
        })
    s = snap["summary"]
    us_channels = []
    for ch in snap.get("us_channels", []):
        us_channels.append({
            "channel_id": ch.get("channel_id"),
            "modulation": ch.get("modulation", ""),
            "power": ch.get("power"),
        })
    return jsonify({
        "found": True,
        "snapshot_timestamp": snap["timestamp"],
        "health": s.get("health", "unknown"),
        "ds_power_avg": s.get("ds_power_avg"),
        "ds_power_min": s.get("ds_power_min"),
        "ds_power_max": s.get("ds_power_max"),
        "ds_snr_min": s.get("ds_snr_min"),
        "ds_snr_avg": s.get("ds_snr_avg"),
        "us_power_avg": s.get("us_power_avg"),
        "us_power_min": s.get("us_power_min"),
        "us_power_max": s.get("us_power_max"),
        "ds_uncorrectable_errors": s.get("ds_uncorrectable_errors", 0),
        "ds_correctable_errors": s.get("ds_correctable_errors", 0),
        "ds_total": s.get("ds_total", 0),
        "us_total": s.get("us_total", 0),
        "us_channels": us_channels,
    })


@bp.route("/api/speedtest/run", methods=["POST"])
@require_auth
def api_speedtest_run():
    """Trigger a speedtest run via the Speedtest Tracker API."""
    global _last_trigger_ts
    _config_manager = get_config_manager()
    if not _config_manager or not _config_manager.is_speedtest_configured():
        return jsonify({"success": False, "error": "Speedtest Tracker not configured"}), 400

    if _config_manager.is_demo_mode():
        return jsonify({"success": False, "error": "Not available in demo mode"}), 400

    now = time.time()
    if now - _last_trigger_ts < _TRIGGER_COOLDOWN:
        remaining = int(_TRIGGER_COOLDOWN - (now - _last_trigger_ts))
        return jsonify({"success": False, "error": f"Rate limited, retry in {remaining}s"}), 429

    url = _config_manager.get("speedtest_tracker_url", "").rstrip("/")
    token = _config_manager.get("speedtest_tracker_token", "")
    try:
        resp = requests.post(
            f"{url}/api/v1/speedtests/run",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=90,
        )
        if resp.status_code == 201:
            _last_trigger_ts = now
            log.info("Speedtest manually triggered via UI")
            return jsonify({"success": True})
        else:
            error = f"Speedtest Tracker returned {resp.status_code}"
            log.warning("Manual speedtest trigger failed: %s", error)
            return jsonify({"success": False, "error": error}), 502
    except requests.ConnectionError:
        return jsonify({"success": False, "error": "Cannot reach Speedtest Tracker"}), 502
    except requests.Timeout:
        return jsonify({"success": False, "error": "Speedtest Tracker timeout"}), 504
    except Exception as e:
        log.warning("Manual speedtest trigger error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/speedtest/cache", methods=["DELETE"])
@require_auth
def api_speedtest_clear_cache():
    """Clear the local speedtest results cache."""
    ss = _get_speedtest_storage()
    if not ss:
        return jsonify({"success": False, "error": "Storage not initialized"}), 500
    count = ss.clear_cache()
    clear_speedtest_latest()
    log.info("Speedtest cache cleared via API (%d results removed)", count)
    return jsonify({"success": True, "cleared": count})
