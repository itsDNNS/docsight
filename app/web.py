"""Flask web UI for DOCSight – DOCSIS channel monitoring."""

import functools
import json
import logging
import math
import os
import re
import stat
import subprocess
import time
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, redirect, session, url_for, make_response, send_file
from werkzeug.security import check_password_hash

from io import BytesIO

from .config import POLL_MIN, POLL_MAX, PASSWORD_MASK, SECRET_KEYS
from .storage import ALLOWED_MIME_TYPES, MAX_ATTACHMENT_SIZE, MAX_ATTACHMENTS_PER_INCIDENT
from .i18n import get_translations, LANGUAGES, LANG_FLAGS

def _server_tz_info():
    """Return server timezone name and UTC offset in minutes."""
    now = datetime.now().astimezone()
    name = now.strftime("%Z") or time.tzname[0] or "UTC"
    offset_min = int(now.utcoffset().total_seconds() // 60)
    return name, offset_min

log = logging.getLogger("docsis.web")

def _get_version():
    """Get version from VERSION file, git tag, or fall back to 'dev'."""
    # 1. Check VERSION file (written during Docker build)
    for vpath in ("/app/VERSION", os.path.join(os.path.dirname(__file__), "..", "VERSION")):
        try:
            with open(vpath) as f:
                v = f.read().strip()
                if v:
                    return v
        except FileNotFoundError:
            pass
    # 2. Try git
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "dev"

APP_VERSION = _get_version()

def _load_changelog():
    """Load changelog.json from the app directory."""
    changelog_path = os.path.join(os.path.dirname(__file__), "changelog.json")
    try:
        with open(changelog_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

_changelog = _load_changelog()

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
    "device_info": None,
    "speedtest_latest": None,
}

_storage = None
_config_manager = None
_on_config_changed = None
_last_manual_poll = 0.0


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
    return {"auth_enabled": auth_enabled, "version": APP_VERSION}


def update_state(analysis=None, error=None, poll_interval=None, connection_info=None, device_info=None, speedtest_latest=None):
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
    if device_info is not None:
        _state["device_info"] = device_info
    if speedtest_latest is not None:
        _state["speedtest_latest"] = speedtest_latest


@app.route("/")
@require_auth
def index():
    if _config_manager and not _config_manager.is_configured():
        return redirect("/setup")

    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)

    isp_name = _config_manager.get("isp_name", "") if _config_manager else ""
    bqm_configured = _config_manager.is_bqm_configured() if _config_manager else False
    speedtest_configured = _config_manager.is_speedtest_configured() if _config_manager else False
    speedtest_latest = _state.get("speedtest_latest")
    booked_download = _config_manager.get("booked_download", 0) if _config_manager else 0
    booked_upload = _config_manager.get("booked_upload", 0) if _config_manager else 0
    conn_info = _state.get("connection_info") or {}
    dev_info = _state.get("device_info") or {}

    def _compute_uncorr_pct(analysis):
        """Compute log-scale percentage for uncorrectable errors gauge."""
        if not analysis:
            return 0
        uncorr = analysis.get("summary", {}).get("ds_uncorrectable_errors", 0)
        return min(100, math.log10(max(1, uncorr)) / 5 * 100)

    def _has_us_ofdma(analysis):
        """Check if any upstream channel uses DOCSIS 3.1+ (OFDMA)."""
        if not analysis:
            return True  # don't warn when no data yet
        for ch in analysis.get("us_channels", []):
            if str(ch.get("docsis_version", "")) in ("3.1", "4.0"):
                return True
        return False

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
                bqm_configured=bqm_configured,
                speedtest_configured=speedtest_configured,
                speedtest_latest=speedtest_latest,
                booked_download=booked_download,
                booked_upload=booked_upload,
                uncorr_pct=_compute_uncorr_pct(snapshot),
                has_us_ofdma=_has_us_ofdma(snapshot),
                device_info=dev_info,
                t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS,
                changelog=_changelog[0] if _changelog else None,
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
        bqm_configured=bqm_configured,
        speedtest_configured=speedtest_configured,
        speedtest_latest=speedtest_latest,
        booked_download=booked_download,
        booked_upload=booked_upload,
        uncorr_pct=_compute_uncorr_pct(_state["analysis"]),
        has_us_ofdma=_has_us_ofdma(_state["analysis"]),
        device_info=dev_info,
        t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS,
        changelog=_changelog[0] if _changelog else None,
    )


@app.route("/setup")
def setup():
    if _config_manager and _config_manager.is_configured():
        return redirect("/")
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    
    # Get available modem drivers
    from .drivers.loader import get_available_drivers
    available_drivers = get_available_drivers()
    
    return render_template("setup.html", config=config, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, available_drivers=available_drivers)


@app.route("/settings")
@require_auth
def settings():
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    theme = _config_manager.get_theme() if _config_manager else "dark"
    
    # Get available modem drivers
    from .drivers.loader import get_available_drivers
    available_drivers = get_available_drivers()
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    return render_template("settings.html", config=config, theme=theme, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, available_drivers=available_drivers)


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
        
        from .drivers.loader import load_driver
        modem_type = data.get("modem_type") or (_config_manager.get("modem_type", "fritzbox") if _config_manager else "fritzbox")
        driver = load_driver(modem_type)
        if not driver:
            return jsonify({"success": False, "error": f"Unknown modem type: {modem_type}"})
        
        session = driver.login(
            data.get("modem_url", "http://192.168.178.1"),
            data.get("modem_user", ""),
            password,
        )
        if not session:
            return jsonify({"success": False, "error": "Authentication failed"})
        
        info = driver.get_device_info(session, data.get("modem_url"))
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


@app.route("/api/modem-defaults/<modem_type>")
@require_auth
def api_modem_defaults(modem_type):
    """Get default configuration for a specific modem type."""
    from .config import MODEM_DEFAULTS
    defaults = MODEM_DEFAULTS.get(modem_type, {})
    return jsonify(defaults)


@app.route("/api/poll", methods=["POST"])
@require_auth
def api_poll():
    """Trigger an immediate modem poll and return fresh analysis."""
    global _last_manual_poll
    if not _config_manager:
        return jsonify({"success": False, "error": "Not configured"}), 500

    now = time.time()
    if now - _last_manual_poll < 10:
        lang = _get_lang()
        t = get_translations(lang)
        return jsonify({"success": False, "error": t.get("refresh_rate_limit", "Rate limited")}), 429

    try:
        from . import analyzer
        from .drivers.loader import load_driver
        
        config = _config_manager.get_all()
        driver = load_driver(config.get("modem_type", "fritzbox"))
        if not driver:
            return jsonify({"success": False, "error": "Failed to load modem driver"}), 500
        
        session = driver.login(
            config["modem_url"], config["modem_user"], config["modem_password"],
        )
        if not session:
            return jsonify({"success": False, "error": "Authentication failed"}), 401
        
        data = driver.get_docsis_data(session, config["modem_url"])
        analysis = analyzer.analyze(data)
        update_state(analysis=analysis)
        if _storage:
            _storage.save_snapshot(analysis)
        _last_manual_poll = time.time()
        return jsonify({"success": True, "analysis": analysis})
    except Exception as e:
        log.error("Manual poll failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


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

    mode = request.args.get("mode", "full")
    if mode not in ("full", "update"):
        mode = "full"

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
        f"- **Export Mode**: {'Full Context (48h)' if mode == 'full' else 'Update (6h)'}",
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

    # ── Historical context (events, speedtests, incidents) ──
    if _storage:
        if mode == "full":
            event_hours, speedtest_limit = 48, 10
        else:
            event_hours, speedtest_limit = 6, 3

        events = _storage.get_recent_events(hours=event_hours)
        if events:
            lines += [
                "",
                f"## Events (Last {event_hours}h)",
                "| Timestamp | Severity | Type | Message |",
                "|-----------|----------|------|---------|",
            ]
            for ev in events:
                lines.append(
                    f"| {ev['timestamp']} | {ev['severity']} | {ev['event_type']} | {ev['message']} |"
                )

        speedtests = _storage.get_recent_speedtests(limit=speedtest_limit)
        if speedtests:
            lines += [
                "",
                f"## Speedtest Results (Last {speedtest_limit})",
                "| Timestamp | Download | Upload | Ping | Jitter | Packet Loss |",
                "|-----------|----------|--------|------|--------|-------------|",
            ]
            for st in speedtests:
                lines.append(
                    f"| {st['timestamp']} | {st.get('download_human', '')} | {st.get('upload_human', '')} "
                    f"| {st.get('ping_ms', '-')} ms | {st.get('jitter_ms', '-')} ms "
                    f"| {st.get('packet_loss_pct', '-')}% |"
                )

        if mode == "full":
            incidents = _storage.get_active_incidents()
            if incidents:
                lines += ["", "## Incident Journal"]
                for inc in incidents:
                    lines.append(f"### [{inc['date']}] {inc['title']}")
                    if inc.get("description"):
                        lines.append(inc["description"])
                    lines.append("")

    # ── Dynamic reference values from thresholds.json ──
    from . import analyzer as _analyzer
    _thresh = _analyzer.get_thresholds()

    lines += ["", "## Reference Values (VFKD Guidelines)", ""]
    _src = _thresh.get("_source", "")
    if _src:
        lines.append(f"Source: {_src}")
        lines.append("")

    lines += [
        "### Downstream Power (dBmV)",
        "| Modulation | Good | Tolerated | Monthly | Immediate |",
        "|------------|------|-----------|---------|-----------|",
    ]
    _ds = _thresh.get("downstream_power", {})
    for mod in sorted(k for k in _ds if not k.startswith("_")):
        t = _ds[mod]
        lines.append(
            f"| {mod} "
            f"| {t['good_min']} to {t['good_max']} "
            f"| {t['tolerated_min']} to {t['tolerated_max']} "
            f"| {t['monthly_min']} to {t['monthly_max']} "
            f"| < {t['immediate_min']} or > {t['immediate_max']} |"
        )

    lines += [
        "",
        "### Upstream Power (dBmV)",
        "| DOCSIS Version | Good | Tolerated | Monthly | Immediate |",
        "|----------------|------|-----------|---------|-----------|",
    ]
    _us = _thresh.get("upstream_power", {})
    for ver in sorted(k for k in _us if not k.startswith("_")):
        t = _us[ver]
        lines.append(
            f"| {ver} "
            f"| {t['good_min']} to {t['good_max']} "
            f"| {t['tolerated_min']} to {t['tolerated_max']} "
            f"| {t['monthly_min']} to {t['monthly_max']} "
            f"| < {t['immediate_min']} or > {t['immediate_max']} |"
        )

    lines += [
        "",
        "### SNR / MER (dB, absolute)",
        "| Modulation | Good | Tolerated | Monthly | Immediate |",
        "|------------|------|-----------|---------|-----------|",
    ]
    _snr = _thresh.get("snr", {})
    for mod in sorted(k for k in _snr if not k.startswith("_")):
        t = _snr[mod]
        lines.append(
            f"| {mod} "
            f"| >= {t['good_min']} "
            f"| >= {t['tolerated_min']} "
            f"| >= {t['monthly_min']} "
            f"| < {t['immediate_min']} |"
        )

    _uncorr = _thresh.get("errors", {}).get("uncorrectable_threshold")
    if _uncorr is not None:
        lines.append("")
        lines.append(f"**Uncorrectable Errors Threshold**: > {_uncorr:,}")

    lines.append("")

    lines += [
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


@app.route("/api/bqm/dates")
@require_auth
def api_bqm_dates():
    """Return dates that have BQM graph data."""
    if _storage:
        return jsonify(_storage.get_bqm_dates())
    return jsonify([])


@app.route("/api/bqm/image/<date>")
@require_auth
def api_bqm_image(date):
    """Return BQM graph PNG for a given date."""
    if not _DATE_RE.match(date):
        return jsonify({"error": "Invalid date format"}), 400
    if not _storage:
        return jsonify({"error": "No storage"}), 404
    image = _storage.get_bqm_graph(date)
    if not image:
        return jsonify({"error": "No BQM graph for this date"}), 404
    resp = make_response(image)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/api/speedtest")
@require_auth
def api_speedtest():
    """Return speedtest results from local cache, with delta fetch from STT."""
    if not _config_manager or not _config_manager.is_speedtest_configured():
        return jsonify([])
    count = request.args.get("count", 2000, type=int)
    count = max(1, min(count, 5000))
    # Delta fetch: get new results from STT API and cache them
    if _storage:
        try:
            from .speedtest import SpeedtestClient
            client = SpeedtestClient(
                _config_manager.get("speedtest_tracker_url"),
                _config_manager.get("speedtest_tracker_token"),
            )
            cached_count = _storage.get_speedtest_count()
            if cached_count < 50:
                # Initial or incomplete cache: full fetch (descending)
                new_results = client.get_results(per_page=2000)
            else:
                last_id = _storage.get_latest_speedtest_id()
                new_results = client.get_newer_than(last_id)
            if new_results:
                _storage.save_speedtest_results(new_results)
                log.info("Cached %d new speedtest results (last_id was %d)", len(new_results), last_id)
        except Exception as e:
            log.warning("Speedtest delta fetch failed: %s", e)
        return jsonify(_storage.get_speedtest_results(limit=count))
    # Fallback: no storage, fetch directly
    from .speedtest import SpeedtestClient
    client = SpeedtestClient(
        _config_manager.get("speedtest_tracker_url"),
        _config_manager.get("speedtest_tracker_token"),
    )
    return jsonify(client.get_results(per_page=count))


@app.route("/api/speedtest/<int:result_id>/signal")
@require_auth
def api_speedtest_signal(result_id):
    """Return the closest DOCSIS snapshot signal data for a speedtest result."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    result = _storage.get_speedtest_by_id(result_id)
    if not result:
        return jsonify({"error": "Speedtest result not found"}), 404
    snap = _storage.get_closest_snapshot(result["timestamp"])
    if not snap:
        lang = _get_lang()
        t = get_translations(lang)
        return jsonify({
            "found": False,
            "message": t.get("signal_no_snapshot", "No signal snapshot found within 2 hours of this speedtest."),
        })
    s = snap["summary"]
    us_channels = []
    for ch in snap.get("us_channels", []):
        us_channels.append({
            "channel_id": ch.get("channel_id"),
            "modulation": ch.get("modulation", ""),
            "power": ch.get("power"),
        })
    return jsonify({
        "found": True,
        "snapshot_timestamp": snap["timestamp"],
        "health": s.get("health", "unknown"),
        "ds_power_avg": s.get("ds_power_avg"),
        "ds_power_min": s.get("ds_power_min"),
        "ds_power_max": s.get("ds_power_max"),
        "ds_snr_min": s.get("ds_snr_min"),
        "ds_snr_avg": s.get("ds_snr_avg"),
        "us_power_avg": s.get("us_power_avg"),
        "us_power_min": s.get("us_power_min"),
        "us_power_max": s.get("us_power_max"),
        "ds_uncorrectable_errors": s.get("ds_uncorrectable_errors", 0),
        "ds_correctable_errors": s.get("ds_correctable_errors", 0),
        "ds_total": s.get("ds_total", 0),
        "us_total": s.get("us_total", 0),
        "us_channels": us_channels,
    })


# ── Incident Journal API ──

@app.route("/api/incidents", methods=["GET"])
@require_auth
def api_incidents_list():
    """Return list of incidents with attachment counts."""
    if not _storage:
        return jsonify([])
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    return jsonify(_storage.get_incidents(limit=limit, offset=offset))


@app.route("/api/incidents", methods=["POST"])
@require_auth
def api_incidents_create():
    """Create a new incident."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not date or not _DATE_RE.match(date):
        return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title too long (max 200 characters)"}), 400
    if len(description) > 10000:
        return jsonify({"error": "Description too long (max 10000 characters)"}), 400
    incident_id = _storage.save_incident(date, title, description)
    return jsonify({"id": incident_id}), 201


@app.route("/api/incidents/<int:incident_id>", methods=["GET"])
@require_auth
def api_incident_get(incident_id):
    """Return single incident with attachment metadata."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Not found"}), 404
    return jsonify(incident)


@app.route("/api/incidents/<int:incident_id>", methods=["PUT"])
@require_auth
def api_incident_update(incident_id):
    """Update an existing incident."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not date or not _DATE_RE.match(date):
        return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title too long (max 200 characters)"}), 400
    if len(description) > 10000:
        return jsonify({"error": "Description too long (max 10000 characters)"}), 400
    if not _storage.update_incident(incident_id, date, title, description):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


@app.route("/api/incidents/<int:incident_id>", methods=["DELETE"])
@require_auth
def api_incident_delete(incident_id):
    """Delete an incident (CASCADE deletes attachments)."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_incident(incident_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


@app.route("/api/incidents/<int:incident_id>/attachments", methods=["POST"])
@require_auth
def api_incident_upload(incident_id):
    """Upload file attachment for an incident."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Incident not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    mime_type = f.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        return jsonify({"error": "File type not allowed"}), 400
    current_count = _storage.get_attachment_count(incident_id)
    if current_count >= MAX_ATTACHMENTS_PER_INCIDENT:
        return jsonify({"error": "Too many attachments (max %d)" % MAX_ATTACHMENTS_PER_INCIDENT}), 400
    file_data = f.read()
    if len(file_data) > MAX_ATTACHMENT_SIZE:
        return jsonify({"error": "File too large (max 10 MB)"}), 400
    attachment_id = _storage.save_attachment(incident_id, f.filename, mime_type, file_data)
    return jsonify({"id": attachment_id}), 201


@app.route("/api/attachments/<int:attachment_id>", methods=["GET"])
@require_auth
def api_attachment_get(attachment_id):
    """Download an attachment file."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    att = _storage.get_attachment(attachment_id)
    if not att:
        return jsonify({"error": "Not found"}), 404
    return send_file(
        BytesIO(att["data"]),
        mimetype=att["mime_type"],
        as_attachment=True,
        download_name=att["filename"],
    )


@app.route("/api/attachments/<int:attachment_id>", methods=["DELETE"])
@require_auth
def api_attachment_delete(attachment_id):
    """Delete a single attachment."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_attachment(attachment_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


# ── Event Log API ──

@app.route("/api/events", methods=["GET"])
@require_auth
def api_events_list():
    """Return list of events with optional filters."""
    if not _storage:
        return jsonify({"events": [], "unacknowledged_count": 0})
    limit = request.args.get("limit", 200, type=int)
    offset = request.args.get("offset", 0, type=int)
    severity = request.args.get("severity") or None
    event_type = request.args.get("event_type") or None
    ack_param = request.args.get("acknowledged")
    acknowledged = int(ack_param) if ack_param is not None and ack_param != "" else None
    events = _storage.get_events(
        limit=limit, offset=offset, severity=severity,
        event_type=event_type, acknowledged=acknowledged,
    )
    unack = _storage.get_event_count(acknowledged=0)
    return jsonify({"events": events, "unacknowledged_count": unack})


@app.route("/api/events/count", methods=["GET"])
@require_auth
def api_events_count():
    """Return unacknowledged event count (for badge)."""
    if not _storage:
        return jsonify({"count": 0})
    return jsonify({"count": _storage.get_event_count(acknowledged=0)})


@app.route("/api/events/<int:event_id>/acknowledge", methods=["POST"])
@require_auth
def api_event_acknowledge(event_id):
    """Acknowledge a single event."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.acknowledge_event(event_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


@app.route("/api/events/acknowledge-all", methods=["POST"])
@require_auth
def api_events_acknowledge_all():
    """Acknowledge all unacknowledged events."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    count = _storage.acknowledge_all_events()
    return jsonify({"success": True, "count": count})


# ── Channel Timeline API ──

@app.route("/api/channels")
@require_auth
def api_channels():
    """Return current DS and US channels from the latest snapshot."""
    if not _storage:
        return jsonify({"ds_channels": [], "us_channels": []})
    return jsonify(_storage.get_current_channels())


@app.route("/api/channel-history")
@require_auth
def api_channel_history():
    """Return per-channel time series data.
    ?channel_id=X&direction=ds|us&days=7"""
    if not _storage:
        return jsonify([])
    channel_id = request.args.get("channel_id", type=int)
    direction = request.args.get("direction", "ds")
    days = request.args.get("days", 7, type=int)
    if channel_id is None:
        return jsonify({"error": "channel_id is required"}), 400
    if direction not in ("ds", "us"):
        return jsonify({"error": "direction must be 'ds' or 'us'"}), 400
    days = max(1, min(days, 90))
    return jsonify(_storage.get_channel_history(channel_id, direction, days))


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/api/report")
@require_auth
def api_report():
    """Generate a PDF incident report."""
    from .report import generate_report

    analysis = _state.get("analysis")
    if not analysis:
        return jsonify({"error": "No data available"}), 404

    # Time range: default last 7 days, configurable via ?days=N
    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 90))
    end_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    start_ts = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    snapshots = []
    if _storage:
        snapshots = _storage.get_range_data(start_ts, end_ts)

    config = {}
    if _config_manager:
        config = {
            "isp_name": _config_manager.get("isp_name", ""),
            "modem_type": _config_manager.get("modem_type", ""),
        }

    conn_info = _state.get("connection_info") or {}
    lang = _get_lang()

    pdf_bytes = generate_report(snapshots, analysis, config, conn_info, lang)

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    response.headers["Content-Disposition"] = f'attachment; filename="docsight_incident_report_{ts}.pdf"'
    return response


@app.route("/api/complaint")
@require_auth
def api_complaint():
    """Generate ISP complaint letter as text."""
    from .report import generate_complaint_text

    analysis = _state.get("analysis")
    if not analysis:
        return jsonify({"error": "No data available"}), 404

    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 90))
    end_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    start_ts = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    snapshots = []
    if _storage:
        snapshots = _storage.get_range_data(start_ts, end_ts)

    config = {}
    if _config_manager:
        config = {
            "isp_name": _config_manager.get("isp_name", ""),
            "modem_type": _config_manager.get("modem_type", ""),
        }

    lang = request.args.get("lang", _get_lang())
    customer_name = request.args.get("name", "")
    customer_number = request.args.get("number", "")
    customer_address = request.args.get("address", "")

    text = generate_complaint_text(
        snapshots, config, None, lang,
        customer_name, customer_number, customer_address
    )
    return jsonify({"text": text, "lang": lang})


@app.route("/api/changelog")
@require_auth
def api_changelog():
    """Return full changelog data."""
    return jsonify(_changelog)


@app.route("/health")
def health():
    """Simple health check endpoint."""
    if _state["analysis"]:
        return {"status": "ok", "docsis_health": _state["analysis"]["summary"]["health"]}
    return {"status": "ok", "docsis_health": "waiting"}
