"""Flask web UI for DOCSIS channel monitoring."""

import logging
import time
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, redirect

from .config import POLL_MIN, POLL_MAX, PASSWORD_MASK, SECRET_KEYS

log = logging.getLogger("docsis.web")

app = Flask(__name__, template_folder="templates")

# Shared state (updated from main loop)
_state = {
    "analysis": None,
    "last_update": None,
    "poll_interval": 300,
    "error": None,
}

_storage = None
_config_manager = None
_on_config_changed = None


def init_storage(storage):
    """Set the snapshot storage instance."""
    global _storage
    _storage = storage


def init_config(config_manager, on_config_changed=None):
    """Set the config manager and optional change callback."""
    global _config_manager, _on_config_changed
    _config_manager = config_manager
    _on_config_changed = on_config_changed


def update_state(analysis=None, error=None, poll_interval=None):
    """Update the shared web state from the main loop."""
    if analysis is not None:
        _state["analysis"] = analysis
        _state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _state["error"] = None
    if error is not None:
        _state["error"] = str(error)
    if poll_interval is not None:
        _state["poll_interval"] = poll_interval


@app.route("/")
def index():
    if _config_manager and not _config_manager.is_configured():
        return redirect("/setup")

    theme = _config_manager.get_theme() if _config_manager else "dark"

    ts = request.args.get("t")
    if ts and _storage:
        snapshot = _storage.get_snapshot(ts)
        if snapshot:
            return render_template(
                "index.html",
                analysis=snapshot,
                last_update=ts.replace("T", " "),
                poll_interval=_state["poll_interval"],
                error=None,
                historical=True,
                snapshot_ts=ts,
                theme=theme,
            )
    return render_template(
        "index.html",
        analysis=_state["analysis"],
        last_update=_state["last_update"],
        poll_interval=_state["poll_interval"],
        error=_state["error"],
        historical=False,
        snapshot_ts=None,
        theme=theme,
    )


@app.route("/setup")
def setup():
    if _config_manager and _config_manager.is_configured():
        return redirect("/")
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    return render_template("setup.html", config=config, poll_min=POLL_MIN, poll_max=POLL_MAX)


@app.route("/settings")
def settings():
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    theme = _config_manager.get_theme() if _config_manager else "dark"
    return render_template("settings.html", config=config, theme=theme, poll_min=POLL_MIN, poll_max=POLL_MAX)


@app.route("/api/config", methods=["POST"])
def api_config():
    """Save configuration."""
    if not _config_manager:
        return jsonify({"success": False, "error": "Config not initialized"}), 500
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data"}), 400
        # Clamp poll_interval to allowed range
        if "poll_interval" in data:
            try:
                pi = int(data["poll_interval"])
                data["poll_interval"] = max(POLL_MIN, min(POLL_MAX, pi))
            except (ValueError, TypeError):
                pass
        _config_manager.save(data)
        if _on_config_changed:
            _on_config_changed()
        return jsonify({"success": True})
    except Exception as e:
        log.error("Config save failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/test-fritz", methods=["POST"])
def api_test_fritz():
    """Test FritzBox connection."""
    try:
        data = request.get_json()
        # Resolve masked passwords to real values
        password = data.get("fritz_password", "")
        if password == PASSWORD_MASK and _config_manager:
            password = _config_manager.get("fritz_password", "")
        from . import fritzbox
        sid = fritzbox.login(
            data.get("fritz_url", "http://192.168.178.1"),
            data.get("fritz_user", ""),
            password,
        )
        info = fritzbox.get_device_info(data.get("fritz_url"), sid)
        return jsonify({"success": True, "model": info.get("model", "OK")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/test-mqtt", methods=["POST"])
def api_test_mqtt():
    """Test MQTT broker connection."""
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
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/calendar")
def api_calendar():
    """Return dates that have snapshot data."""
    if _storage:
        return jsonify(_storage.get_dates_with_data())
    return jsonify([])


@app.route("/api/snapshot/daily")
def api_snapshot_daily():
    """Return the daily snapshot closest to the configured snapshot_time."""
    date = request.args.get("date")
    if not date or not _storage:
        return jsonify(None)
    target_time = _config_manager.get("snapshot_time", "06:00") if _config_manager else "06:00"
    snap = _storage.get_daily_snapshot(date, target_time)
    return jsonify(snap)


@app.route("/api/trends")
def api_trends():
    """Return trend data for a date range.
    ?range=day|week|month&date=YYYY-MM-DD (date defaults to today)."""
    if not _storage:
        return jsonify([])
    range_type = request.args.get("range", "day")
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    target_time = _config_manager.get("snapshot_time", "06:00") if _config_manager else "06:00"

    try:
        ref_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    if range_type == "day":
        # All snapshots for a single day (intraday)
        return jsonify(_storage.get_intraday_data(date_str))
    elif range_type == "week":
        start = (ref_date - timedelta(days=ref_date.weekday())).strftime("%Y-%m-%d")
        end = (ref_date + timedelta(days=6 - ref_date.weekday())).strftime("%Y-%m-%d")
        return jsonify(_storage.get_trend_data(start, end, target_time))
    elif range_type == "month":
        start = ref_date.replace(day=1).strftime("%Y-%m-%d")
        if ref_date.month == 12:
            end = ref_date.replace(year=ref_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = ref_date.replace(month=ref_date.month + 1, day=1) - timedelta(days=1)
        return jsonify(_storage.get_trend_data(start, end.strftime("%Y-%m-%d"), target_time))
    else:
        return jsonify({"error": "Invalid range (use day, week, month)"}), 400


@app.route("/api/snapshots")
def api_snapshots():
    """Return list of available snapshot timestamps."""
    if _storage:
        return jsonify(_storage.get_snapshot_list())
    return jsonify([])


@app.route("/health")
def health():
    """Simple health check endpoint."""
    if _state["analysis"]:
        return {"status": "ok", "docsis_health": _state["analysis"]["summary"]["health"]}
    return {"status": "waiting"}, 503
