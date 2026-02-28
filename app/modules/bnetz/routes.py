"""BNetzA module routes."""

import logging
from io import BytesIO

from flask import Blueprint, request, jsonify, send_file

from app.web import require_auth, get_storage, get_config_manager, _get_client_ip, _get_lang
from app.storage import MAX_ATTACHMENT_SIZE
from app.i18n import get_translations
from .storage import BnetzStorage

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web.bnetz")

bp = Blueprint("bnetz_module", __name__)

# Lazy-initialized module-local storage
_storage = None


def _get_bnetz_storage():
    global _storage
    if _storage is None:
        core_storage = get_storage()
        if core_storage:
            _storage = BnetzStorage(core_storage.db_path)
    return _storage


@bp.route("/api/bnetz/upload", methods=["POST"])
@require_auth
def api_bnetz_upload():
    """Upload a BNetzA Messprotokoll PDF, parse it, and store the results."""
    bs = _get_bnetz_storage()
    if not bs:
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
            from .csv_parser import parse_bnetz_csv
            csv_content = file_bytes.decode("utf-8-sig")
            parsed = parse_bnetz_csv(csv_content)
        except (ValueError, UnicodeDecodeError) as e:
            return jsonify({"error": t.get("bnetz_parse_error", str(e))}), 400
        measurement_id = bs.save_bnetz_measurement(parsed, pdf_bytes=None, source="upload")
    else:
        if not file_bytes[:5] == b"%PDF-":
            return jsonify({"error": "Not a valid PDF file"}), 400
        try:
            from .parser import parse_bnetz_pdf
            parsed = parse_bnetz_pdf(file_bytes)
        except ValueError as e:
            return jsonify({"error": t.get("bnetz_parse_error", str(e))}), 400
        measurement_id = bs.save_bnetz_measurement(parsed, file_bytes, source="upload")

    audit_log.info(
        "BNetzA measurement uploaded: ip=%s id=%d provider=%s date=%s type=%s",
        _get_client_ip(), measurement_id,
        parsed.get("provider", "?"), parsed.get("date", "?"),
        "csv" if is_csv else "pdf",
    )
    return jsonify({"id": measurement_id, "parsed": parsed}), 201


@bp.route("/api/bnetz/measurements")
@require_auth
def api_bnetz_list():
    """Return list of BNetzA measurements (without PDF blob)."""
    bs = _get_bnetz_storage()
    if not bs:
        return jsonify([])
    limit = request.args.get("limit", 50, type=int)
    return jsonify(bs.get_bnetz_measurements(limit=limit))


@bp.route("/api/bnetz/pdf/<int:measurement_id>")
@require_auth
def api_bnetz_pdf(measurement_id):
    """Download the original BNetzA Messprotokoll PDF."""
    bs = _get_bnetz_storage()
    if not bs:
        return jsonify({"error": "Storage not initialized"}), 500
    pdf = bs.get_bnetz_pdf(measurement_id)
    if not pdf:
        return jsonify({"error": "Not found"}), 404
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"bnetz_messprotokoll_{measurement_id}.pdf",
    )


@bp.route("/api/bnetz/<int:measurement_id>", methods=["DELETE"])
@require_auth
def api_bnetz_delete(measurement_id):
    """Delete a BNetzA measurement."""
    bs = _get_bnetz_storage()
    if not bs:
        return jsonify({"error": "Storage not initialized"}), 500
    if not bs.delete_bnetz_measurement(measurement_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("BNetzA measurement deleted: ip=%s id=%d", _get_client_ip(), measurement_id)
    return jsonify({"success": True})
