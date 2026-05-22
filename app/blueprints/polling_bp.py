"""Polling and connectivity test routes."""

import logging
import time

from flask import Blueprint, request, jsonify

from app.web import (
    require_auth,
    get_config_manager, get_storage, get_modem_collector, get_collectors,
    get_last_manual_poll, set_last_manual_poll,
    _get_lang,
)
from app.config import PASSWORD_MASK
from app.i18n import get_translations

log = logging.getLogger("docsis.web")

polling_bp = Blueprint("polling_bp", __name__)


def _valid_push_subscription(subscription):
    if not isinstance(subscription, dict):
        return False
    if not str(subscription.get("endpoint") or "").strip():
        return False
    keys = subscription.get("keys") or {}
    return isinstance(keys, dict) and bool(keys.get("p256dh")) and bool(keys.get("auth"))


def _pwa_push_configured(config_mgr):
    return bool(
        config_mgr
        and config_mgr.get("notify_pwa_push_enabled")
        and config_mgr.get("notify_pwa_push_vapid_public_key")
        and config_mgr.get("notify_pwa_push_vapid_private_key")
    )


def _as_bool(value):
    """Parse booleans from JSON/form payloads."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@polling_bp.route("/api/test-modem", methods=["POST"])
@polling_bp.route("/api/test-fritz", methods=["POST"])  # deprecated alias
@require_auth
def api_test_modem():
    """Test modem connection."""
    _config_manager = get_config_manager()
    try:
        data = request.get_json()
        # Resolve masked passwords to real values
        password = data.get("modem_password", "")
        if password == PASSWORD_MASK and _config_manager:
            password = _config_manager.get("modem_password", "")
        from app.drivers import driver_registry
        modem_type = data.get("modem_type", "fritzbox")
        driver = driver_registry.load_driver(
            modem_type,
            data.get("modem_url") or "http://192.168.100.1",
            data.get("modem_user", ""),
            password,
        )
        driver.login()
        info = driver.get_device_info()
        return jsonify({"success": True, "model": info.get("model", "OK")})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)})
    except Exception as e:
        log.warning("Modem test failed: %s", e)
        return jsonify({"success": False, "error": type(e).__name__ + ": " + str(e).split("\n")[0][:200]})


@polling_bp.route("/api/test-mqtt", methods=["POST"])
@require_auth
def api_test_mqtt():
    """Test MQTT broker connection."""
    _config_manager = get_config_manager()
    try:
        data = request.get_json()
        # Resolve masked passwords to real values
        pw = data.get("mqtt_password", "") or None
        if pw == PASSWORD_MASK and _config_manager:
            pw = _config_manager.get("mqtt_password", "") or None
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="docsis-test")
        user = data.get("mqtt_user", "") or None
        if user:
            client.username_pw_set(user, pw)
        port = int(data.get("mqtt_port", 1883))
        client.connect(data.get("mqtt_host", "localhost"), port, 5)
        client.disconnect()
        return jsonify({"success": True})
    except Exception as e:
        log.warning("MQTT test failed: %s", e)
        return jsonify({"success": False, "error": type(e).__name__ + ": " + str(e).split("\n")[0][:200]})


@polling_bp.route("/api/notifications/test", methods=["POST"])
@require_auth
def api_notifications_test():
    """Send a test notification to all configured channels."""
    _config_manager = get_config_manager()
    if not _config_manager or not _config_manager.is_notify_configured():
        return jsonify({"success": False, "error": "Notifications not configured"}), 400
    from app.notifier import NotificationDispatcher
    dispatcher = NotificationDispatcher(_config_manager, storage=get_storage())
    result = dispatcher.test()
    return jsonify(result)


@polling_bp.route("/api/notifications/pwa/status", methods=["GET"])
@require_auth
def api_pwa_push_status():
    """Return browser Push API readiness without exposing private VAPID material."""
    _config_manager = get_config_manager()
    storage = get_storage()
    configured = _pwa_push_configured(_config_manager)
    public_key = ""
    if _config_manager and _config_manager.get("notify_pwa_push_enabled"):
        public_key = _config_manager.get("notify_pwa_push_vapid_public_key") or ""
    count = storage.count_pwa_push_subscriptions() if storage else 0
    return jsonify({
        "enabled": bool(_config_manager and _config_manager.get("notify_pwa_push_enabled")),
        "configured": configured,
        "public_key": public_key if configured else "",
        "subscription_count": count,
    })


@polling_bp.route("/api/notifications/pwa/subscribe", methods=["POST"])
@require_auth
def api_pwa_push_subscribe():
    """Persist the current browser's Push API subscription."""
    storage = get_storage()
    if not storage:
        return jsonify({"success": False, "error": "Storage unavailable"}), 503
    data = request.get_json(silent=True) or {}
    subscription = data.get("subscription") or data
    if not _valid_push_subscription(subscription):
        return jsonify({"success": False, "error": "Invalid Web Push subscription"}), 400
    try:
        record = storage.upsert_pwa_push_subscription(
            subscription,
            user_agent=request.headers.get("User-Agent", "")[:500],
        )
    except ValueError:
        return jsonify({"success": False, "error": "Invalid Web Push subscription"}), 400
    return jsonify({"success": True, "subscription_count": storage.count_pwa_push_subscriptions(), "id": record["id"]})


@polling_bp.route("/api/notifications/pwa/unsubscribe", methods=["POST"])
@require_auth
def api_pwa_push_unsubscribe():
    """Remove the current browser's Push API subscription by endpoint."""
    storage = get_storage()
    if not storage:
        return jsonify({"success": False, "error": "Storage unavailable"}), 503
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint") or (data.get("subscription") or {}).get("endpoint")
    if not endpoint:
        return jsonify({"success": False, "error": "Subscription endpoint is required"}), 400
    storage.delete_pwa_push_subscription(endpoint)
    return jsonify({"success": True, "subscription_count": storage.count_pwa_push_subscriptions()})


@polling_bp.route("/api/test-speedtest", methods=["POST"])
@require_auth
def api_test_speedtest():
    """Test Speedtest Tracker connection."""
    _config_manager = get_config_manager()
    try:
        data = request.get_json()
        url = data.get("speedtest_tracker_url", "")
        token = data.get("speedtest_tracker_token", "")
        tls_insecure = _as_bool(data.get("speedtest_tls_insecure", False))
        # Resolve masked token to real value
        if token == PASSWORD_MASK and _config_manager:
            token = _config_manager.get("speedtest_tracker_token", "")
        if not url or not token:
            return jsonify({"success": False, "error": "URL and token are required"})
        from app.modules.speedtest.client import SpeedtestClient
        client = SpeedtestClient(url, token, tls_insecure=tls_insecure)
        results, error = client.get_latest_with_error(1)
        if error:
            return jsonify({"success": False, "error": error})
        if results:
            r = results[0]
            return jsonify({
                "success": True,
                "results": len(results),
                "latest": {
                    "download": r.get("download_human") or f"{r.get('download_mbps', 0)} Mbps",
                    "upload": r.get("upload_human") or f"{r.get('upload_mbps', 0)} Mbps",
                    "ping": f"{r.get('ping_ms', 0)} ms",
                },
            })
        return jsonify({"success": True, "results": 0})
    except Exception as e:
        log.warning("Speedtest Tracker test failed: %s", e)
        return jsonify({"success": False, "error": type(e).__name__ + ": " + str(e).split("\n")[0][:200]})


@polling_bp.route("/api/poll", methods=["POST"])
@require_auth
def api_poll():
    """Trigger an immediate modem poll via ModemCollector.

    Uses the same collector instance as automatic polling to ensure
    consistent behavior and fail-safe application.
    Uses _collect_lock to prevent collision with parallel auto-poll.
    """
    _modem_collector = get_modem_collector()

    if not _modem_collector:
        return jsonify({"success": False, "error": "Collector not initialized"}), 500

    now = time.time()
    if now - get_last_manual_poll() < 10:
        lang = _get_lang()
        t = get_translations(lang)
        return jsonify({"success": False, "error": t.get("refresh_rate_limit", "Rate limited")}), 429

    if not _modem_collector._collect_lock.acquire(timeout=0):
        return jsonify({"success": False, "error": "Poll already in progress"}), 429

    try:
        result = _modem_collector.collect()

        if not result.success:
            return jsonify({"success": False, "error": result.error}), 500

        set_last_manual_poll(time.time())

        # Return the analysis data from the collector result
        # (ModemCollector already updated web state and saved snapshot)
        return jsonify({"success": True, "analysis": result.data})

    except Exception as e:
        log.error("Manual poll failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _modem_collector._collect_lock.release()


@polling_bp.route("/api/collectors/status")
@require_auth
def api_collectors_status():
    """Return health status of all collectors.

    Provides monitoring info: failure counts, penalties, next poll times.
    Useful for debugging collector issues and fail-safe behavior.
    """
    _collectors = get_collectors()
    if not _collectors:
        return jsonify([])

    return jsonify([c.get_status() for c in _collectors])
