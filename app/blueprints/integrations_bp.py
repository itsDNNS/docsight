"""Integration routes: BQM, Smokeping, Weather, Speedtest, BNetzA."""

import logging
from io import BytesIO

import requests as _requests

from flask import Blueprint, request, jsonify, make_response, send_file

from app.web import (
    require_auth,
    get_storage, get_config_manager, get_state,
    _valid_date, _get_client_ip, _get_lang, _get_tz_name,
)
from app.storage import MAX_ATTACHMENT_SIZE
from app.i18n import get_translations

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web")

integrations_bp = Blueprint("integrations_bp", __name__)


SMOKEPING_TIMESPANS = {
    "3h": "last_10800",
    "30h": "last_108000",
    "10d": "last_864000",
    "1y": "last_31104000",
}


# ── Smokeping ──

@integrations_bp.route("/api/smokeping/targets")
@require_auth
def api_smokeping_targets():
    """Return list of configured Smokeping targets."""
    _config_manager = get_config_manager()
    if not _config_manager or not _config_manager.is_smokeping_configured():
        return jsonify([])
    raw = _config_manager.get("smokeping_targets", "")
    targets = [t.strip() for t in raw.split(",") if t.strip()]
    return jsonify(targets)


@integrations_bp.route("/api/smokeping/graph/<path:target>/<timespan>")
@require_auth
def api_smokeping_graph(target, timespan):
    """Proxy a Smokeping graph PNG."""
    _config_manager = get_config_manager()
    if not _config_manager or not _config_manager.is_smokeping_configured():
        return jsonify({"error": "Smokeping not configured"}), 404

    timespan_code = SMOKEPING_TIMESPANS.get(timespan)
    if not timespan_code:
        return jsonify({"error": "Invalid timespan"}), 400

    configured = [t.strip() for t in _config_manager.get("smokeping_targets", "").split(",")]
    if target not in configured:
        return jsonify({"error": "Unknown target"}), 404

    base_url = _config_manager.get("smokeping_url", "").rstrip("/")
    target_path = target.replace(".", "/")
    cache_url = f"{base_url}/cache/{target_path}_{timespan_code}.png"

    try:
        # Always trigger CGI to regenerate cache with fresh data
        _requests.get(f"{base_url}/?target={target}", timeout=10)
        r = _requests.get(cache_url, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.warning("Smokeping proxy failed for %s/%s: %s", target, timespan, e)
        return jsonify({"error": "Failed to fetch graph"}), 502

    resp = make_response(r.content)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


# ── BQM ──

@integrations_bp.route("/api/bqm/dates")
@require_auth
def api_bqm_dates():
    """Return dates that have BQM graph data."""
    _storage = get_storage()
    if _storage:
        return jsonify(_storage.get_bqm_dates())
    return jsonify([])


@integrations_bp.route("/api/bqm/image/<date>")
@require_auth
def api_bqm_image(date):
    """Return BQM graph PNG for a given date."""
    _storage = get_storage()
    if not _valid_date(date):
        return jsonify({"error": "Invalid date format"}), 400
    if not _storage:
        return jsonify({"error": "No storage"}), 404
    image = _storage.get_bqm_graph(date)
    if not image:
        return jsonify({"error": "No BQM graph for this date"}), 404
    resp = make_response(image)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@integrations_bp.route("/api/bqm/live")
@require_auth
def api_bqm_live():
    """Fetch live BQM graph PNG from ThinkBroadband, fallback to today's cached."""
    from app import thinkbroadband

    _config_manager = get_config_manager()
    _storage = get_storage()
    bqm_url = _config_manager.get("bqm_url") if _config_manager else None
    image = None
    source = "cached"
    ts = None

    if bqm_url and not (_config_manager and _config_manager.is_demo_mode()):
        image = thinkbroadband.fetch_graph(bqm_url)
        if image:
            from app.tz import utc_now
            source = "live"
            ts = utc_now()

    if not image and _storage:
        from app.tz import local_today
        today = local_today(_get_tz_name())
        image = _storage.get_bqm_graph(today)
        if image:
            source = "cached"

    if not image:
        return jsonify({"error": "No BQM graph available"}), 404

    resp = make_response(image)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-BQM-Source"] = source
    if ts:
        resp.headers["X-BQM-Timestamp"] = ts
    return resp


@integrations_bp.route("/api/bqm/import", methods=["POST"])
@require_auth
def api_bqm_import():
    """Bulk-import BQM graph images with per-file date mapping."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "No storage"}), 500

    files = request.files.getlist("files[]")
    dates_raw = request.form.get("dates", "")
    overwrite = request.form.get("overwrite", "false").lower() == "true"

    if not files or not dates_raw:
        return jsonify({"error": "No files or dates provided"}), 400

    dates = [d.strip() for d in dates_raw.split(",") if d.strip()]
    if len(files) != len(dates):
        return jsonify({"error": "File count does not match date count"}), 400
    if len(files) > 366:
        return jsonify({"error": "Too many files (max 366)"}), 400

    _PNG_MAGIC = b"\x89PNG"
    _JPEG_MAGIC = b"\xff\xd8\xff"
    _MAX_SIZE = 2 * 1024 * 1024  # 2 MB

    imported = 0
    skipped = 0
    replaced = 0
    skipped_dates = []
    errors = []

    for f, date in zip(files, dates):
        fname = f.filename or "unknown"

        if not _valid_date(date):
            errors.append({"filename": fname, "error": "Invalid date"})
            continue

        data = f.read()
        if len(data) > _MAX_SIZE:
            errors.append({"filename": fname, "error": "File too large (max 2 MB)"})
            continue
        if not (data[:4] == _PNG_MAGIC or data[:3] == _JPEG_MAGIC):
            errors.append({"filename": fname, "error": "Not a PNG or JPEG image"})
            continue

        try:
            result = _storage.import_bqm_graph(date, data, overwrite=overwrite)
            if result == "imported":
                imported += 1
            elif result == "skipped":
                skipped += 1
                skipped_dates.append(date)
            elif result == "replaced":
                replaced += 1
        except Exception as e:
            log.error("BQM import error for %s: %s", fname, e)
            errors.append({"filename": fname, "error": str(e)})

    return jsonify({
        "imported": imported,
        "skipped": skipped,
        "replaced": replaced,
        "skipped_dates": skipped_dates,
        "errors": errors,
    })


@integrations_bp.route("/api/bqm/images", methods=["DELETE"])
@require_auth
def api_bqm_delete():
    """Delete BQM images: single date, range, or all."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    if data.get("all"):
        if data.get("confirm") != "DELETE_ALL":
            return jsonify({"error": "Confirmation required: set confirm to 'DELETE_ALL'"}), 400
        deleted = _storage.delete_all_bqm_graphs()
        audit_log.info("All BQM images deleted: ip=%s count=%d", _get_client_ip(), deleted)
        return jsonify({"deleted": deleted})

    start = data.get("start")
    end = data.get("end")
    if start and end:
        if not _valid_date(start) or not _valid_date(end):
            return jsonify({"error": "Invalid date format"}), 400
        deleted = _storage.delete_bqm_graphs_range(start, end)
        audit_log.info("BQM images deleted range: ip=%s start=%s end=%s count=%d", _get_client_ip(), start, end, deleted)
        return jsonify({"deleted": deleted})

    date = data.get("date")
    if date:
        if not _valid_date(date):
            return jsonify({"error": "Invalid date format"}), 400
        deleted = 1 if _storage.delete_bqm_graph(date) else 0
        audit_log.info("BQM image deleted: ip=%s date=%s", _get_client_ip(), date)
        return jsonify({"deleted": deleted})

    return jsonify({"error": "Provide 'all', 'start'+'end', or 'date'"}), 400


# ── Speedtest helpers ──

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


# ── Speedtest API ──

@integrations_bp.route("/api/speedtest")
@require_auth
def api_speedtest():
    """Return speedtest results from local cache, with delta fetch from STT."""
    _config_manager = get_config_manager()
    _storage = get_storage()
    if not _config_manager or not _config_manager.is_speedtest_configured():
        return jsonify([])
    count = request.args.get("count", 2000, type=int)
    count = max(1, min(count, 5000))
    # Demo mode: return seeded data without external API call
    if _config_manager.is_demo_mode() and _storage:
        results = _storage.get_speedtest_results(limit=count)
        return jsonify([_enrich_speedtest(r) for r in results])
    # Delta fetch: get new results from STT API and cache them
    if _storage:
        try:
            from app.speedtest import SpeedtestClient
            client = SpeedtestClient(
                _config_manager.get("speedtest_tracker_url"),
                _config_manager.get("speedtest_tracker_token"),
            )
            cached_count = _storage.get_speedtest_count()
            if cached_count < 50:
                # Initial or incomplete cache: full fetch (descending)
                new_results = client.get_results(per_page=2000)
            else:
                last_id = _storage.get_latest_speedtest_id()
                new_results = client.get_newer_than(last_id)
            if new_results:
                _storage.save_speedtest_results(new_results)
                log.info("Cached %d new speedtest results (last_id was %d)", len(new_results), last_id)
        except Exception as e:
            log.warning("Speedtest delta fetch failed: %s", e)
        results = _storage.get_speedtest_results(limit=count)
        return jsonify([_enrich_speedtest(r) for r in results])
    # Fallback: no storage, fetch directly
    from app.speedtest import SpeedtestClient
    client = SpeedtestClient(
        _config_manager.get("speedtest_tracker_url"),
        _config_manager.get("speedtest_tracker_token"),
    )
    results = client.get_results(per_page=count)
    return jsonify([_enrich_speedtest(r) for r in results])


@integrations_bp.route("/api/speedtest/<int:result_id>")
@require_auth
def api_speedtest_detail(result_id):
    """Return full speedtest result by ID."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    result = _storage.get_speedtest_by_id(result_id)
    if not result:
        return jsonify({"error": "Speedtest result not found"}), 404
    return jsonify(_enrich_speedtest(result))


@integrations_bp.route("/api/speedtest/<int:result_id>/signal")
@require_auth
def api_speedtest_signal(result_id):
    """Return the closest DOCSIS snapshot signal data for a speedtest result."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    result = _storage.get_speedtest_by_id(result_id)
    if not result:
        return jsonify({"error": "Speedtest result not found"}), 404
    snap = _storage.get_closest_snapshot(result["timestamp"])
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


# ── Breitbandmessung (BNetzA) API ──

@integrations_bp.route("/api/bnetz/upload", methods=["POST"])
@require_auth
def api_bnetz_upload():
    """Upload a BNetzA Messprotokoll PDF, parse it, and store the results."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = f.filename.lower()
    is_csv = filename.endswith(".csv")
    is_pdf = filename.endswith(".pdf") or (f.content_type and f.content_type == "application/pdf")

    if not is_csv and not is_pdf:
        return jsonify({"error": "Only PDF and CSV files are accepted"}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_ATTACHMENT_SIZE:
        return jsonify({"error": "File too large (max 10 MB)"}), 400

    lang = _get_lang()
    t = get_translations(lang)

    if is_csv:
        try:
            from app.bnetz_csv_parser import parse_bnetz_csv
            csv_content = file_bytes.decode("utf-8-sig")
            parsed = parse_bnetz_csv(csv_content)
        except (ValueError, UnicodeDecodeError) as e:
            return jsonify({"error": t.get("bnetz_parse_error", str(e))}), 400
        measurement_id = _storage.save_bnetz_measurement(parsed, pdf_bytes=None, source="upload")
    else:
        if not file_bytes[:5] == b"%PDF-":
            return jsonify({"error": "Not a valid PDF file"}), 400
        try:
            from app.bnetz_parser import parse_bnetz_pdf
            parsed = parse_bnetz_pdf(file_bytes)
        except ValueError as e:
            return jsonify({"error": t.get("bnetz_parse_error", str(e))}), 400
        measurement_id = _storage.save_bnetz_measurement(parsed, file_bytes, source="upload")

    audit_log.info(
        "BNetzA measurement uploaded: ip=%s id=%d provider=%s date=%s type=%s",
        _get_client_ip(), measurement_id,
        parsed.get("provider", "?"), parsed.get("date", "?"),
        "csv" if is_csv else "pdf",
    )
    return jsonify({"id": measurement_id, "parsed": parsed}), 201


@integrations_bp.route("/api/bnetz/measurements")
@require_auth
def api_bnetz_list():
    """Return list of BNetzA measurements (without PDF blob)."""
    _storage = get_storage()
    if not _storage:
        return jsonify([])
    limit = request.args.get("limit", 50, type=int)
    return jsonify(_storage.get_bnetz_measurements(limit=limit))


@integrations_bp.route("/api/bnetz/pdf/<int:measurement_id>")
@require_auth
def api_bnetz_pdf(measurement_id):
    """Download the original BNetzA Messprotokoll PDF."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    pdf = _storage.get_bnetz_pdf(measurement_id)
    if not pdf:
        return jsonify({"error": "Not found"}), 404
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"bnetz_messprotokoll_{measurement_id}.pdf",
    )


@integrations_bp.route("/api/bnetz/<int:measurement_id>", methods=["DELETE"])
@require_auth
def api_bnetz_delete(measurement_id):
    """Delete a BNetzA measurement."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_bnetz_measurement(measurement_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("BNetzA measurement deleted: ip=%s id=%d", _get_client_ip(), measurement_id)
    return jsonify({"success": True})
