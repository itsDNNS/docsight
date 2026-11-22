"""Polling and connectivity test routes."""

from app.runtime import current_runtime
from app.web_locale import get_lang
import logging
import threading
import time

from flask import Blueprint, request, jsonify

from app.web_auth import require_auth
from app.config import PASSWORD_MASK, parse_config_bool, parse_config_int
from app import modem_diagnosis
from app.i18n import get_translations
from app.modules.mqtt.publisher import create_client
from paho.mqtt.client import MQTT_ERR_SUCCESS
from app.modules.speedtest.client import SpeedtestClient, is_finished, public_error

log = logging.getLogger("docsis.web")

polling_bp = Blueprint("polling_bp", __name__)


def _object(value):
    """A JSON object from the request, or an empty one for any other value."""
    return value if isinstance(value, dict) else {}


def _pwa_push_configured(config_mgr):
    return bool(
        config_mgr.get("notify_pwa_push_enabled")
        and config_mgr.get("notify_pwa_push_vapid_public_key")
        and config_mgr.get("notify_pwa_push_vapid_private_key")
    )


def _resolve_masked_secret(value, secret_key, submitted, saved):
    """Swap a masked secret for the saved one, but only for the saved destination.

    ``saved`` returns the saved destination, including its TLS policy; it is only
    read when a saved secret would be reused. Returns (secret, error).
    """
    if value != PASSWORD_MASK:
        return value, None
    config = current_runtime().config_manager
    with config.locked():  # secret and destination from the same saved state
        stored = config.get(secret_key) or None
        if not stored:
            return None, None
        try:
            matches = submitted == saved()
        except (TypeError, ValueError, OverflowError):
            matches = False
    if not matches:
        return None, "Enter the password to test changed connection settings."
    return stored, None


@polling_bp.route("/api/test-modem", methods=["POST"])
@polling_bp.route("/api/test-fritz", methods=["POST"])  # deprecated alias
@require_auth
def api_test_modem():
    """Test modem connection."""
    _config_manager = current_runtime().config_manager
    from app.drivers import get_driver_registry
    driver_registry = get_driver_registry()
    modem_type = "fritzbox"
    modem_url = "http://192.168.100.1"
    stage = "load"
    try:
        data = request.get_json()
        modem_type = data.get("modem_type", "fritzbox")
        password, error = _resolve_masked_secret(
            data.get("modem_password", ""), "modem_password",
            (modem_type, data.get("modem_url") or "", data.get("modem_user") or ""),
            # An empty saved URL never matches: the test would fall back to a default address.
            lambda: (_config_manager.get("modem_type"), _config_manager.get("modem_url") or None,
                     _config_manager.get("modem_user") or ""),
        )
        if error:
            return jsonify({"success": False, "error": error})
        password = password or ""
        modem_url = data.get("modem_url") or modem_url
        driver = driver_registry.load_driver(
            modem_type,
            modem_url,
            data.get("modem_user", ""),
            password,
        )
        stage = "login"
        driver.login()
        stage = "read"
        info = driver.get_device_info()
        return jsonify({"success": True, "model": info.get("model", "OK")})
    except Exception as exc:
        # A login that failed against a silent address is a reachability problem,
        # whatever the driver's message says.
        if stage == "login" and not modem_diagnosis.host_reachable(modem_url):
            reason = modem_diagnosis.UNREACHABLE
        else:
            reason = modem_diagnosis.classify_failure(exc, stage)
        log.warning("Modem test failed (%s)", reason)
        error = ("Community modem connection failed" if not driver_registry.is_builtin(modem_type)
                 else "Modem connection failed")
        return jsonify({"success": False, "error": error, "reason": reason,
                        "help_url": modem_diagnosis.HELP_URLS[reason]})


@polling_bp.route("/api/setup/detect-modem", methods=["POST"])
@require_auth
def api_detect_modem():
    """Look for a modem at a few common local addresses.

    Runs only when the user asks for it. The addresses are fixed; the request
    carries no input, so it cannot be pointed at other hosts.
    """
    from app.drivers import get_driver_registry
    from app.modem_detect import detect_modems
    known = get_driver_registry().get_all_type_keys()
    return jsonify({"devices": detect_modems(known_drivers=known)})


MQTT_ANSWER_SECONDS = 5


@polling_bp.route("/api/test-mqtt", methods=["POST"])
@require_auth
def api_test_mqtt():
    """Test the MQTT broker connection, including the broker's answer to the login."""
    _config_manager = current_runtime().config_manager
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "No data"}), 400
    host = data.get("mqtt_host") or "localhost"
    user = data.get("mqtt_user") or None
    try:
        port = parse_config_int(data.get("mqtt_port") or 1883)
    except (TypeError, ValueError, OverflowError):
        port = 0
    if not (isinstance(host, str) and isinstance(user, (str, type(None))) and 0 < port < 65536):
        return jsonify({"success": False, "error": "Invalid broker settings"}), 400
    tls_insecure = parse_config_bool(data.get("mqtt_tls_insecure"))
    password, error = _resolve_masked_secret(
        data.get("mqtt_password") or None, "mqtt_password", (host, port, user, tls_insecure),
        lambda: (_config_manager.get("mqtt_host"), parse_config_int(_config_manager.get("mqtt_port")),
                 _config_manager.get("mqtt_user") or None, parse_config_bool(_config_manager.get("mqtt_tls_insecure"))),
    )
    if error:
        return jsonify({"success": False, "error": error})
    connack = threading.Event()
    answer = {}

    def on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        answer["reason"] = reason_code
        connack.set()

    client, started = None, False
    try:
        client = create_client("docsis-test", port, user, password, tls_insecure)
        client.on_connect = on_connect
        client.connect(host, port)
        started = client.loop_start() == MQTT_ERR_SUCCESS
        if not started or not connack.wait(MQTT_ANSWER_SECONDS):
            return jsonify({"success": False, "error": "MQTT broker did not answer"})
        if answer["reason"].is_failure:
            return jsonify({"success": False, "error": f"MQTT broker refused the connection: {answer['reason']}"})
        return jsonify({"success": True})
    except (OSError, ValueError) as exc:
        log.warning("MQTT test failed (%s)", type(exc).__name__)
        return jsonify({"success": False, "error": "Cannot reach MQTT broker"})
    except Exception:
        log.exception("MQTT test failed")
        return jsonify({"success": False, "error": "MQTT test failed, see the DOCSight log"})
    finally:
        try:
            if client is not None:
                client.disconnect()  # before joining, so the network loop stops instead of reconnecting
        finally:
            if started:
                client.loop_stop()


@polling_bp.route("/api/notifications/test", methods=["POST"])
@require_auth
def api_notifications_test():
    """Send a test notification to all configured channels."""
    _config_manager = current_runtime().config_manager
    if not _config_manager.is_notify_configured():
        return jsonify({"success": False, "error": "Notifications not configured"}), 400
    from app.notifier import NotificationDispatcher
    dispatcher = NotificationDispatcher(_config_manager, storage=current_runtime().storage)
    result = dispatcher.test()
    return jsonify(result)


@polling_bp.route("/api/notifications/pwa/status", methods=["GET"])
@require_auth
def api_pwa_push_status():
    """Return browser Push API readiness without exposing private VAPID material."""
    _config_manager = current_runtime().config_manager
    storage = current_runtime().storage
    configured = _pwa_push_configured(_config_manager)
    public_key = ""
    if _config_manager.get("notify_pwa_push_enabled"):
        public_key = _config_manager.get("notify_pwa_push_vapid_public_key") or ""
    count = storage.count_pwa_push_subscriptions() if storage else 0
    return jsonify({
        "enabled": bool(_config_manager.get("notify_pwa_push_enabled")),
        "configured": configured,
        "public_key": public_key if configured else "",
        "subscription_count": count,
    })


@polling_bp.route("/api/notifications/pwa/subscribe", methods=["POST"])
@require_auth
def api_pwa_push_subscribe():
    """Persist the current browser's Push API subscription."""
    storage = current_runtime().storage
    if not storage:
        return jsonify({"success": False, "error": "Storage unavailable"}), 503
    data = _object(request.get_json(silent=True))
    try:
        record = storage.upsert_pwa_push_subscription(
            data.get("subscription") or data,
            user_agent=request.headers.get("User-Agent", "")[:500],
        )
    except ValueError:
        return jsonify({"success": False, "error": "Invalid Web Push subscription"}), 400
    return jsonify({"success": True, "subscription_count": storage.count_pwa_push_subscriptions(), "id": record["id"]})


@polling_bp.route("/api/notifications/pwa/unsubscribe", methods=["POST"])
@require_auth
def api_pwa_push_unsubscribe():
    """Remove the current browser's Push API subscription by endpoint."""
    storage = current_runtime().storage
    if not storage:
        return jsonify({"success": False, "error": "Storage unavailable"}), 503
    data = _object(request.get_json(silent=True))
    endpoint = data.get("endpoint") or _object(data.get("subscription")).get("endpoint")
    if not endpoint:
        return jsonify({"success": False, "error": "Subscription endpoint is required"}), 400
    storage.delete_pwa_push_subscription(endpoint)
    return jsonify({"success": True, "subscription_count": storage.count_pwa_push_subscriptions()})


@polling_bp.route("/api/test-speedtest", methods=["POST"])
@require_auth
def api_test_speedtest():
    """Test Speedtest Tracker connection."""
    _config_manager = current_runtime().config_manager
    try:
        data = request.get_json(silent=True) or {}
        submitted_url = data.get("speedtest_tracker_url", "")
        tls_insecure = parse_config_bool(data.get("speedtest_tls_insecure", False))
        if not submitted_url:
            return jsonify({"success": False, "error": "URL and token are required"})

        with _config_manager.locked():  # URL, token and TLS policy from the same saved state
            saved_url = _config_manager.get("speedtest_tracker_url", "")
            token = _config_manager.get("speedtest_tracker_token", "")
            saved_tls_insecure = parse_config_bool(_config_manager.get("speedtest_tls_insecure", False))
        if not saved_url or submitted_url.rstrip("/") != saved_url.rstrip("/") or tls_insecure != saved_tls_insecure:
            return jsonify({
                "success": False,
                "error": "Save Speedtest Tracker settings before testing.",
            })
        if not token:
            return jsonify({"success": False, "error": "URL and token are required"})

        client = SpeedtestClient(saved_url, token, tls_insecure=tls_insecure)
        results, error = client.get_latest_with_error(1)
        if error:
            return jsonify({"success": False, "error": error})
        if results and is_finished(results[0]):
            r = results[0]
            return jsonify({
                "success": True,
                "results": len(results),
                "latest": {
                    "download": r.get("download_human") or f"{r.get('download_mbps') or 0} Mbps",
                    "upload": r.get("upload_human") or f"{r.get('upload_mbps') or 0} Mbps",
                    "ping": f"{r.get('ping_ms', 0)} ms",
                },
            })
        return jsonify({"success": True, "results": 0})
    except Exception as exc:
        log.warning("Speedtest Tracker test failed (%s)", type(exc).__name__)
        return jsonify({"success": False, "error": public_error(exc)})


@polling_bp.route("/api/poll", methods=["POST"])
@require_auth(token_writes=True)
def api_poll():
    """Trigger an immediate modem poll via ModemCollector.

    Uses the same collector instance as automatic polling to ensure
    consistent behavior and fail-safe application.
    Uses _collect_lock to prevent collision with parallel auto-poll.
    """
    _modem_collector = current_runtime().modem_collector

    if not _modem_collector:
        return jsonify({"success": False, "error": "Collector not initialized"}), 500

    now = time.time()
    if now - current_runtime().get_last_manual_poll() < 10:
        lang = get_lang()
        t = get_translations(lang)
        return jsonify({"success": False, "error": t["refresh_rate_limit"]}), 429

    if not _modem_collector._collect_lock.acquire(timeout=0):
        return jsonify({"success": False, "error": "Poll already in progress"}), 429

    try:
        result = _modem_collector.collect()

        if not result.success:
            log.warning("Manual poll failed: %s", result.error)
            return jsonify({"success": False, "error": "Modem reading failed, see the DOCSight log"}), 500

        current_runtime().set_last_manual_poll(time.time())

        # Return the analysis data from the collector result
        # (ModemCollector already updated web state and saved snapshot)
        return jsonify({"success": True, "analysis": result.data})

    except Exception as exc:
        log.exception("Manual poll failed")
        return jsonify({"success": False, "error": modem_diagnosis.public_message(exc)}), 500
    finally:
        _modem_collector._collect_lock.release()


@polling_bp.route("/api/collectors/status")
@require_auth
def api_collectors_status():
    """Return health status of all collectors.

    Provides monitoring info: failure counts, penalties, next poll times.
    Useful for debugging collector issues and fail-safe behavior.
    """
    _collectors = current_runtime().collectors
    if not _collectors:
        return jsonify([])

    return jsonify([c.get_status() for c in _collectors])
