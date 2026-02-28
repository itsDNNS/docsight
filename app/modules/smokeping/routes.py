"""Smokeping module routes."""

import logging

import requests as _requests

from flask import Blueprint, jsonify, make_response

from app.web import (
    require_auth,
    get_config_manager,
)

log = logging.getLogger("docsis.web")

bp = Blueprint("smokeping_module", __name__)


SMOKEPING_TIMESPANS = {
    "3h": "last_10800",
    "30h": "last_108000",
    "10d": "last_864000",
    "1y": "last_31104000",
}


# ── Smokeping ──

@bp.route("/api/smokeping/targets")
@require_auth
def api_smokeping_targets():
    """Return list of configured Smokeping targets."""
    _config_manager = get_config_manager()
    if not _config_manager or not _config_manager.is_smokeping_configured():
        return jsonify([])
    raw = _config_manager.get("smokeping_targets", "")
    targets = [t.strip() for t in raw.split(",") if t.strip()]
    return jsonify(targets)


@bp.route("/api/smokeping/graph/<path:target>/<timespan>")
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
