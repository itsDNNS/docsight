"""Flask web UI for DOCSight – DOCSIS channel monitoring."""

import functools
import json
import logging
import math
import os
import re
import stat
import subprocess
import threading
import time
from datetime import datetime, timedelta

import requests as _requests

from flask import Flask, render_template, request, jsonify, redirect, session, url_for, make_response, send_file
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from io import BytesIO

from .config import POLL_MIN, POLL_MAX, PASSWORD_MASK, SECRET_KEYS, HASH_KEYS
from .gaming_index import compute_gaming_index
from .storage import ALLOWED_MIME_TYPES, MAX_ATTACHMENT_SIZE, MAX_ATTACHMENTS_PER_ENTRY
from .i18n import get_translations, LANGUAGES, LANG_FLAGS

def _server_tz_info():
    """Return server timezone name and UTC offset in minutes."""
    now = datetime.now().astimezone()
    name = now.strftime("%Z") or time.tzname[0] or "UTC"
    offset_min = int(now.utcoffset().total_seconds() // 60)
    return name, offset_min

log = logging.getLogger("docsis.web")
audit_log = logging.getLogger("docsis.audit")

# ── Login rate limiting (in-memory) ──
_login_attempts = {}  # IP -> [timestamp, ...]
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 900  # 15 min
_LOGIN_LOCKOUT_BASE = 30  # seconds, doubles each excess attempt


def _get_client_ip():
    """Get client IP, respecting X-Forwarded-For behind reverse proxy."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_login_rate_limit(ip):
    """Return seconds until retry allowed, or 0 if not limited."""
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        excess = len(attempts) - _LOGIN_MAX_ATTEMPTS
        lockout = _LOGIN_LOCKOUT_BASE * (2 ** min(excess, 8))
        remaining = lockout - (now - attempts[-1])
        if remaining > 0:
            return remaining
    return 0


def _record_failed_login(ip):
    """Record a failed login attempt."""
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())

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

# GitHub update check (background, never blocks page loads)
_update_cache = {"latest": None, "checked_at": 0, "checking": False}
_UPDATE_CACHE_TTL = 3600  # 1 hour

def _check_for_update():
    """Return cached update info. Triggers background check if stale."""
    now = time.time()
    if now - _update_cache["checked_at"] < _UPDATE_CACHE_TTL:
        return _update_cache["latest"]
    if APP_VERSION == "dev":
        return None
    if not _update_cache["checking"]:
        _update_cache["checking"] = True
        import threading
        threading.Thread(target=_fetch_update, daemon=True).start()
    return _update_cache["latest"]

def _fetch_update():
    """Background thread: fetch latest release from GitHub."""
    try:
        r = _requests.get(
            "https://api.github.com/repos/itsDNNS/docsight/releases/latest",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=5,
        )
        if r.status_code == 200:
            tag = r.json().get("tag_name", "")
            cur = APP_VERSION.lstrip("v")
            lat = tag.lstrip("v")
            if lat and lat != cur and _version_newer(lat, cur):
                _update_cache["latest"] = tag
            else:
                _update_cache["latest"] = None
    except Exception:
        pass  # keep previous cache value
    finally:
        _update_cache["checked_at"] = time.time()
        _update_cache["checking"] = False

def _version_newer(latest, current):
    """Compare date-based version strings (e.g. '2026-02-16.1' > '2026-02-13.8')."""
    return latest > current


app = Flask(__name__, template_folder="templates")
app.secret_key = os.urandom(32)  # overwritten by _init_session_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(date_str):
    """Validate date string format AND actual calendar validity."""
    if not date_str or not _DATE_RE.match(date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False
_SAFE_HTML_RE = re.compile(r"<(?!/?(?:b|a|strong|em|br)\b)[^>]+>", re.IGNORECASE)


@app.template_filter("safe_html")
def safe_html_filter(value):
    """Allow only <b>, <a>, <strong>, <em>, <br> tags — strip everything else."""
    from markupsafe import Markup
    cleaned = _SAFE_HTML_RE.sub("", str(value))
    return Markup(cleaned)


@app.template_filter("fmt_k")
def format_k(value):
    """Format large numbers with k/M suffix: 1200000 -> 1.2M, 132007 -> 132k, 5929 -> 5.9k."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return str(value)
    if value >= 1000000:
        # Million: 1.2M, 12M
        formatted = f"{value / 1000000:.1f}"
        if formatted.endswith(".0"):
            formatted = formatted[:-2]
        return formatted + "M"
    elif value >= 100000:
        return f"{value // 1000}k"
    elif value >= 1000:
        formatted = f"{value / 1000:.1f}"
        if formatted.endswith(".0"):
            formatted = formatted[:-2]
        return formatted + "k"
    return str(value)


@app.template_filter("fmt_speed_value")
def format_speed_value(value):
    """Format speed value: >= 1000 Mbps -> GBit value."""
    try:
        value = float(value)
    except (ValueError, TypeError):
        return str(value)
    if value >= 1000:
        # Convert to GBit: 1094 -> 1.1
        return f"{value / 1000:.1f}"
    else:
        # Keep as Mbps: 544 -> 544
        return str(int(round(value)))


@app.template_filter("fmt_speed_unit")
def format_speed_unit(value):
    """Return speed unit: >= 1000 Mbps -> 'GBit/s', else 'MBit/s'."""
    try:
        value = float(value)
    except (ValueError, TypeError):
        return "MBit/s"
    return "GBit/s" if value >= 1000 else "MBit/s"


def _get_lang():
    """Get language from query param or config."""
    lang = request.args.get("lang")
    if lang and lang in LANGUAGES:
        return lang
    if _config_manager:
        return _config_manager.get("language", "en")
    return "en"

# Shared state (updated from main loop)
_state_lock = threading.Lock()
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
_modem_collector = None
_collectors = []
_last_manual_poll = 0.0


def init_storage(storage):
    """Set the snapshot storage instance."""
    global _storage
    _storage = storage


def init_collector(modem_collector):
    """Set the modem collector instance for manual polling."""
    global _modem_collector
    _modem_collector = modem_collector


def init_collectors(collectors):
    """Set the list of all collectors for status reporting."""
    global _collectors
    _collectors = collectors


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
        ip = _get_client_ip()
        wait = _check_login_rate_limit(ip)
        if wait > 0:
            audit_log.warning("Login rate-limited: ip=%s (retry in %ds)", ip, int(wait))
            error = t.get("login_rate_limited", "Too many attempts. Try again later.")
            return render_template("login.html", t=t, lang=lang, theme=theme, error=error)
        pw = request.form.get("password", "")
        stored = _config_manager.get("admin_password", "")
        if stored.startswith(("scrypt:", "pbkdf2:")):
            success = check_password_hash(stored, pw)
        else:
            success = (pw == stored)
            if success:
                # Auto-upgrade plaintext password to hash
                _config_manager.save({"admin_password": pw})
                audit_log.info("Auto-upgraded plaintext password to hash for ip=%s", ip)
        if success:
            _login_attempts.pop(ip, None)
            session.permanent = True
            session["authenticated"] = True
            audit_log.info("Login successful: ip=%s", ip)
            return redirect("/")
        _record_failed_login(ip)
        audit_log.warning("Login failed: ip=%s", ip)
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
    return {"auth_enabled": auth_enabled, "version": APP_VERSION, "update_available": _check_for_update()}


def update_state(analysis=None, error=None, poll_interval=None, connection_info=None, device_info=None, speedtest_latest=None):
    """Update the shared web state from the main loop (thread-safe)."""
    with _state_lock:
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


def get_state() -> dict:
    """Return a snapshot of the shared web state (thread-safe)."""
    with _state_lock:
        return dict(_state)


@app.route("/")
@require_auth
def index():
    demo_mode = _config_manager.is_demo_mode() if _config_manager else False
    if _config_manager and not demo_mode and not _config_manager.is_configured():
        return redirect("/setup")

    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)

    isp_name = _config_manager.get("isp_name", "") if _config_manager else ""
    bqm_configured = _config_manager.is_bqm_configured() if _config_manager else False
    smokeping_configured = _config_manager.is_smokeping_configured() if _config_manager else False
    speedtest_configured = _config_manager.is_speedtest_configured() if _config_manager else False
    gaming_quality_enabled = _config_manager.is_gaming_quality_enabled() if _config_manager else False
    bnetz_enabled = _config_manager.is_bnetz_enabled() if _config_manager else True
    state = get_state()
    speedtest_latest = state.get("speedtest_latest")
    booked_download = _config_manager.get("booked_download", 0) if _config_manager else 0
    booked_upload = _config_manager.get("booked_upload", 0) if _config_manager else 0
    conn_info = state.get("connection_info") or {}
    # Demo mode: derive booked speeds from connection info if not explicitly set
    if demo_mode:
        if not booked_download:
            booked_download = conn_info.get("max_downstream_kbps", 250000) // 1000
        if not booked_upload:
            booked_upload = conn_info.get("max_upstream_kbps", 40000) // 1000
    dev_info = state.get("device_info") or {}
    analysis = state["analysis"]
    gaming_index = compute_gaming_index(analysis, speedtest_latest) if gaming_quality_enabled else None
    bnetz_latest = _storage.get_latest_bnetz() if _storage and bnetz_enabled else None

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

    return render_template(
        "index.html",
        analysis=analysis,
        last_update=state["last_update"],
        poll_interval=state["poll_interval"],
        error=state["error"],
        theme=theme,
        isp_name=isp_name, connection_info=conn_info,
        bqm_configured=bqm_configured,
        smokeping_configured=smokeping_configured,
        speedtest_configured=speedtest_configured,
        speedtest_latest=speedtest_latest,
        booked_download=booked_download,
        booked_upload=booked_upload,
        uncorr_pct=_compute_uncorr_pct(analysis),
        has_us_ofdma=_has_us_ofdma(analysis),
        device_info=dev_info,
        demo_mode=demo_mode,
        gaming_quality_enabled=gaming_quality_enabled,
        gaming_index=gaming_index,
        bnetz_enabled=bnetz_enabled,
        bnetz_latest=bnetz_latest,
        t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS,
    )


@app.route("/setup")
def setup():
    if _config_manager and (_config_manager.is_configured() or _config_manager.is_demo_mode()):
        return redirect("/")
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    from .drivers import DRIVER_REGISTRY, DRIVER_DISPLAY_NAMES
    modem_types = [(k, DRIVER_DISPLAY_NAMES.get(k, k)) for k in sorted(DRIVER_REGISTRY)]
    return render_template("setup.html", config=config, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, modem_types=modem_types)


@app.route("/settings")
@require_auth
def settings():
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    from .drivers import DRIVER_REGISTRY, DRIVER_DISPLAY_NAMES
    modem_types = [(k, DRIVER_DISPLAY_NAMES.get(k, k)) for k in sorted(DRIVER_REGISTRY)]
    return render_template("settings.html", config=config, theme=theme, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, modem_types=modem_types)


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
        changed_keys = [k for k in data if k not in SECRET_KEYS and k not in HASH_KEYS]
        secret_changed = [k for k in data if k in SECRET_KEYS or k in HASH_KEYS]
        _config_manager.save(data)
        audit_log.info(
            "Config changed: ip=%s keys=%s secrets_changed=%s",
            _get_client_ip(), changed_keys, secret_changed,
        )
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
        from .drivers import load_driver
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
        log.warning("MQTT test failed: %s", e)
        return jsonify({"success": False, "error": type(e).__name__ + ": " + str(e).split("\n")[0][:200]})


@app.route("/api/notifications/test", methods=["POST"])
@require_auth
def api_notifications_test():
    """Send a test notification to all configured channels."""
    if not _config_manager or not _config_manager.is_notify_configured():
        return jsonify({"success": False, "error": "Notifications not configured"}), 400
    from .notifier import NotificationDispatcher
    dispatcher = NotificationDispatcher(_config_manager)
    result = dispatcher.test()
    return jsonify(result)


@app.route("/api/poll", methods=["POST"])
@require_auth
def api_poll():
    """Trigger an immediate modem poll via ModemCollector.

    Uses the same collector instance as automatic polling to ensure
    consistent behavior and fail-safe application.
    Uses _collect_lock to prevent collision with parallel auto-poll.
    """
    global _last_manual_poll

    if not _modem_collector:
        return jsonify({"success": False, "error": "Collector not initialized"}), 500

    now = time.time()
    if now - _last_manual_poll < 10:
        lang = _get_lang()
        t = get_translations(lang)
        return jsonify({"success": False, "error": t.get("refresh_rate_limit", "Rate limited")}), 429

    if not _modem_collector._collect_lock.acquire(timeout=0):
        return jsonify({"success": False, "error": "Poll already in progress"}), 429

    try:
        result = _modem_collector.collect()

        if not result.success:
            return jsonify({"success": False, "error": result.error}), 500

        _last_manual_poll = time.time()

        # Return the analysis data from the collector result
        # (ModemCollector already updated web state and saved snapshot)
        return jsonify({"success": True, "analysis": result.data})

    except Exception as e:
        log.error("Manual poll failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _modem_collector._collect_lock.release()


@app.route("/api/collectors/status")
@require_auth
def api_collectors_status():
    """Return health status of all collectors.
    
    Provides monitoring info: failure counts, penalties, next poll times.
    Useful for debugging collector issues and fail-safe behavior.
    """
    if not _collectors:
        return jsonify([])
    
    return jsonify([c.get_status() for c in _collectors])



@app.route("/api/trends")
@require_auth
def api_trends():
    """Return trend data for a date range.
    ?range=day|week|month&date=YYYY-MM-DD (date defaults to today)."""
    if not _storage:
        return jsonify([])
    range_type = request.args.get("range", "day")
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    try:
        ref_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    if range_type == "day":
        return jsonify(_storage.get_intraday_data(date_str))
    elif range_type == "week":
        start = (ref_date - timedelta(days=6)).strftime("%Y-%m-%d")
        return jsonify(_storage.get_summary_range(start, date_str))
    elif range_type == "month":
        start = (ref_date - timedelta(days=29)).strftime("%Y-%m-%d")
        return jsonify(_storage.get_summary_range(start, date_str))
    else:
        return jsonify({"error": "Invalid range (use day, week, month)"}), 400


@app.route("/api/export")
@require_auth
def api_export():
    """Generate a structured markdown report for LLM analysis."""
    state = get_state()
    analysis = state.get("analysis")
    if not analysis:
        return jsonify({"error": "No data available"}), 404

    mode = request.args.get("mode", "full")
    if mode not in ("full", "update"):
        mode = "full"

    s = analysis["summary"]
    ds = analysis["ds_channels"]
    us = analysis["us_channels"]
    ts = state.get("last_update", "unknown")

    isp = _config_manager.get("isp_name", "") if _config_manager else ""
    conn = state.get("connection_info") or {}
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
            entries = _storage.get_active_entries()
            if entries:
                lines += ["", "## Incident Journal"]
                for inc in entries:
                    lines.append(f"### [{inc['date']}] {inc['title']}")
                    if inc.get("description"):
                        lines.append(inc["description"])
                    lines.append("")

        # ── Cross-source correlation ──
        if speedtests:
            corr_lines = []
            for st in speedtests:
                snap = _storage.get_closest_snapshot(st["timestamp"])
                if snap:
                    ss = snap["summary"]
                    corr_lines.append(
                        f"| {st['timestamp'][:16]} | {st.get('download_human', '')} "
                        f"| {ss.get('health', '')} | {ss.get('ds_snr_min', '')} dB "
                        f"| {ss.get('ds_power_avg', '')} dBmV "
                        f"| {ss.get('ds_uncorrectable_errors', 0):,} |"
                    )
            if corr_lines:
                lines += [
                    "",
                    "## Cross-Source Correlation",
                    "Speedtest performance correlated with modem signal health at the time of each test.",
                    "",
                    "| Speedtest Time | Download | Modem Health | DS SNR Min | DS Power Avg | Uncorr. Errors |",
                    "|---------------|----------|-------------|------------|-------------|----------------|",
                ]
                lines.extend(corr_lines)

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


SMOKEPING_TIMESPANS = {
    "3h": "last_10800",
    "30h": "last_108000",
    "10d": "last_864000",
    "1y": "last_31104000",
}


@app.route("/api/smokeping/targets")
@require_auth
def api_smokeping_targets():
    """Return list of configured Smokeping targets."""
    if not _config_manager or not _config_manager.is_smokeping_configured():
        return jsonify([])
    raw = _config_manager.get("smokeping_targets", "")
    targets = [t.strip() for t in raw.split(",") if t.strip()]
    return jsonify(targets)


@app.route("/api/smokeping/graph/<path:target>/<timespan>")
@require_auth
def api_smokeping_graph(target, timespan):
    """Proxy a Smokeping graph PNG."""
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
    if not _valid_date(date):
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
    # Demo mode: return seeded data without external API call
    if _config_manager.is_demo_mode() and _storage:
        return jsonify(_storage.get_speedtest_results(limit=count))
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


# ── Journal Entries API (renamed from /api/incidents) ──

@app.route("/api/journal", methods=["GET"])
@require_auth
def api_journal_list():
    """Return list of journal entries with attachment counts."""
    if not _storage:
        return jsonify([])
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    search = request.args.get("search", "", type=str).strip() or None
    incident_id_param = request.args.get("incident_id", None, type=str)
    incident_id = None
    if incident_id_param is not None and incident_id_param != "":
        try:
            incident_id = int(incident_id_param)
        except (ValueError, TypeError):
            pass
    return jsonify(_storage.get_entries(limit=limit, offset=offset, search=search, incident_id=incident_id))


@app.route("/api/journal", methods=["POST"])
@require_auth
def api_journal_create():
    """Create a new journal entry."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not _valid_date(date):
        return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title too long (max 200 characters)"}), 400
    if len(description) > 10000:
        return jsonify({"error": "Description too long (max 10000 characters)"}), 400
    icon = (data.get("icon") or "").strip() or None
    inc_id = data.get("incident_id")
    if inc_id is not None:
        try:
            inc_id = int(inc_id) if inc_id else None
        except (ValueError, TypeError):
            inc_id = None
    entry_id = _storage.save_entry(date, title, description, icon=icon, incident_id=inc_id)
    audit_log.info("Journal entry created: ip=%s id=%d title=%s", _get_client_ip(), entry_id, title[:50])
    return jsonify({"id": entry_id}), 201


@app.route("/api/journal/<int:entry_id>", methods=["GET"])
@require_auth
def api_journal_get(entry_id):
    """Return single journal entry with attachment metadata."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    entry = _storage.get_entry(entry_id)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    return jsonify(entry)


@app.route("/api/journal/<int:entry_id>", methods=["PUT"])
@require_auth
def api_journal_update(entry_id):
    """Update an existing journal entry."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not _valid_date(date):
        return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title too long (max 200 characters)"}), 400
    if len(description) > 10000:
        return jsonify({"error": "Description too long (max 10000 characters)"}), 400
    icon = (data.get("icon") or "").strip() or None
    inc_id = data.get("incident_id")
    if inc_id is not None:
        try:
            inc_id = int(inc_id) if inc_id else None
        except (ValueError, TypeError):
            inc_id = None
    if not _storage.update_entry(entry_id, date, title, description, icon=icon, incident_id=inc_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Journal entry updated: ip=%s id=%d", _get_client_ip(), entry_id)
    return jsonify({"success": True})


@app.route("/api/journal/<int:entry_id>", methods=["DELETE"])
@require_auth
def api_journal_delete(entry_id):
    """Delete a journal entry (CASCADE deletes attachments)."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_entry(entry_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Journal entry deleted: ip=%s id=%d", _get_client_ip(), entry_id)
    return jsonify({"success": True})


@app.route("/api/journal/<int:entry_id>/attachments", methods=["POST"])
@require_auth
def api_journal_upload(entry_id):
    """Upload file attachment for a journal entry."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    entry = _storage.get_entry(entry_id)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    mime_type = f.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        return jsonify({"error": "File type not allowed"}), 400
    current_count = _storage.get_attachment_count(entry_id)
    if current_count >= MAX_ATTACHMENTS_PER_ENTRY:
        return jsonify({"error": "Too many attachments (max %d)" % MAX_ATTACHMENTS_PER_ENTRY}), 400
    file_data = f.read()
    if len(file_data) > MAX_ATTACHMENT_SIZE:
        return jsonify({"error": "File too large (max 10 MB)"}), 400
    filename = secure_filename(f.filename) or "attachment"
    attachment_id = _storage.save_attachment(entry_id, filename, mime_type, file_data)
    audit_log.info(
        "Attachment uploaded: ip=%s entry=%d file=%s size=%d",
        _get_client_ip(), entry_id, filename, len(file_data),
    )
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
    audit_log.info("Attachment deleted: ip=%s id=%d", _get_client_ip(), attachment_id)
    return jsonify({"success": True})


# ── Journal Import API ──

@app.route("/api/journal/import/preview", methods=["POST"])
@require_auth
def api_journal_import_preview():
    """Upload Excel/CSV file and return parsed preview with auto-detected mapping."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    lower = f.filename.lower()
    if not (lower.endswith(".xlsx") or lower.endswith(".csv")):
        return jsonify({"error": "Only .xlsx and .csv files are supported"}), 400

    file_bytes = f.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        return jsonify({"error": "File too large (max 5 MB)"}), 400

    from .import_parser import parse_file
    try:
        result = parse_file(file_bytes, f.filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        log.exception("Import parse error")
        return jsonify({"error": "Failed to parse file"}), 500

    # Mark duplicates
    for row in result["rows"]:
        row["duplicate"] = _storage.check_entry_exists(row["date"], row["title"])

    duplicates = sum(1 for r in result["rows"] if r["duplicate"])
    result["duplicates"] = duplicates

    audit_log.info(
        "Import preview: ip=%s file=%s total=%d skipped=%d duplicates=%d",
        _get_client_ip(), f.filename, result["total"], result["skipped"], duplicates,
    )
    return jsonify(result)


@app.route("/api/journal/import/confirm", methods=["POST"])
@require_auth
def api_journal_import_confirm():
    """Bulk-import confirmed journal entry rows."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data or "rows" not in data:
        return jsonify({"error": "No rows provided"}), 400

    rows = data["rows"]
    if not isinstance(rows, list):
        return jsonify({"error": "rows must be a list"}), 400

    imported = 0
    duplicates = 0
    for row in rows:
        date = (row.get("date") or "").strip()
        title = (row.get("title") or "").strip()
        description = (row.get("description") or "").strip()

        if not _valid_date(date):
            continue
        if not title:
            continue
        if len(title) > 200:
            title = title[:200]
        if len(description) > 10000:
            description = description[:10000]

        if _storage.check_entry_exists(date, title):
            duplicates += 1
            continue

        _storage.save_entry(date, title, description)
        imported += 1

    audit_log.info(
        "Import confirm: ip=%s imported=%d duplicates=%d",
        _get_client_ip(), imported, duplicates,
    )
    return jsonify({"imported": imported, "duplicates": duplicates})


@app.route("/api/journal/batch", methods=["DELETE"])
@require_auth
def api_journal_batch_delete():
    """Batch delete journal entries by IDs or delete all."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    if data.get("all"):
        if data.get("confirm") != "DELETE_ALL":
            return jsonify({"error": "Confirmation required: set confirm to 'DELETE_ALL'"}), 400
        deleted = _storage.delete_all_entries()
        audit_log.info("All journal entries deleted: ip=%s count=%d", _get_client_ip(), deleted)
        return jsonify({"deleted": deleted})

    ids = data.get("ids")
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "Provide 'ids' list or 'all: true'"}), 400
    ids = [int(i) for i in ids if isinstance(i, (int, float))]
    if not ids:
        return jsonify({"error": "No valid IDs"}), 400

    deleted = _storage.delete_entries_batch(ids)
    audit_log.info("Batch delete journal entries: ip=%s ids=%s deleted=%d", _get_client_ip(), ids, deleted)
    return jsonify({"deleted": deleted})


# ── Journal Entry Unassign ──

@app.route("/api/journal/unassign", methods=["POST"])
@require_auth
def api_journal_unassign():
    """Remove incident assignment from journal entries."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    entry_ids = data.get("entry_ids", [])
    if not entry_ids or not isinstance(entry_ids, list):
        return jsonify({"error": "Provide entry_ids list"}), 400
    entry_ids = [int(i) for i in entry_ids if isinstance(i, (int, float))]
    count = _storage.unassign_entries(entry_ids)
    return jsonify({"updated": count})


# ── Incident Container API (NEW) ──

_VALID_INCIDENT_STATUSES = {"open", "resolved", "escalated"}


@app.route("/api/incidents", methods=["GET"])
@require_auth
def api_incidents_list():
    """Return list of incident containers with entry_count."""
    if not _storage:
        return jsonify([])
    status = request.args.get("status", None, type=str)
    if status and status not in _VALID_INCIDENT_STATUSES:
        status = None
    return jsonify(_storage.get_incidents(status=status))


@app.route("/api/incidents", methods=["POST"])
@require_auth
def api_incidents_create():
    """Create a new incident container."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if len(name) > 200:
        return jsonify({"error": "Name too long (max 200 characters)"}), 400
    description = (data.get("description") or "").strip()
    if len(description) > 5000:
        return jsonify({"error": "Description too long (max 5000 characters)"}), 400
    status = (data.get("status") or "open").strip()
    if status not in _VALID_INCIDENT_STATUSES:
        return jsonify({"error": "Invalid status (open, resolved, escalated)"}), 400
    start_date = (data.get("start_date") or "").strip() or None
    end_date = (data.get("end_date") or "").strip() or None
    if start_date and not _valid_date(start_date):
        return jsonify({"error": "Invalid start_date format (YYYY-MM-DD)"}), 400
    if end_date and not _valid_date(end_date):
        return jsonify({"error": "Invalid end_date format (YYYY-MM-DD)"}), 400
    icon = (data.get("icon") or "").strip() or None
    incident_id = _storage.save_incident(name, description, status, start_date, end_date, icon)
    audit_log.info("Incident created: ip=%s id=%d name=%s", _get_client_ip(), incident_id, name[:50])
    return jsonify({"id": incident_id}), 201


@app.route("/api/incidents/<int:incident_id>", methods=["GET"])
@require_auth
def api_incident_get(incident_id):
    """Return single incident container with entry_count."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Not found"}), 404
    return jsonify(incident)


@app.route("/api/incidents/<int:incident_id>", methods=["PUT"])
@require_auth
def api_incident_update(incident_id):
    """Update an existing incident container."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if len(name) > 200:
        return jsonify({"error": "Name too long (max 200 characters)"}), 400
    description = (data.get("description") or "").strip()
    if len(description) > 5000:
        return jsonify({"error": "Description too long (max 5000 characters)"}), 400
    status = (data.get("status") or "open").strip()
    if status not in _VALID_INCIDENT_STATUSES:
        return jsonify({"error": "Invalid status (open, resolved, escalated)"}), 400
    start_date = (data.get("start_date") or "").strip() or None
    end_date = (data.get("end_date") or "").strip() or None
    if start_date and not _valid_date(start_date):
        return jsonify({"error": "Invalid start_date format (YYYY-MM-DD)"}), 400
    if end_date and not _valid_date(end_date):
        return jsonify({"error": "Invalid end_date format (YYYY-MM-DD)"}), 400
    icon = (data.get("icon") or "").strip() or None
    if not _storage.update_incident(incident_id, name, description, status, start_date, end_date, icon):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Incident updated: ip=%s id=%d", _get_client_ip(), incident_id)
    return jsonify({"success": True})


@app.route("/api/incidents/<int:incident_id>", methods=["DELETE"])
@require_auth
def api_incident_delete(incident_id):
    """Delete an incident container (entries become unassigned)."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_incident(incident_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Incident deleted: ip=%s id=%d", _get_client_ip(), incident_id)
    return jsonify({"success": True})


@app.route("/api/incidents/<int:incident_id>/timeline")
@require_auth
def api_incident_timeline(incident_id):
    """Return bundled timeline data for a single incident."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Not found"}), 404

    entries = _storage.get_entries(limit=9999, incident_id=incident_id)

    timeline = []
    bnetz = []
    if incident.get("start_date"):
        start_ts = incident["start_date"] + "T00:00:00"
        end_date = incident.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        end_ts = end_date + "T23:59:59"
        timeline = _storage.get_correlation_timeline(start_ts, end_ts)
        bnetz = _storage.get_bnetz_in_range(start_ts, end_ts)

    return jsonify({
        "incident": incident,
        "entries": entries,
        "timeline": timeline,
        "bnetz": bnetz,
    })


@app.route("/api/incidents/<int:incident_id>/report")
@require_auth
def api_incident_report(incident_id):
    """Generate PDF complaint report for a specific incident."""
    from .report import generate_incident_report

    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500

    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Not found"}), 404

    entries = _storage.get_entries(limit=9999, incident_id=incident_id)

    # For entries with attachments, load full attachment metadata
    for entry in entries:
        full = _storage.get_entry(entry["id"])
        if full:
            entry["attachments"] = full.get("attachments", [])

    snapshots = []
    speedtests = []
    bnetz = []
    if incident.get("start_date"):
        start_ts = incident["start_date"] + "T00:00:00"
        end_date = incident.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        end_ts = end_date + "T23:59:59"
        snapshots = _storage.get_range_data(start_ts, end_ts)
        speedtests = _storage.get_speedtest_in_range(start_ts, end_ts)
        bnetz = _storage.get_bnetz_in_range(start_ts, end_ts)

    config = {}
    if _config_manager:
        config = {
            "isp_name": _config_manager.get("isp_name", ""),
            "modem_type": _config_manager.get("modem_type", ""),
        }

    conn_info = get_state().get("connection_info") or {}
    lang = _get_lang()

    pdf_bytes = generate_incident_report(
        incident, entries, snapshots, speedtests, bnetz,
        config, conn_info, lang,
        attachment_loader=_storage.get_attachment,
    )

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', incident.get("name", "incident"))
    ts = datetime.now().strftime("%Y-%m-%d")
    response.headers["Content-Disposition"] = f'attachment; filename="DOCSight_Beschwerde_{safe_name}_{ts}.pdf"'
    return response


@app.route("/api/incidents/<int:incident_id>/assign", methods=["POST"])
@require_auth
def api_incident_assign(incident_id):
    """Assign journal entries to an incident."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Incident not found"}), 404
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    entry_ids = data.get("entry_ids", [])
    if not entry_ids or not isinstance(entry_ids, list):
        return jsonify({"error": "Provide entry_ids list"}), 400
    entry_ids = [int(i) for i in entry_ids if isinstance(i, (int, float))]
    count = _storage.assign_entries_to_incident(entry_ids, incident_id)
    audit_log.info("Entries assigned: ip=%s incident=%d count=%d", _get_client_ip(), incident_id, count)
    return jsonify({"updated": count})


# ── Breitbandmessung (BNetzA) API ──

@app.route("/api/bnetz/upload", methods=["POST"])
@require_auth
def api_bnetz_upload():
    """Upload a BNetzA Messprotokoll PDF, parse it, and store the results."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = f.filename.lower()
    is_csv = filename.endswith(".csv")
    is_pdf = filename.endswith(".pdf") or (f.content_type and f.content_type == "application/pdf")

    if not is_csv and not is_pdf:
        return jsonify({"error": "Only PDF and CSV files are accepted"}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_ATTACHMENT_SIZE:
        return jsonify({"error": "File too large (max 10 MB)"}), 400

    lang = _get_lang()
    t = get_translations(lang)

    if is_csv:
        try:
            from .bnetz_csv_parser import parse_bnetz_csv
            csv_content = file_bytes.decode("utf-8-sig")
            parsed = parse_bnetz_csv(csv_content)
        except (ValueError, UnicodeDecodeError) as e:
            return jsonify({"error": t.get("bnetz_parse_error", str(e))}), 400
        measurement_id = _storage.save_bnetz_measurement(parsed, pdf_bytes=None, source="upload")
    else:
        if not file_bytes[:5] == b"%PDF-":
            return jsonify({"error": "Not a valid PDF file"}), 400
        try:
            from .bnetz_parser import parse_bnetz_pdf
            parsed = parse_bnetz_pdf(file_bytes)
        except ValueError as e:
            return jsonify({"error": t.get("bnetz_parse_error", str(e))}), 400
        measurement_id = _storage.save_bnetz_measurement(parsed, file_bytes, source="upload")

    audit_log.info(
        "BNetzA measurement uploaded: ip=%s id=%d provider=%s date=%s type=%s",
        _get_client_ip(), measurement_id,
        parsed.get("provider", "?"), parsed.get("date", "?"),
        "csv" if is_csv else "pdf",
    )
    return jsonify({"id": measurement_id, "parsed": parsed}), 201


@app.route("/api/bnetz/measurements")
@require_auth
def api_bnetz_list():
    """Return list of BNetzA measurements (without PDF blob)."""
    if not _storage:
        return jsonify([])
    limit = request.args.get("limit", 50, type=int)
    return jsonify(_storage.get_bnetz_measurements(limit=limit))


@app.route("/api/bnetz/pdf/<int:measurement_id>")
@require_auth
def api_bnetz_pdf(measurement_id):
    """Download the original BNetzA Messprotokoll PDF."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    pdf = _storage.get_bnetz_pdf(measurement_id)
    if not pdf:
        return jsonify({"error": "Not found"}), 404
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"bnetz_messprotokoll_{measurement_id}.pdf",
    )


@app.route("/api/bnetz/<int:measurement_id>", methods=["DELETE"])
@require_auth
def api_bnetz_delete(measurement_id):
    """Delete a BNetzA measurement."""
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_bnetz_measurement(measurement_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("BNetzA measurement deleted: ip=%s id=%d", _get_client_ip(), measurement_id)
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


# ── Cross-Source Correlation API ──

@app.route("/api/correlation")
@require_auth
def api_correlation():
    """Return unified timeline with data from all sources for cross-source correlation.
    Query params:
      hours: int (default 24, max 168)
      sources: comma-separated list of modem,speedtest,events (default all)
    """
    if not _storage:
        return jsonify([])
    hours = request.args.get("hours", 24, type=int)
    hours = max(1, min(hours, 168))
    end_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    start_ts = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")

    sources_param = request.args.get("sources", "")
    if sources_param:
        valid = {"modem", "speedtest", "events", "bnetz"}
        sources = valid & set(s.strip() for s in sources_param.split(","))
        if not sources:
            sources = valid
    else:
        sources = None

    timeline = _storage.get_correlation_timeline(start_ts, end_ts, sources)

    # Enrich speedtest entries with closest modem health
    modem_entries = [e for e in timeline if e["source"] == "modem"]
    for entry in timeline:
        if entry["source"] == "speedtest" and modem_entries:
            closest = min(modem_entries, key=lambda m: abs(
                datetime.fromisoformat(m["timestamp"]).timestamp() -
                datetime.fromisoformat(entry["timestamp"]).timestamp()
            ))
            delta_min = abs(
                datetime.fromisoformat(closest["timestamp"]).timestamp() -
                datetime.fromisoformat(entry["timestamp"]).timestamp()
            ) / 60
            if delta_min <= 120:
                entry["modem_health"] = closest.get("health")
                entry["modem_ds_snr_min"] = closest.get("ds_snr_min")
                entry["modem_ds_power_avg"] = closest.get("ds_power_avg")

    return jsonify(timeline)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'"
    )
    return response


@app.route("/api/report")
@require_auth
def api_report():
    """Generate a PDF incident report."""
    from .report import generate_report

    state = get_state()
    analysis = state.get("analysis")
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

    conn_info = state.get("connection_info") or {}
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

    analysis = get_state().get("analysis")
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

    include_bnetz = request.args.get("include_bnetz", "false") == "true"
    bnetz_id = request.args.get("bnetz_id", None, type=int)

    bnetz_data = None
    if _storage and (include_bnetz or bnetz_id):
        if bnetz_id:
            all_bnetz = _storage.get_bnetz_measurements(limit=100)
            bnetz_data = next((m for m in all_bnetz if m["id"] == bnetz_id), None)
        else:
            in_range = _storage.get_bnetz_in_range(start_ts, end_ts)
            # Prefer most recent with deviation
            for m in reversed(in_range):
                if m.get("verdict_download") == "deviation" or m.get("verdict_upload") == "deviation":
                    bnetz_data = m
                    break
            if not bnetz_data and in_range:
                bnetz_data = in_range[-1]

    text = generate_complaint_text(
        snapshots, config, None, lang,
        customer_name, customer_number, customer_address,
        bnetz_data=bnetz_data,
    )
    return jsonify({"text": text, "lang": lang})


@app.route("/health")
def health():
    """Simple health check endpoint."""
    state = get_state()
    if state["analysis"]:
        return {"status": "ok", "docsis_health": state["analysis"]["summary"]["health"]}
    return {"status": "ok", "docsis_health": "waiting"}
