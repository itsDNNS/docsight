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
        from app.drivers import load_driver
        modem_type = data.get("modem_type", "fritzbox")
        driver = load_driver(
            modem_type,
            data.get("modem_url", "http://192.168.178.1"),
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
    dispatcher = NotificationDispatcher(_config_manager)
    result = dispatcher.test()
    return jsonify(result)


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
