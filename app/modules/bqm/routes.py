"""BQM module routes."""

import logging

from flask import Blueprint, request, jsonify, make_response

from app.web import (
    require_auth,
    get_storage, get_config_manager, get_state,
    _valid_date, _get_client_ip, _get_tz_name,
)
from .storage import BqmStorage

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web.bqm")

bp = Blueprint("bqm_module", __name__)

# Lazy-initialized module-local storage
_storage = None


def _get_bqm_storage():
    global _storage
    if _storage is None:
        core_storage = get_storage()
        if core_storage:
            _storage = BqmStorage(core_storage.db_path)
    return _storage


@bp.route("/api/bqm/dates")
@require_auth
def api_bqm_dates():
    """Return dates that have BQM graph data."""
    bs = _get_bqm_storage()
    if bs:
        return jsonify(bs.get_bqm_dates())
    return jsonify([])


@bp.route("/api/bqm/image/<date>")
@require_auth
def api_bqm_image(date):
    """Return BQM graph PNG for a given date."""
    bs = _get_bqm_storage()
    if not _valid_date(date):
        return jsonify({"error": "Invalid date format"}), 400
    if not bs:
        return jsonify({"error": "No storage"}), 404
    image = bs.get_bqm_graph(date)
    if not image:
        return jsonify({"error": "No BQM graph for this date"}), 404
    resp = make_response(image)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.route("/api/bqm/live")
@require_auth
def api_bqm_live():
    """Fetch live BQM graph PNG from ThinkBroadband, fallback to today's cached."""
    from .thinkbroadband import fetch_graph

    _config_manager = get_config_manager()
    bs = _get_bqm_storage()
    bqm_url = _config_manager.get("bqm_url") if _config_manager else None
    image = None
    source = "cached"
    ts = None

    if bqm_url and not (_config_manager and _config_manager.is_demo_mode()):
        image = fetch_graph(bqm_url)
        if image:
            from app.tz import utc_now
            source = "live"
            ts = utc_now()

    if not image and bs:
        from app.tz import local_today
        today = local_today(_get_tz_name())
        image = bs.get_bqm_graph(today)
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


@bp.route("/api/bqm/import", methods=["POST"])
@require_auth
def api_bqm_import():
    """Bulk-import BQM graph images with per-file date mapping."""
    bs = _get_bqm_storage()
    if not bs:
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
            result = bs.import_bqm_graph(date, data, overwrite=overwrite)
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


@bp.route("/api/bqm/images", methods=["DELETE"])
@require_auth
def api_bqm_delete():
    """Delete BQM images: single date, range, or all."""
    bs = _get_bqm_storage()
    if not bs:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    if data.get("all"):
        if data.get("confirm") != "DELETE_ALL":
            return jsonify({"error": "Confirmation required: set confirm to 'DELETE_ALL'"}), 400
        deleted = bs.delete_all_bqm_graphs()
        audit_log.info("All BQM images deleted: ip=%s count=%d", _get_client_ip(), deleted)
        return jsonify({"deleted": deleted})

    start = data.get("start")
    end = data.get("end")
    if start and end:
        if not _valid_date(start) or not _valid_date(end):
            return jsonify({"error": "Invalid date format"}), 400
        deleted = bs.delete_bqm_graphs_range(start, end)
        audit_log.info("BQM images deleted range: ip=%s start=%s end=%s count=%d", _get_client_ip(), start, end, deleted)
        return jsonify({"deleted": deleted})

    date = data.get("date")
    if date:
        if not _valid_date(date):
            return jsonify({"error": "Invalid date format"}), 400
        deleted = 1 if bs.delete_bqm_graph(date) else 0
        audit_log.info("BQM image deleted: ip=%s date=%s", _get_client_ip(), date)
        return jsonify({"deleted": deleted})

    return jsonify({"error": "Provide 'all', 'start'+'end', or 'date'"}), 400
