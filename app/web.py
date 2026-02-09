"""Flask web UI for DOCSight – DOCSIS channel monitoring."""

import functools
import logging
import os
import re
import stat
import time
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from werkzeug.security import check_password_hash

from .config import POLL_MIN, POLL_MAX, PASSWORD_MASK, SECRET_KEYS
from .i18n import get_translations, LANGUAGES

def _server_tz_info():
    """Return server timezone name and UTC offset in minutes."""
    now = datetime.now().astimezone()
    name = now.strftime("%Z") or time.tzname[0] or "UTC"
    offset_min = int(now.utcoffset().total_seconds() // 60)
    return name, offset_min

log = logging.getLogger("docsis.web")

app = Flask(__name__, template_folder="templates")
app.secret_key = os.urandom(32)  # overwritten by _init_session_key

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.template_filter("fmt_k")
def format_k(value):
    """Format large numbers with k suffix: 132007 -> 132k, 5929 -> 5.9k."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return str(value)
    if value >= 100000:
        return f"{value // 1000}k"
    elif value >= 1000:
        formatted = f"{value / 1000:.1f}"
        if formatted.endswith(".0"):
            formatted = formatted[:-2]
        return formatted + "k"
    return str(value)


def _get_lang():
    """Get language from query param or config."""
    lang = request.args.get("lang")
    if lang and lang in LANGUAGES:
        return lang
    if _config_manager:
        return _config_manager.get("language", "en")
    return "en"

# Shared state (updated from main loop)
_state = {
    "analysis": None,
    "last_update": None,
    "poll_interval": 900,
    "error": None,
    "connection_info": None,
}

_storage = None
_config_manager = None
_on_config_changed = None


def init_storage(storage):
    """Set the snapshot storage instance."""
    global _storage
    _storage = storage


def _init_session_key(data_dir):
    """Load or generate a persistent session secret key."""
    key_path = os.path.join(data_dir, ".session_key")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            app.secret_key = f.read()
    else:
        key = os.urandom(32)
        os.makedirs(data_dir, exist_ok=True)
        with open(key_path, "wb") as f:
            f.write(key)
        try:
            os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        app.secret_key = key


def init_config(config_manager, on_config_changed=None):
    """Set the config manager and optional change callback."""
    global _config_manager, _on_config_changed
    _config_manager = config_manager
    _on_config_changed = on_config_changed
    _init_session_key(config_manager.data_dir)


def _auth_required():
    """Check if auth is enabled and user is not logged in."""
    if not _config_manager:
        return False
    admin_pw = _config_manager.get("admin_password", "")
    if not admin_pw:
        return False
    return not session.get("authenticated")


def require_auth(f):
    """Decorator: redirect to /login if auth is enabled and not logged in."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if _auth_required():
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _config_manager or not _config_manager.get("admin_password", ""):
        return redirect("/")
    lang = _get_lang()
    t = get_translations(lang)
    theme = _config_manager.get_theme() if _config_manager else "dark"
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        stored = _config_manager.get("admin_password", "")
        if stored.startswith(("scrypt:", "pbkdf2:")):
            success = check_password_hash(stored, pw)
        else:
            success = (pw == stored)  # legacy plaintext / env var
        if success:
            session["authenticated"] = True
            return redirect("/")
        error = t.get("login_failed", "Invalid password")
    return render_template("login.html", t=t, lang=lang, theme=theme, error=error)


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect("/login")


@app.context_processor
def inject_auth():
    """Make auth_enabled available in all templates."""
    auth_enabled = bool(_config_manager and _config_manager.get("admin_password", ""))
    return {"auth_enabled": auth_enabled}


def update_state(analysis=None, error=None, poll_interval=None, connection_info=None):
    """Update the shared web state from the main loop."""
    if analysis is not None:
        _state["analysis"] = analysis
        _state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _state["error"] = None
    if error is not None:
        _state["error"] = str(error)
    if poll_interval is not None:
        _state["poll_interval"] = poll_interval
    if connection_info is not None:
        _state["connection_info"] = connection_info


@app.route("/")
@require_auth
def index():
    if _config_manager and not _config_manager.is_configured():
        return redirect("/setup")

    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)

    isp_name = _config_manager.get("isp_name", "") if _config_manager else ""
    conn_info = _state.get("connection_info") or {}

    ts = request.args.get("t")
    if ts and not _TS_RE.match(ts):
        return redirect("/")
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
                isp_name=isp_name, connection_info=conn_info,
                t=t, lang=lang, languages=LANGUAGES,
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
        isp_name=isp_name, connection_info=conn_info,
        t=t, lang=lang, languages=LANGUAGES,
    )


@app.route("/setup")
def setup():
    if _config_manager and _config_manager.is_configured():
        return redirect("/")
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    return render_template("setup.html", config=config, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, server_tz=tz_name, server_tz_offset=tz_offset)


@app.route("/settings")
@require_auth
def settings():
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    return render_template("settings.html", config=config, theme=theme, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, server_tz=tz_name, server_tz_offset=tz_offset)


@app.route("/api/config", methods=["POST"])
@require_auth
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


@app.route("/api/test-modem", methods=["POST"])
@app.route("/api/test-fritz", methods=["POST"])  # deprecated alias
@require_auth
def api_test_modem():
    """Test modem connection."""
    try:
        data = request.get_json()
        # Resolve masked passwords to real values
        password = data.get("modem_password", "")
        if password == PASSWORD_MASK and _config_manager:
            password = _config_manager.get("modem_password", "")
        from . import fritzbox
        sid = fritzbox.login(
            data.get("modem_url", "http://192.168.178.1"),
            data.get("modem_user", ""),
            password,
        )
        info = fritzbox.get_device_info(data.get("modem_url"), sid)
        return jsonify({"success": True, "model": info.get("model", "OK")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/test-mqtt", methods=["POST"])
@require_auth
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
@require_auth
def api_calendar():
    """Return dates that have snapshot data."""
    if _storage:
        return jsonify(_storage.get_dates_with_data())
    return jsonify([])


@app.route("/api/snapshot/daily")
@require_auth
def api_snapshot_daily():
    """Return the daily snapshot closest to the configured snapshot_time."""
    date = request.args.get("date")
    if not date or not _storage:
        return jsonify(None)
    if not _DATE_RE.match(date):
        return jsonify({"error": "Invalid date format"}), 400
    target_time = _config_manager.get("snapshot_time", "06:00") if _config_manager else "06:00"
    snap = _storage.get_daily_snapshot(date, target_time)
    return jsonify(snap)


@app.route("/api/trends")
@require_auth
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


@app.route("/api/export")
@require_auth
def api_export():
    """Generate a structured markdown report for LLM analysis."""
    analysis = _state.get("analysis")
    if not analysis:
        return jsonify({"error": "No data available"}), 404

    s = analysis["summary"]
    ds = analysis["ds_channels"]
    us = analysis["us_channels"]
    ts = _state.get("last_update", "unknown")

    isp = _config_manager.get("isp_name", "") if _config_manager else ""
    conn = _state.get("connection_info") or {}
    ds_mbps = conn.get("max_downstream_kbps", 0) // 1000 if conn else 0
    us_mbps = conn.get("max_upstream_kbps", 0) // 1000 if conn else 0

    lines = [
        "# DOCSight – DOCSIS Cable Connection Status Report",
        "",
        "## Context",
        "This is a status report from a DOCSIS cable modem generated by DOCSight.",
        "DOCSIS (Data Over Cable Service Interface Specification) is the standard for internet over coaxial cable.",
        "Analyze this data and provide insights about connection health, problematic channels, and recommendations.",
        "",
        "## Overview",
        f"- **ISP**: {isp}" if isp else None,
        f"- **Tariff**: {ds_mbps}/{us_mbps} Mbit/s (Down/Up)" if ds_mbps else None,
        f"- **Health**: {s.get('health', 'Unknown')}",
        f"- **Issues**: {', '.join(s.get('health_issues', []))}" if s.get('health_issues') else None,
        f"- **Timestamp**: {ts}",
        "",
        "## Summary",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Downstream Channels | {s.get('ds_total', 0)} |",
        f"| DS Power (Min/Avg/Max) | {s.get('ds_power_min')} / {s.get('ds_power_avg')} / {s.get('ds_power_max')} dBmV |",
        f"| DS SNR (Min/Avg) | {s.get('ds_snr_min')} / {s.get('ds_snr_avg')} dB |",
        f"| DS Correctable Errors | {s.get('ds_correctable_errors', 0):,} |",
        f"| DS Uncorrectable Errors | {s.get('ds_uncorrectable_errors', 0):,} |",
        f"| Upstream Channels | {s.get('us_total', 0)} |",
        f"| US Power (Min/Avg/Max) | {s.get('us_power_min')} / {s.get('us_power_avg')} / {s.get('us_power_max')} dBmV |",
        "",
        "## Downstream Channels",
        "| Ch | Frequency | Power (dBmV) | SNR (dB) | Modulation | Corr. Errors | Uncorr. Errors | DOCSIS | Health |",
        "|----|-----------|-------------|----------|------------|-------------|---------------|--------|--------|",
    ]
    for ch in ds:
        lines.append(
            f"| {ch.get('channel_id','')} | {ch.get('frequency','')} | {ch.get('power','')} "
            f"| {ch.get('snr', '-')} | {ch.get('modulation','')} "
            f"| {ch.get('correctable_errors', 0):,} | {ch.get('uncorrectable_errors', 0):,} "
            f"| {ch.get('docsis_version','')} | {ch.get('health','')} |"
        )
    lines += [
        "",
        "## Upstream Channels",
        "| Ch | Frequency | Power (dBmV) | Modulation | Multiplex | DOCSIS | Health |",
        "|----|-----------|-------------|------------|-----------|--------|--------|",
    ]
    for ch in us:
        lines.append(
            f"| {ch.get('channel_id','')} | {ch.get('frequency','')} | {ch.get('power','')} "
            f"| {ch.get('modulation','')} | {ch.get('multiplex','')} "
            f"| {ch.get('docsis_version','')} | {ch.get('health','')} |"
        )
    lines += [
        "",
        "## Reference Values",
        "| Metric | Good | Marginal | Poor |",
        "|--------|------|----------|------|",
        "| DS Power | -7 to +7 dBmV | +/-7 to +/-10 | > +/-10 dBmV |",
        "| US Power | 35 to 49 dBmV | 50 to 54 | > 54 dBmV |",
        "| SNR/MER | > 30 dB | 25 to 30 | < 25 dB |",
        "| Uncorr. Errors | low | - | > 10,000 |",
        "",
        "## Questions",
        "Please analyze this data and provide:",
        "1. Overall connection health assessment",
        "2. Channels that need attention (with reasons)",
        "3. Error rate analysis and whether it indicates a problem",
        "4. Specific recommendations to improve connection quality",
    ]
    return jsonify({"text": "\n".join(l for l in lines if l is not None)})


@app.route("/api/snapshots")
@require_auth
def api_snapshots():
    """Return list of available snapshot timestamps."""
    if _storage:
        return jsonify(_storage.get_snapshot_list())
    return jsonify([])


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/health")
def health():
    """Simple health check endpoint."""
    if _state["analysis"]:
        return {"status": "ok", "docsis_health": _state["analysis"]["summary"]["health"]}
    return {"status": "waiting"}, 503
