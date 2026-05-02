"""Local maintainer notices API."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.maintainer_notices import (
    coerce_dismissed_notice_ids,
    get_active_notices,
    is_valid_notice_id,
)
from app.web import APP_VERSION, get_config_manager, require_auth

notices_bp = Blueprint("notices_bp", __name__)


def _dismissed_ids(config_mgr) -> list[str]:
    raw = config_mgr.get("dismissed_notice_ids", []) if config_mgr else []
    return coerce_dismissed_notice_ids(raw)


@notices_bp.route("/api/notices")
@require_auth
def api_notices_list():
    """List active local maintainer notices."""
    location = request.args.get("location")
    if location not in (None, "dashboard", "settings"):
        return jsonify({"success": False, "error": "Invalid notice location"}), 400

    config_mgr = get_config_manager()
    notices = get_active_notices(
        APP_VERSION,
        dismissed_ids=_dismissed_ids(config_mgr),
        location=location,
    )
    return jsonify({"success": True, "notices": notices})


@notices_bp.route("/api/notices/<notice_id>/dismiss", methods=["POST"])
@require_auth
def api_notice_dismiss(notice_id):
    """Persist a local notice dismissal by stable notice id."""
    if not is_valid_notice_id(notice_id):
        return jsonify({"success": False, "error": "Invalid notice id"}), 400

    config_mgr = get_config_manager()
    if not config_mgr:
        return jsonify({"success": False, "error": "Config not initialized"}), 500

    dismissed = _dismissed_ids(config_mgr)
    if notice_id not in dismissed:
        dismissed.append(notice_id)
    persisted = coerce_dismissed_notice_ids(dismissed)
    config_mgr.save({"dismissed_notice_ids": persisted})
    return jsonify({"success": True, "dismissed_notice_ids": persisted})
