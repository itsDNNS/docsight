"""Configuration and API token management routes."""

import logging

from flask import Blueprint, request, jsonify

from app.web import (
    require_auth, _require_session_auth,
    get_config_manager, get_storage, get_on_config_changed,
    _get_client_ip, _localize_timestamps,
)
from app.config import POLL_MIN, POLL_MAX, SECRET_KEYS, HASH_KEYS

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web")

config_bp = Blueprint("config_bp", __name__)


@config_bp.route("/api/config", methods=["POST"])
@require_auth
def api_config():
    """Save configuration."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify({"success": False, "error": "Config not initialized"}), 500
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data"}), 400
        # Validate timezone if provided
        if "timezone" in data and data["timezone"]:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(data["timezone"])
            except (KeyError, Exception):
                return jsonify({"success": False, "error": "Invalid timezone"}), 400
        # Clamp poll_interval to allowed range
        if "poll_interval" in data:
            try:
                pi = int(data["poll_interval"])
                data["poll_interval"] = max(POLL_MIN, min(POLL_MAX, pi))
            except (ValueError, TypeError):
                pass
        changed_keys = [k for k in data if k not in SECRET_KEYS and k not in HASH_KEYS]
        secret_changed = [k for k in data if k in SECRET_KEYS or k in HASH_KEYS]
        _config_manager.save(data)
        audit_log.info(
            "Config changed: ip=%s keys=%s secrets_changed=%s",
            _get_client_ip(), changed_keys, secret_changed,
        )
        _on_config_changed = get_on_config_changed()
        if _on_config_changed:
            _on_config_changed()
        return jsonify({"success": True})
    except Exception as e:
        log.error("Config save failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ── API Token Management ──

@config_bp.route("/api/tokens", methods=["GET"])
@require_auth
def api_tokens_list():
    """List all API tokens (without hashes)."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not available"}), 500
    tokens = _storage.get_api_tokens()
    _localize_timestamps(tokens)
    return jsonify({"tokens": tokens})


@config_bp.route("/api/tokens", methods=["POST"])
@_require_session_auth
def api_tokens_create():
    """Create a new API token. Session-only (no token auth)."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not available"}), 500
    data = request.get_json()
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Token name is required"}), 400
    token_id, plaintext = _storage.create_api_token(name)
    audit_log.info("API token created: id=%s name=%s ip=%s", token_id, name, _get_client_ip())
    return jsonify({"id": token_id, "token": plaintext, "name": name}), 201


@config_bp.route("/api/tokens/<int:token_id>", methods=["DELETE"])
@_require_session_auth
def api_tokens_revoke(token_id):
    """Revoke an API token. Session-only (no token auth)."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "Storage not available"}), 500
    revoked = _storage.revoke_api_token(token_id)
    if not revoked:
        return jsonify({"error": "Token not found or already revoked"}), 404
    audit_log.info("API token revoked: id=%s ip=%s", token_id, _get_client_ip())
    return jsonify({"success": True})


@config_bp.route("/api/demo/migrate", methods=["POST"])
@require_auth
def api_demo_migrate():
    """Switch from demo to live mode. Removes demo data, keeps user data."""
    _config_manager = get_config_manager()
    _storage = get_storage()
    if not _config_manager or not _config_manager.is_demo_mode():
        return jsonify({"success": False, "error": "Not in demo mode"}), 400
    if not _storage:
        return jsonify({"success": False, "error": "Storage not initialized"}), 500
    try:
        purged = _storage.purge_demo_data()
        _config_manager.save({"demo_mode": False})
        _storage.max_days = _config_manager.get("history_days", 7)
        audit_log.info("Demo migration: ip=%s purged=%d rows", _get_client_ip(), purged)
        _on_config_changed = get_on_config_changed()
        if _on_config_changed:
            _on_config_changed()
        return jsonify({"success": True, "purged": purged})
    except Exception as e:
        log.error("Demo migration failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
