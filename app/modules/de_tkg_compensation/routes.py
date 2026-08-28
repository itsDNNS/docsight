"""Authenticated thin HTTP adapters for German TKG compensation claims."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from io import BytesIO
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, jsonify, request, send_file

from app.tz import get_tz_name, local_to_utc, local_today
from app.web import get_config_manager, get_module_loader, get_storage, require_auth

from .candidates import (
    CONNECTION_CANDIDATE_LOOKBACK_DAYS,
    CONNECTION_CANDIDATE_MAX_RESULTS,
    CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET,
    CONNECTION_CANDIDATE_MAX_TARGETS,
    INCIDENT_CANDIDATE_MAX_RESULTS,
    chunk_report_windows,
    load_connection_monitor_candidates,
    load_incident_candidates,
)
from .capabilities import get_capabilities
from .letter import render_claim_letter
from .rules import (
    RuleValidationError,
    compute_missed_appointment,
    compute_outage_compensation,
    empty_compensation_breakdown,
)
from .rules_data import RULESET_DE_TKG58, resolve_ruleset
from .storage import ClaimStorage


bp = Blueprint("de_tkg_bp", __name__)

_CLAIM_FIELDS = {
    "status", "window_from", "window_to", "origin",
    "fault_report_received_date", "fault_report_channel", "ticket_ref",
    "restored_date", "monthly_fee_cents", "confirmed_days", "eligibility",
    "prior_credit", "letter_text",
}
_CREDIT_CLASSIFICATIONS = {"goodwill", "reduction", "compensation", "unclear"}
_ELIGIBILITY_FIELDS = {
    "complete_outage", "replacement_solution_days", "user_responsibility",
    "force_majeure", "lawful_interruption", "missed_appointments",
}
MAX_MISSED_APPOINTMENTS = 100
_LETTER_FACT_FIELDS = _CLAIM_FIELDS - {"status", "letter_text"}
_GENERIC_VALIDATION_ERROR = (
    "technical_validation_failed",
    "The request could not be validated",
)
_PUBLIC_VALIDATION_ERRORS = {
    "eligibility_claim_basis_required": "Confirm a complete outage or at least one missed appointment",
    "eligibility_confirmed_days_required": "Confirm each complete-outage calendar day before calculating",
    "eligibility_statutory_exclusion_confirmed": "A confirmed statutory exclusion prevents this calculation",
    "technical_claim_window_invalid": "Claim-window bounds must be calendar dates",
    "technical_claim_window_required": "A selected claim window is required for an outage calculation",
    "technical_claim_window_reversed": "Claim-window end cannot precede its start",
    "technical_complete_outage_invalid": "Complete-outage confirmation must be boolean",
    "technical_confirmed_day_invalid": "Confirmed day must be YYYY-MM-DD",
    "technical_confirmed_day_outside_claim_window": "Confirmed day lies outside the selected claim window",
    "technical_confirmed_day_outside_window": "Confirmed day lies outside the reported outage window",
    "technical_confirmed_days_invalid": "Confirmed days must be a list",
    "technical_date_invalid": "Dates must be calendar dates",
    "technical_eligibility_field_unknown": "Unknown eligibility field",
    "technical_eligibility_invalid": "Eligibility must be an object",
    "technical_fault_report_channel_invalid": "Invalid fault-report channel",
    "technical_fault_report_received_date_invalid": "Fault-report receipt date must be YYYY-MM-DD",
    "technical_force_majeure_invalid": "Force-majeure confirmation must be boolean",
    "technical_json_object_required": "JSON object required",
    "technical_lawful_interruption_invalid": "Lawful-interruption confirmation must be boolean",
    "technical_letter_text_invalid": "Invalid letter text",
    "technical_missed_appointments_invalid": "Missed appointment count must be a non-negative integer",
    "technical_missed_appointments_limit": "Missed appointment count exceeds the technical maximum of 100",
    "technical_monthly_fee_invalid": "Monthly fee must be integer cents",
    "technical_monthly_fee_negative": "Monthly fee cannot be negative",
    "technical_monthly_fee_required": "Monthly fee is required",
    "technical_origin_invalid": "Unknown candidate origin",
    "technical_prior_credit_classification_invalid": "Prior credit classification is invalid",
    "technical_prior_credit_field_unknown": "Unknown prior credit field",
    "technical_prior_credit_invalid": "Prior credit is invalid",
    "technical_replacement_day_unconfirmed": "Replacement-solution days must also be confirmed outage days",
    "technical_replacement_solution_day_invalid": "Replacement-solution day must be YYYY-MM-DD",
    "technical_replacement_solution_days_invalid": "Replacement-solution days must be a list",
    "technical_report_in_future": "Fault-report date cannot be in the future",
    "technical_restored_date_invalid": "Restoration date must be YYYY-MM-DD",
    "technical_restored_before_report": "Restoration date cannot be before fault-report receipt",
    "technical_restored_in_future": "Restoration date cannot be in the future",
    "technical_rules_version_unsupported": "Stored rules version is unsupported",
    "technical_status_invalid": "Status must be draft or completed",
    "technical_ticket_ref_invalid": "Invalid ticket reference",
    "technical_unknown_field": "Unknown claim field",
    "technical_user_responsibility_invalid": "User-responsibility confirmation must be boolean",
    "technical_window_from_invalid": "Claim-window start must be a timestamp",
    "technical_window_from_timezone_invalid": "Claim-window start cannot be interpreted in the configured timezone",
    "technical_window_reversed": "Window end cannot precede window start",
    "technical_window_to_invalid": "Claim-window end must be a timestamp",
    "technical_window_to_timezone_invalid": "Claim-window end cannot be interpreted in the configured timezone",
}


def _error(code: str, message: str, status: int = 400):
    return jsonify({"error": message, "code": code}), status


def _validation_error_response(exc: RuleValidationError, status: int = 400):
    exception_code = getattr(exc, "code", None)
    for allowed_code, allowed_message in _PUBLIC_VALIDATION_ERRORS.items():
        if exception_code == allowed_code:
            return _error(allowed_code, allowed_message, status)
    return _error(_GENERIC_VALIDATION_ERROR[0], _GENERIC_VALIDATION_ERROR[1], status)


def _storage() -> ClaimStorage | None:
    core = get_storage()
    return ClaimStorage(core.db_path) if core else None


def _connection_db_path() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "/data"), "connection_monitor.db")


def _capabilities() -> dict[str, bool]:
    return get_capabilities(
        get_config_manager(), get_module_loader(), connection_db_path=_connection_db_path()
    )


def _calendar_date(value, field: str, *, optional: bool = False) -> date | None:
    if value in (None, "") and optional:
        return None
    if not isinstance(value, str):
        raise RuleValidationError(f"technical_{field}_invalid", f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RuleValidationError(
            f"technical_{field}_invalid", f"{field} must be YYYY-MM-DD"
        ) from None


def _utc_timestamp(value, field: str, tz_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RuleValidationError(f"technical_{field}_invalid", f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RuleValidationError(f"technical_{field}_invalid", f"{field} must be a timestamp") from None
    if parsed.tzinfo is None:
        try:
            return local_to_utc(parsed.strftime("%Y-%m-%dT%H:%M:%S"), tz_name)
        except (OSError, ValueError, ZoneInfoNotFoundError):
            raise RuleValidationError(
                f"technical_{field}_timezone_invalid",
                f"{field} cannot be interpreted in the configured timezone",
            ) from None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalise_claim_payload(data, tz_name: str) -> dict:
    if not isinstance(data, dict):
        raise RuleValidationError("technical_json_object_required", "JSON object required")
    unknown = sorted(set(data) - _CLAIM_FIELDS)
    if unknown:
        raise RuleValidationError(
            "technical_unknown_field", f"Unknown claim field: {unknown[0]}"
        )
    payload = dict(data)
    if "status" in payload and payload["status"] not in {"draft", "completed"}:
        raise RuleValidationError("technical_status_invalid", "Status must be draft or completed")
    if "origin" in payload and payload["origin"] not in {"manual", "telemetry", "incident"}:
        raise RuleValidationError("technical_origin_invalid", "Unknown candidate origin")
    for field, maximum in {
        "fault_report_channel": 100,
        "ticket_ref": 500,
        "letter_text": 200_000,
    }.items():
        if field in payload and payload[field] is not None:
            if not isinstance(payload[field], str) or len(payload[field]) > maximum:
                raise RuleValidationError(f"technical_{field}_invalid", f"Invalid {field}")
            payload[field] = payload[field].strip()
    for field in ("fault_report_received_date", "restored_date"):
        if field in payload:
            parsed = _calendar_date(payload[field], field, optional=True)
            payload[field] = parsed.isoformat() if parsed else None
    for field in ("window_from", "window_to"):
        if field in payload:
            payload[field] = _utc_timestamp(payload[field], field, tz_name)
    if payload.get("window_from") and payload.get("window_to"):
        start = datetime.fromisoformat(payload["window_from"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(payload["window_to"].replace("Z", "+00:00"))
        if end < start:
            raise RuleValidationError(
                "technical_window_reversed", "Window end cannot precede window start"
            )
    if "monthly_fee_cents" in payload:
        fee = payload["monthly_fee_cents"]
        if fee is not None and (isinstance(fee, bool) or not isinstance(fee, int)):
            raise RuleValidationError(
                "technical_monthly_fee_invalid", "Monthly fee must be integer cents"
            )
    if "confirmed_days" in payload:
        days = payload["confirmed_days"]
        if not isinstance(days, list):
            raise RuleValidationError(
                "technical_confirmed_days_invalid", "Confirmed days must be a list"
            )
        payload["confirmed_days"] = [
            _calendar_date(value, "confirmed_day").isoformat() for value in days
        ]
    if "eligibility" in payload:
        eligibility = payload["eligibility"]
        if not isinstance(eligibility, dict):
            raise RuleValidationError("technical_eligibility_invalid", "Eligibility must be an object")
        unknown_eligibility = sorted(set(eligibility) - _ELIGIBILITY_FIELDS)
        if unknown_eligibility:
            raise RuleValidationError(
                "technical_eligibility_field_unknown",
                f"Unknown eligibility field: {unknown_eligibility[0]}",
            )
        for field in (
            "complete_outage", "user_responsibility", "force_majeure",
            "lawful_interruption",
        ):
            if field in eligibility and not isinstance(eligibility[field], bool):
                raise RuleValidationError(
                    f"technical_{field}_invalid", f"{field} must be boolean"
                )
        replacement_days = eligibility.get("replacement_solution_days", [])
        if not isinstance(replacement_days, list):
            raise RuleValidationError(
                "technical_replacement_solution_days_invalid",
                "Replacement-solution days must be a list",
            )
        if "replacement_solution_days" in eligibility:
            eligibility["replacement_solution_days"] = [
                _calendar_date(value, "replacement_solution_day").isoformat()
                for value in replacement_days
            ]
        appointment_count = eligibility.get("missed_appointments", 0)
        if (
            isinstance(appointment_count, bool)
            or not isinstance(appointment_count, int)
            or appointment_count < 0
        ):
            raise RuleValidationError(
                "technical_missed_appointments_invalid",
                "Missed appointment count must be a non-negative integer",
            )
        if appointment_count > MAX_MISSED_APPOINTMENTS:
            raise RuleValidationError(
                "technical_missed_appointments_limit",
                f"Missed appointment count exceeds the technical maximum of {MAX_MISSED_APPOINTMENTS}",
            )
    if "prior_credit" in payload:
        credit = payload["prior_credit"]
        if not isinstance(credit, dict):
            raise RuleValidationError("technical_prior_credit_invalid", "Prior credit must be an object")
        if set(credit) - {"amount_cents", "classification"}:
            raise RuleValidationError(
                "technical_prior_credit_field_unknown", "Unknown prior credit field"
            )
        amount = credit.get("amount_cents")
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int) or amount < 0):
            raise RuleValidationError("technical_prior_credit_invalid", "Prior credit amount is invalid")
        classification = credit.get("classification")
        if classification is not None and classification not in _CREDIT_CLASSIFICATIONS:
            raise RuleValidationError(
                "technical_prior_credit_classification_invalid", "Prior credit classification is invalid"
            )
    return payload


def _configured_zone(tz_name: str):
    try:
        return ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_window_dates(claim: dict, tz_name: str) -> tuple[date, date]:
    if not claim.get("window_from") or not claim.get("window_to"):
        raise RuleValidationError(
            "technical_claim_window_required",
            "A selected claim window is required for an outage calculation",
        )
    zone = _configured_zone(tz_name)
    start = datetime.fromisoformat(claim["window_from"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(claim["window_to"].replace("Z", "+00:00"))
    return start.astimezone(zone).date(), end.astimezone(zone).date()


def _calculate_claim(claim: dict):
    eligibility = claim.get("eligibility") or {}
    count = eligibility.get("missed_appointments", 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise RuleValidationError(
            "technical_missed_appointments_invalid",
            "Missed appointment count must be a non-negative integer",
        )
    if count > MAX_MISSED_APPOINTMENTS:
        raise RuleValidationError(
            "technical_missed_appointments_limit",
            f"Missed appointment count exceeds the technical maximum of {MAX_MISSED_APPOINTMENTS}",
        )
    has_outage = eligibility.get("complete_outage") is True
    if not has_outage and count == 0:
        raise RuleValidationError(
            "eligibility_claim_basis_required",
            "Confirm a complete outage or at least one missed appointment",
        )
    tz_name = get_tz_name(get_config_manager())
    ruleset = resolve_ruleset(claim.get("rules_version"))
    if has_outage:
        if any(
            eligibility.get(key) is True
            for key in ("user_responsibility", "force_majeure", "lawful_interruption")
        ):
            raise RuleValidationError(
                "eligibility_statutory_exclusion_confirmed",
                "A user-confirmed statutory exclusion prevents this calculation",
            )
        confirmed = claim.get("confirmed_days") or []
        if not confirmed:
            raise RuleValidationError(
                "eligibility_confirmed_days_required",
                "Confirm each complete-outage calendar day before calculating",
            )
        report_date = _calendar_date(
            claim.get("fault_report_received_date"), "fault_report_received_date"
        )
        restored = _calendar_date(
            claim.get("restored_date"), "restored_date", optional=True
        )
        window_start, window_end = _local_window_dates(claim, tz_name)
        breakdown = compute_outage_compensation(
            fault_report_received=report_date,
            restored=restored,
            confirmed_full_outage_days=[
                _calendar_date(value, "confirmed_day") for value in confirmed
            ],
            monthly_fee_cents=claim.get("monthly_fee_cents"),
            replacement_solution_days=[
                _calendar_date(value, "replacement_solution_day")
                for value in eligibility.get("replacement_solution_days", [])
            ],
            claim_window_start=window_start,
            claim_window_end=window_end,
            ruleset=ruleset,
            today=date.fromisoformat(local_today(tz_name)),
        )
    else:
        breakdown = empty_compensation_breakdown(ruleset)
    appointments = tuple(
        compute_missed_appointment(
            monthly_fee_cents=claim.get("monthly_fee_cents"),
            ruleset=ruleset,
        )
        for _ in range(count)
    )
    return breakdown, appointments


def _customer_defaults(capabilities: dict[str, bool]) -> dict[str, str]:
    config = get_config_manager()
    if not capabilities["reports"] or capabilities["demo_mode"] or not config:
        return {}
    return {
        "name": config.get("report_customer_name", "") or "",
        "customer_number": config.get("report_customer_number", "") or "",
        "address": config.get("report_customer_address", "") or "",
    }


def _calculation_response(claim: dict, breakdown, appointments) -> dict:
    capabilities = _capabilities()
    response = breakdown.to_dict()
    response["missed_appointments"] = [item.to_dict() for item in appointments]
    response["missed_appointments_total_cents"] = sum(
        item.amount_cents for item in appointments
    )
    response["grand_total_cents"] = (
        breakdown.total_cents + response["missed_appointments_total_cents"]
    )
    response["prior_credit"] = claim.get("prior_credit") or {}
    response["prior_credit_automatically_deducted"] = False
    response["capabilities"] = capabilities
    response["report_chunks"] = []
    if capabilities["reports"] and claim.get("window_from") and claim.get("window_to"):
        chunks = chunk_report_windows(claim["window_from"], claim["window_to"])
        for chunk in chunks:
            chunk["url"] = "/api/report?" + urlencode(
                {"from": chunk["from"], "to": chunk["to"]}
            )
        response["report_chunks"] = chunks
        response["report_chunk_note"] = (
            "The report is split only because each evidence PDF has a technical "
            "90-day window. This does not limit the compensation period."
        )
    response["evidence_checklist_url"] = (
        "/api/evidence/checklist?"
        + urlencode({"from": claim.get("window_from"), "to": claim.get("window_to")})
        if capabilities["evidence"] and claim.get("window_from") and claim.get("window_to")
        else None
    )
    response["journal_export_url"] = None
    if capabilities["journal"] and claim.get("fault_report_received_date"):
        query = {
            "format": "md",
            "from": claim["fault_report_received_date"],
        }
        if claim.get("restored_date"):
            query["to"] = claim["restored_date"]
        response["journal_export_url"] = "/api/journal/export?" + urlencode(query)
    return response


@bp.route("/api/de-tkg/candidates", methods=["GET"])
@require_auth
def api_candidates():
    capabilities = _capabilities()
    candidates = []
    tz_name = get_tz_name(get_config_manager())
    today_value = local_today(tz_name)
    if capabilities["connection_monitor_source"]:
        candidates.extend(load_connection_monitor_candidates(_connection_db_path(), tz_name))
    core = get_storage()
    if capabilities["journal"] and core:
        candidates.extend(
            load_incident_candidates(
                core.db_path, tz_name, local_today_value=today_value
            )
        )
    return jsonify({
        "candidates": candidates,
        "capabilities": capabilities,
        "customer_defaults": _customer_defaults(capabilities),
        "rules_version": RULESET_DE_TKG58.rules_version,
        "jurisdiction": "DE",
        "timezone": tz_name,
        "local_today": today_value,
        "proposal_limits_note": (
            "Source lookback, sample, target, and result limits apply only to "
            "technical candidate generation and never cap a manual legal claim."
        ),
        "proposal_limits": {
            "connection_lookback_days": CONNECTION_CANDIDATE_LOOKBACK_DAYS,
            "connection_max_targets": CONNECTION_CANDIDATE_MAX_TARGETS,
            "connection_max_samples_per_target": CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET,
            "connection_max_results": CONNECTION_CANDIDATE_MAX_RESULTS,
            "incident_max_results": INCIDENT_CANDIDATE_MAX_RESULTS,
        },
    })


@bp.route("/api/de-tkg/claims", methods=["GET"])
@require_auth
def api_claims_list():
    storage = _storage()
    return jsonify(storage.list() if storage else [])


@bp.route("/api/de-tkg/claims", methods=["POST"])
@require_auth
def api_claims_create():
    storage = _storage()
    if not storage:
        return _error("technical_storage_unavailable", "Storage unavailable", 500)
    try:
        tz_name = get_tz_name(get_config_manager())
        payload = _normalise_claim_payload(request.get_json(silent=True), tz_name)
    except RuleValidationError as exc:
        return _validation_error_response(exc)
    if payload.get("letter_text"):
        return _error(
            "technical_letter_not_generated",
            "Generate the letter from calculated claim facts before editing it",
            409,
        )
    config = get_config_manager()
    claim = storage.create(
        payload, is_demo=bool(config and config.is_demo_mode())
    )
    return jsonify(claim), 201


@bp.route("/api/de-tkg/claims/<int:claim_id>", methods=["GET"])
@require_auth
def api_claim_get(claim_id):
    storage = _storage()
    claim = storage.get(claim_id) if storage else None
    return jsonify(claim) if claim else _error("technical_claim_not_found", "Claim not found", 404)


@bp.route("/api/de-tkg/claims/<int:claim_id>", methods=["PUT"])
@require_auth
def api_claim_update(claim_id):
    storage = _storage()
    if not storage:
        return _error("technical_storage_unavailable", "Storage unavailable", 500)
    try:
        tz_name = get_tz_name(get_config_manager())
        payload = _normalise_claim_payload(request.get_json(silent=True), tz_name)
    except RuleValidationError as exc:
        return _validation_error_response(exc)
    existing = storage.get(claim_id)
    if not existing:
        return _error("technical_claim_not_found", "Claim not found", 404)
    if payload.get("letter_text") and not existing.get("letter_text"):
        return _error(
            "technical_letter_not_generated",
            "Generate the letter from calculated claim facts before editing it",
            409,
        )
    if payload.get("status") == "completed":
        facts_changed = any(
            key in payload and payload[key] != existing.get(key)
            for key in _LETTER_FACT_FIELDS
        )
        resulting_letter = payload.get("letter_text", existing.get("letter_text"))
        if facts_changed or not resulting_letter:
            return _error(
                "technical_letter_not_generated",
                "Regenerate the letter before completing the claim",
                409,
            )
    claim = storage.update(claim_id, payload)
    return jsonify(claim) if claim else _error("technical_claim_not_found", "Claim not found", 404)


@bp.route("/api/de-tkg/claims/<int:claim_id>", methods=["DELETE"])
@require_auth
def api_claim_delete(claim_id):
    storage = _storage()
    if not storage or not storage.delete(claim_id):
        return _error("technical_claim_not_found", "Claim not found", 404)
    return jsonify({"success": True})


@bp.route("/api/de-tkg/claims/<int:claim_id>/calculate", methods=["POST"])
@require_auth
def api_claim_calculate(claim_id):
    storage = _storage()
    claim = storage.get(claim_id) if storage else None
    if not claim:
        return _error("technical_claim_not_found", "Claim not found", 404)
    try:
        breakdown, appointments = _calculate_claim(claim)
    except RuleValidationError as exc:
        return _validation_error_response(exc, 422)
    return jsonify(_calculation_response(claim, breakdown, appointments))


@bp.route("/api/de-tkg/claims/<int:claim_id>/letter", methods=["GET", "POST"])
@require_auth
def api_claim_letter(claim_id):
    storage = _storage()
    claim = storage.get(claim_id) if storage else None
    if not claim:
        return _error("technical_claim_not_found", "Claim not found", 404)
    try:
        ruleset = resolve_ruleset(claim.get("rules_version"))
    except RuleValidationError as exc:
        return _validation_error_response(
            exc, 409 if request.method == "GET" else 422
        )
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or set(data) - {"customer"}:
            return _error("technical_letter_payload_invalid", "Invalid letter payload")
        customer = data.get("customer")
        if customer is not None and not isinstance(customer, dict):
            return _error("technical_customer_invalid", "Customer details must be an object")
        try:
            breakdown, appointments = _calculate_claim(claim)
        except RuleValidationError as exc:
            return _validation_error_response(exc, 422)
        customer = customer if customer is not None else _customer_defaults(_capabilities())
        safe_customer = {}
        for key in ("name", "customer_number", "address"):
            value = customer.get(key, "") if customer else ""
            if not isinstance(value, str) or len(value) > 10_000:
                return _error("technical_customer_invalid", "Customer details are invalid")
            safe_customer[key] = value.strip()
        text = render_claim_letter(
            claim=claim,
            breakdown=breakdown,
            missed_appointments=appointments,
            customer=safe_customer,
        )
        claim = storage.update(claim_id, {"letter_text": text})
    text = claim.get("letter_text") or ""
    if not text:
        return _error("technical_letter_not_generated", "Generate the letter first", 409)
    if request.args.get("download") == "1":
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return send_file(
            BytesIO(text.encode("utf-8")),
            mimetype="text/plain; charset=utf-8",
            as_attachment=True,
            download_name=f"docsight_tkg_entschaedigung_{stamp}.txt",
        )
    return jsonify({
        "letter_text": text,
        "rules_version": ruleset.rules_version,
        "language": "de",
        "filename_prefix": "docsight_tkg_entschaedigung_",
    })
