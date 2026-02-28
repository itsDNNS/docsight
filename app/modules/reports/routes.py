"""Report generation routes."""

import logging
import re
from datetime import datetime

from flask import Blueprint, request, jsonify, make_response

from app.web import (
    require_auth,
    get_storage, get_config_manager, get_state,
    _get_lang,
)

log = logging.getLogger("docsis.web")

bp = Blueprint("reports_bp", __name__)


@bp.route("/api/report")
@require_auth
def api_report():
    """Generate a PDF incident report."""
    from .report import generate_report

    _storage = get_storage()
    _config_manager = get_config_manager()
    state = get_state()
    analysis = state.get("analysis")
    if not analysis:
        return jsonify({"error": "No data available"}), 404

    # Time range: default last 7 days, configurable via ?days=N
    from app.tz import utc_now as _utc_now, utc_cutoff as _utc_cutoff
    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 90))
    end_ts = _utc_now()
    start_ts = _utc_cutoff(days=days)

    snapshots = []
    if _storage:
        snapshots = _storage.get_range_data(start_ts, end_ts)

    config = {}
    if _config_manager:
        config = {
            "isp_name": _config_manager.get("isp_name", ""),
            "modem_type": _config_manager.get("modem_type", ""),
        }

    conn_info = state.get("connection_info") or {}
    lang = _get_lang()

    pdf_bytes = generate_report(snapshots, analysis, config, conn_info, lang)

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    response.headers["Content-Disposition"] = f'attachment; filename="docsight_incident_report_{ts}.pdf"'
    return response


@bp.route("/api/complaint")
@require_auth
def api_complaint():
    """Generate ISP complaint letter as text."""
    from .report import generate_complaint_text

    _storage = get_storage()
    _config_manager = get_config_manager()
    analysis = get_state().get("analysis")
    if not analysis:
        return jsonify({"error": "No data available"}), 404

    from app.tz import utc_now as _un, utc_cutoff as _uc
    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 90))
    end_ts = _un()
    start_ts = _uc(days=days)

    snapshots = []
    if _storage:
        snapshots = _storage.get_range_data(start_ts, end_ts)

    config = {}
    if _config_manager:
        config = {
            "isp_name": _config_manager.get("isp_name", ""),
            "modem_type": _config_manager.get("modem_type", ""),
        }

    lang = request.args.get("lang", _get_lang())
    customer_name = request.args.get("name", "")
    customer_number = request.args.get("number", "")
    customer_address = request.args.get("address", "")

    include_bnetz = request.args.get("include_bnetz", "false") == "true"
    bnetz_id = request.args.get("bnetz_id", None, type=int)

    bnetz_data = None
    if _storage and (include_bnetz or bnetz_id):
        if bnetz_id:
            all_bnetz = _storage.get_bnetz_measurements(limit=100)
            bnetz_data = next((m for m in all_bnetz if m["id"] == bnetz_id), None)
        else:
            in_range = _storage.get_bnetz_in_range(start_ts, end_ts)
            # Prefer most recent with deviation
            for m in reversed(in_range):
                if m.get("verdict_download") == "deviation" or m.get("verdict_upload") == "deviation":
                    bnetz_data = m
                    break
            if not bnetz_data and in_range:
                bnetz_data = in_range[-1]

    text = generate_complaint_text(
        snapshots, config, None, lang,
        customer_name, customer_number, customer_address,
        bnetz_data=bnetz_data,
    )
    return jsonify({"text": text, "lang": lang})
