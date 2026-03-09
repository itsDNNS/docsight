"""FRITZ!Box cable utilization routes."""

import logging

from flask import Blueprint, jsonify

from app import fritzbox as fb
from app.i18n import get_translations
from app.web import get_config_manager, require_auth

log = logging.getLogger("docsis.web.fritzbox_cable")

bp = Blueprint("fritzbox_cable_module", __name__)


def _get_lang():
    from flask import request
    return request.cookies.get("lang", "en")


@bp.route("/api/fritzbox/cable-utilization")
@require_auth
def api_fritzbox_cable_utilization():
    """Return live cable utilization data for supported FRITZ!Box setups."""
    config = get_config_manager()
    t = get_translations(_get_lang())
    if not config:
        return jsonify({"supported": False, "message": t.get("docsight.fritzbox_cable.unavailable", "Configuration unavailable.")}), 503
    if config.is_demo_mode():
        return jsonify({"supported": False, "message": t.get("docsight.fritzbox_cable.demo_mode", "Cable utilization is unavailable in demo mode.")})
    if config.get("modem_type") != "fritzbox":
        return jsonify({"supported": False, "message": t.get("docsight.fritzbox_cable.unsupported_driver", "This view is only available for FRITZ!Box cable devices.")})

    try:
        sid = fb.login(
            config.get("modem_url"),
            config.get("modem_user"),
            config.get("modem_password"),
        )
        return jsonify(fb.get_cable_utilization(config.get("modem_url"), sid))
    except Exception as e:
        log.warning("Failed to load FRITZ!Box cable utilization: %s", e)
        return jsonify({
            "supported": False,
            "message": t.get("docsight.fritzbox_cable.fetch_failed", "Cable utilization could not be loaded from the FRITZ!Box right now."),
        }), 502
