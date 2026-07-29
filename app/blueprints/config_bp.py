"""Configuration and API token management routes."""

import logging
import os
import threading
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify

from app.web import (
    require_auth, _require_session_auth, _admin_password_matches,
    _invalidate_admin_sessions, _secret_values_match,
    get_config_manager, get_storage, get_on_config_changed,
    get_runtime_controller,
    _get_client_ip, _localize_timestamps,
)
from app.config import (
    PASSWORD_MASK,
    POLL_MAX,
    POLL_MIN,
)
from app.drivers import driver_registry

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web")

config_bp = Blueprint("config_bp", __name__)
_fallback_runtime_lock = threading.RLock()
_MODEM_CONNECTION_KEYS = {
    "modem_type",
    "modem_url",
    "modem_user",
    "modem_password",
}
_BQM_INITIAL_FETCH_FAILURE = {
    "success": False,
    "error": "BQM initial fetch failed; configuration was saved",
}


def _runtime_lock():
    """Return the shared runtime transaction boundary."""
    runtime = get_runtime_controller()
    return runtime.transaction_lock if runtime else _fallback_runtime_lock


def _normalized_origin(value):
    try:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port
    except (TypeError, ValueError):
        return None


def _request_authority():
    """Return the Host authority without trusting proxy-only scheme headers."""
    try:
        parsed = urlparse(f"//{request.host}")
        if not parsed.hostname or parsed.username or parsed.password:
            return None
        return parsed.hostname.lower(), parsed.port
    except (TypeError, ValueError):
        return None


def _origin_matches_request_authority(origin):
    """Compare browser authority while tolerating an internal HTTP scheme."""
    normalized = _normalized_origin(origin)
    authority = _request_authority()
    if not normalized or not authority:
        return False

    scheme, origin_host, origin_port = normalized
    request_host, request_port = authority
    if origin_host != request_host:
        return False
    if origin_port == request_port:
        return True

    browser_default_port = 443 if scheme == "https" else 80
    return (
        origin_port is None
        and request_port == browser_default_port
    ) or (
        request_port is None
        and origin_port == browser_default_port
    )


def _reject_cross_origin_browser_request():
    """Reject browser cross-origin mutations while allowing local API clients."""
    fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    origin = request.headers.get("Origin", "").strip()

    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        return jsonify({"success": False, "error": "Cross-origin request rejected"}), 403

    if origin:
        if not _origin_matches_request_authority(origin):
            return jsonify({"success": False, "error": "Cross-origin request rejected"}), 403
    elif fetch_site == "same-site":
        # Browser same-site requests can still cross origins (for example ports).
        return jsonify({"success": False, "error": "Cross-origin request rejected"}), 403

    return None


def _rollback_config(config_manager, snapshot, on_config_changed):
    """Restore persisted config and reapply the previous runtime state."""
    try:
        config_manager.restore(snapshot)
    except Exception:
        log.exception("Config rollback persistence failed")
        return
    if on_config_changed:
        try:
            on_config_changed()
        except Exception:
            log.exception("Config rollback runtime apply failed")


def _should_run_bqm_initial_fetch(url):
    """Return True only for ThinkBroadband share URLs safe for immediate setup fetch."""
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    return (
        parsed.scheme == "https"
        and host in {"thinkbroadband.com", "www.thinkbroadband.com"}
        and path.startswith("/broadband/monitoring/quality/share/")
        and path.endswith(".csv")
    )


def run_bqm_initial_fetch(config_manager=None, storage=None):
    """Lazy wrapper to avoid importing optional BQM routes during blueprint setup."""
    from app.modules.bqm.routes import run_bqm_initial_fetch as _run_bqm_initial_fetch

    return _run_bqm_initial_fetch(config_manager, storage)


@config_bp.route("/api/config", methods=["POST"])
@_require_session_auth
def api_config():
    """Save configuration."""
    cross_origin = _reject_cross_origin_browser_request()
    if cross_origin:
        return cross_origin
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify({"success": False, "error": "Config not initialized"}), 500
    with _runtime_lock():
        try:
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "No data"}), 400
            data = dict(data)
            previous_admin_password = _config_manager.get("admin_password", "")
            admin_password_requested = "admin_password" in data
            if admin_password_requested and (
                data["admin_password"] == PASSWORD_MASK
                or _admin_password_matches(previous_admin_password, data["admin_password"])
            ):
                del data["admin_password"]
            if (
                _config_manager.is_demo_mode()
                and _MODEM_CONNECTION_KEYS.intersection(data)
            ):
                return jsonify({
                    "success": False,
                    "error": (
                        "Modem connection settings cannot be changed "
                        "while Demo Mode is active"
                    ),
                }), 409
            # Validate timezone if provided
            if "timezone" in data and data["timezone"]:
                try:
                    ZoneInfo(data["timezone"])
                except Exception:
                    return jsonify({"success": False, "error": "Invalid timezone"}), 400
            if "modem_type" in data and (
                not isinstance(data["modem_type"], str)
                or not driver_registry.has_driver(data["modem_type"])
            ):
                supported = ", ".join(
                    sorted(driver_registry.get_all_type_keys())
                )
                return jsonify({
                    "success": False,
                    "error": f"Unknown modem_type. Supported: {supported}",
                }), 400
            # Clamp poll_interval to allowed range
            if "poll_interval" in data:
                try:
                    pi = int(data["poll_interval"])
                    data["poll_interval"] = max(POLL_MIN, min(POLL_MAX, pi))
                except (ValueError, TypeError):
                    pass
            previous_bqm_url = (_config_manager.get("bqm_url") or "").strip()
            requested_bqm_url = (
                (data.get("bqm_url") or "").strip()
                if "bqm_url" in data
                else previous_bqm_url
            )
            should_fetch_bqm = (
                bool(requested_bqm_url)
                and requested_bqm_url != previous_bqm_url
                and _should_run_bqm_initial_fetch(requested_bqm_url)
            )
            snapshot = _config_manager.snapshot()
            _on_config_changed = get_on_config_changed()
            try:
                _config_manager.save(data)
            except ValueError:
                # ConfigManager validates URL schemes before mutating either
                # in-memory or persisted state.
                return jsonify({
                    "success": False,
                    "error": (
                        "Configuration URLs must use HTTP or HTTPS."
                    ),
                }), 400
            except Exception:
                _rollback_config(
                    _config_manager, snapshot, _on_config_changed
                )
                raise
            try:
                if _on_config_changed:
                    _on_config_changed()
            except Exception:
                _rollback_config(
                    _config_manager, snapshot, _on_config_changed
                )
                raise

            response = {"success": True}
            if should_fetch_bqm:
                try:
                    fetch_result = run_bqm_initial_fetch(
                        _config_manager, get_storage()
                    )
                except Exception:
                    log.exception(
                        "Optional BQM initial fetch raised after config commit"
                    )
                    fetch_result = None
                if (
                    isinstance(fetch_result, dict)
                    and fetch_result.get("success") is True
                ):
                    response["bqm_initial_fetch"] = fetch_result
                else:
                    if fetch_result is not None:
                        log.warning(
                            "Optional BQM initial fetch reported failure "
                            "after config commit"
                        )
                    response["bqm_initial_fetch"] = dict(
                        _BQM_INITIAL_FETCH_FAILURE
                    )

            effective_admin_password = _config_manager.get("admin_password", "")
            admin_password_changed = (
                admin_password_requested
                and not _secret_values_match(
                    previous_admin_password, effective_admin_password
                )
            )
            if admin_password_changed:
                _invalidate_admin_sessions()
            audit_log.info("Config changed: ip=%s", _get_client_ip())
            return jsonify(response)
        except Exception:
            log.exception("Config save failed")
            return jsonify({"success": False, "error": "Config save failed"}), 500


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


@config_bp.route("/api/demo/start", methods=["POST"])
@_require_session_auth
def api_demo_start():
    """Enable Demo Mode on a truly unconfigured instance."""
    cross_origin = _reject_cross_origin_browser_request()
    if cross_origin:
        return cross_origin
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify({"success": False, "error": "Config not initialized"}), 500
    with _runtime_lock():
        if not _config_manager.is_demo_mode() and _config_manager.is_configured():
            return jsonify({
                "success": False,
                "error": "Demo Mode can only be started before modem setup",
            }), 409

        snapshot = _config_manager.snapshot()
        _on_config_changed = get_on_config_changed()
        try:
            if not _config_manager.is_demo_mode():
                _config_manager.save({"demo_mode": True})
            if _on_config_changed:
                _on_config_changed()
            audit_log.info("First-run demo started: ip=%s", _get_client_ip())
            return jsonify({"success": True})
        except Exception:
            log.exception("Demo start failed")
            _rollback_config(_config_manager, snapshot, _on_config_changed)
            return jsonify({"success": False, "error": "Demo start failed"}), 500


@config_bp.route("/api/demo/migrate", methods=["POST"])
@require_auth
def api_demo_migrate():
    """Switch from demo to live mode. Removes demo data, keeps user data."""
    cross_origin = _reject_cross_origin_browser_request()
    if cross_origin:
        return cross_origin
    _config_manager = get_config_manager()
    _storage = get_storage()
    if not _config_manager:
        return jsonify({"success": False, "error": "Config not initialized"}), 500
    action = (request.get_json(silent=True) or {}).get("action", "exit")
    next_paths = {
        "connect": "/setup?connect=1",
        "exit": "/setup",
    }
    if action not in next_paths:
        return jsonify({"success": False, "error": "Invalid demo exit action"}), 400
    with _runtime_lock():
        if not _config_manager.is_demo_mode():
            return jsonify({"success": False, "error": "Not in demo mode"}), 400
        if _config_manager.is_demo_mode_forced():
            return jsonify({
                "success": False,
                "error": "Demo Mode is managed by deployment configuration",
            }), 409
        if not _storage:
            return jsonify({"success": False, "error": "Storage not initialized"}), 500

        _on_config_changed = get_on_config_changed()
        runtime = get_runtime_controller()
        if (runtime is None) != (_on_config_changed is None):
            log.error(
                "Demo migration refused: runtime controller/config callback mismatch"
            )
            return jsonify({
                "success": False,
                "error": "Demo exit failed",
            }), 500

        snapshot = _config_manager.snapshot()
        try:
            # Stop the active demo runtime independently of persisted modem
            # settings. Legacy installs may contain both demo and modem config.
            if runtime:
                if not runtime.quiesce(timeout=runtime.stop_timeout):
                    raise TimeoutError(
                        "Demo polling did not stop before destructive cleanup"
                    )

            _config_manager.save({"demo_mode": False})
            if _on_config_changed:
                _on_config_changed()
            purged = _storage.purge_demo_data()
            from app.modules.connection_monitor.storage import ConnectionMonitorStorage
            cm_db_path = os.path.join(_config_manager.data_dir, "connection_monitor.db")
            if os.path.exists(cm_db_path):
                cm_storage = ConnectionMonitorStorage(cm_db_path)
                from app.collectors.demo import (
                    DEMO_CONNECTION_MONITOR_DAYS,
                    DEMO_CONNECTION_MONITOR_INTERVAL_SECONDS,
                    DEMO_CONNECTION_MONITOR_TARGETS,
                )
                cm_storage.backfill_legacy_demo_provenance(
                    DEMO_CONNECTION_MONITOR_TARGETS,
                    expected_sample_count=(
                        DEMO_CONNECTION_MONITOR_DAYS
                        * 86400
                        // DEMO_CONNECTION_MONITOR_INTERVAL_SECONDS
                    ),
                    interval_seconds=DEMO_CONNECTION_MONITOR_INTERVAL_SECONDS,
                )
                purged += cm_storage.purge_demo_data()
            _storage.max_days = _config_manager.get("history_days", 7)
            audit_log.info("Demo migration: ip=%s purged=%d rows", _get_client_ip(), purged)
            return jsonify({
                "success": True,
                "purged": purged,
                "next_path": next_paths[action],
            })
        except Exception:
            log.exception("Demo migration failed")
            _rollback_config(_config_manager, snapshot, _on_config_changed)
            return jsonify({"success": False, "error": "Demo exit failed"}), 500
