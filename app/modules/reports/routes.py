"""Report generation routes."""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, make_response, request

from app.aggregation import select_preferred_bnetz
from app.tz import utc_cutoff, utc_now
from app.web import (
    _get_lang,
    get_config_manager,
    get_state,
    get_storage,
    require_auth,
)

from .report import generate_complaint_text, generate_report

log = logging.getLogger("docsis.web")

bp = Blueprint("reports_bp", __name__)


def _window_error(message, code, field=None):
    payload = {"error": message, "code": code}
    if field is not None:
        payload["field"] = field
    return jsonify(payload), 400


def _parse_window_bound(value, field):
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None, _window_error(
            f"'{field}' must be a valid ISO-8601 timestamp",
            "window_invalid_timestamp",
            field,
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, _window_error(
            f"'{field}' must include a timezone",
            "window_timezone_required",
            field,
        )
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return normalized, None


def _get_report_window():
    """Return inclusive canonical UTC bounds, or a stable JSON 400 response."""
    from_value = request.args.get("from")
    to_value = request.args.get("to")
    has_from = from_value is not None
    has_to = to_value is not None
    has_days = "days" in request.args

    if has_days and (has_from or has_to):
        return None, _window_error(
            "'days' cannot be combined with 'from' and 'to'",
            "window_ambiguous_mode",
        )
    if has_from != has_to:
        return None, _window_error(
            "Both 'from' and 'to' are required",
            "window_bounds_required",
        )

    if has_from:
        start, error = _parse_window_bound(from_value, "from")
        if error:
            return None, error
        end, error = _parse_window_bound(to_value, "to")
        if error:
            return None, error
        if start > end:
            return None, _window_error(
                "'from' must not be after 'to'",
                "window_invalid_order",
            )
        if end - start > timedelta(days=90):
            return None, _window_error(
                "Report window must not exceed 90 days",
                "window_too_large",
            )
        return (
            start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ), None

    days_value = request.args.get("days")
    if days_value is None:
        days = 7
    else:
        try:
            days = int(days_value)
        except (TypeError, ValueError):
            return None, _window_error(
                "'days' must be an integer",
                "window_invalid_days",
                "days",
            )
    days = max(1, min(days, 90))
    end = utc_now()
    start = utc_cutoff(days=days)
    return (start, end), None


def _get_comparison_data(storage):
    from_a = request.args.get("comparison_from_a")
    to_a = request.args.get("comparison_to_a")
    from_b = request.args.get("comparison_from_b")
    to_b = request.args.get("comparison_to_b")
    if not storage or not all([from_a, to_a, from_b, to_b]):
        return None
    try:
        from app.modules.comparison.routes import compare_periods
        return compare_periods(storage, from_a, to_a, from_b, to_b)
    except (ImportError, Exception):
        return None


@bp.route("/api/report")
@require_auth
def api_report():
    """Generate a PDF incident report."""
    _storage = get_storage()
    _config_manager = get_config_manager()
    window, error = _get_report_window()
    if error:
        return error
    start_ts, end_ts = window

    snapshots = []
    if _storage:
        snapshots = _storage.get_range_data(start_ts, end_ts)

    config = {}
    if _config_manager:
        config = {
            "isp_name": _config_manager.get("isp_name", ""),
            "modem_type": _config_manager.get("modem_type", ""),
        }

    conn_info = (get_state().get("connection_info") or {})
    lang = request.args.get("lang", _get_lang())
    comparison_data = _get_comparison_data(_storage)
    customer_name = request.args.get("name", "")
    customer_number = request.args.get("number", "")
    customer_address = request.args.get("address", "")

    pdf_bytes = generate_report(
        snapshots,
        config=config,
        connection_info=conn_info,
        lang=lang,
        comparison_data=comparison_data,
        customer_name=customer_name,
        customer_number=customer_number,
        customer_address=customer_address,
        report_start=start_ts,
        report_end=end_ts,
    )

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    response.headers["Content-Disposition"] = f'attachment; filename="docsight_incident_report_{ts}.pdf"'
    return response


@bp.route("/api/complaint")
@require_auth
def api_complaint():
    """Generate ISP complaint letter as text."""
    _storage = get_storage()
    _config_manager = get_config_manager()
    window, error = _get_report_window()
    if error:
        return error
    start_ts, end_ts = window

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
        try:
            # BNetzA storage is in the bnetz module — try to get it
            from app.modules.bnetz.storage import BnetzStorage
            _bnetz_storage = BnetzStorage(_storage.db_path)
            if bnetz_id:
                all_bnetz = _bnetz_storage.get_bnetz_measurements(limit=100)
                bnetz_data = next((m for m in all_bnetz if m["id"] == bnetz_id), None)
            else:
                in_range = _bnetz_storage.get_bnetz_in_range(start_ts, end_ts)
                bnetz_data = select_preferred_bnetz(in_range)
        except (ImportError, Exception):
            pass  # BNetzA module not available

    comparison_data = _get_comparison_data(_storage)

    text = generate_complaint_text(
        snapshots,
        config,
        None,
        lang,
        customer_name,
        customer_number,
        customer_address,
        bnetz_data=bnetz_data,
        comparison_data=comparison_data,
        report_start=start_ts,
        report_end=end_ts,
    )
    return jsonify({
        "text": text,
        "lang": lang,
        "window": {"from": start_ts, "to": end_ts},
    })
