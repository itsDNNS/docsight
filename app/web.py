"""Flask web UI for DOCSight – DOCSIS channel monitoring."""

import functools
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

from flask import Flask, render_template, request, jsonify, redirect, session
from werkzeug.security import check_password_hash

from .config import POLL_MIN, POLL_MAX
from .gaming_index import compute_gaming_index
from .i18n import get_translations, LANGUAGES, LANG_FLAGS

_IANA_REGIONS = {"Africa", "America", "Antarctica", "Arctic", "Asia",
                 "Atlantic", "Australia", "Europe", "Indian", "Pacific"}

def _get_iana_timezones():
    """Return sorted list of IANA timezone names (no POSIX abbreviations)."""
    from zoneinfo import available_timezones
    return ["UTC"] + sorted(
        tz for tz in available_timezones()
        if tz.split("/")[0] in _IANA_REGIONS
    )

from .tz import guess_iana_timezone as _guess_iana_timezone

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


def _get_tz_name():
    """Get configured IANA timezone name."""
    if _config_manager:
        tz = _config_manager.get("timezone")
        if tz:
            return tz
    from .tz import guess_iana_timezone
    return guess_iana_timezone()


def _localize_timestamps(data, keys=("timestamp", "created_at", "updated_at", "last_used_at")):
    """Convert UTC timestamps to local time in-place for API responses.

    Works on dicts and lists of dicts. Modifies data in-place and returns it.
    """
    from .tz import to_local
    tz = _get_tz_name()
    if not tz:
        return data
    if isinstance(data, dict):
        for k in keys:
            if k in data and data[k] and isinstance(data[k], str) and data[k].endswith("Z"):
                data[k] = to_local(data[k], tz)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for k in keys:
                    if k in item and item[k] and isinstance(item[k], str) and item[k].endswith("Z"):
                        item[k] = to_local(item[k], tz)
    return data


# ── Jinja2 Filters for timestamp display ──

def _jinja_localtime(value):
    """Jinja2 filter: convert UTC timestamp to local display time."""
    if not value or not isinstance(value, str):
        return value
    from .tz import to_local
    tz = _get_tz_name()
    return to_local(value, tz) if tz else value.rstrip("Z")


def _jinja_localiso(value):
    """Jinja2 filter: convert UTC timestamp to local ISO format (no Z)."""
    return _jinja_localtime(value)


app.jinja_env.filters["localtime"] = _jinja_localtime
app.jinja_env.filters["localiso"] = _jinja_localiso


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
_module_loader = None


def get_storage():
    """Get the storage instance (set at runtime via init_storage)."""
    return _storage


def get_config_manager():
    """Get the config manager (set at runtime via init_config)."""
    return _config_manager


def get_modem_collector():
    """Get the modem collector (set at runtime via init_collector)."""
    return _modem_collector


def get_collectors():
    """Get all collectors (set at runtime via init_collectors)."""
    return _collectors


def get_module_loader():
    """Get the module loader instance."""
    return _module_loader


def get_on_config_changed():
    """Get the config changed callback."""
    return _on_config_changed


def get_last_manual_poll():
    """Get the timestamp of the last manual poll."""
    return _last_manual_poll


def set_last_manual_poll(value):
    """Set the timestamp of the last manual poll."""
    global _last_manual_poll
    _last_manual_poll = value


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


def init_modules(module_loader):
    """Set the module loader instance."""
    global _module_loader
    _module_loader = module_loader


def setup_module_templates(module_loader):
    """Add module template directories to Jinja2's search path."""
    from jinja2 import FileSystemLoader, ChoiceLoader

    loaders = [app.jinja_loader]  # keep default loader first
    for mod in module_loader.get_enabled_modules():
        tpl_dir = os.path.join(mod.path, "templates")
        if os.path.isdir(tpl_dir):
            loaders.append(FileSystemLoader(tpl_dir))
    if len(loaders) > 1:
        app.jinja_loader = ChoiceLoader(loaders)


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
    """Check if auth is enabled and user is not logged in.

    Also checks for valid Bearer token in Authorization header.
    Returns True if authentication is required but not provided.
    """
    if not _config_manager:
        return False
    admin_pw = _config_manager.get("admin_password", "")
    if not admin_pw:
        return False
    if session.get("authenticated"):
        return False
    # Check Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and _storage:
        token = auth_header[7:]
        token_info = _storage.validate_api_token(token)
        if token_info:
            request._api_token = token_info
            return False
    return True


def require_auth(f):
    """Decorator: redirect to /login or return 401 JSON for API paths."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if _auth_required():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def _require_session_auth(f):
    """Decorator: only allow session-based login, no API tokens."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not _config_manager or not _config_manager.get("admin_password", ""):
            return f(*args, **kwargs)
        if not session.get("authenticated"):
            # Token auth is not sufficient for this endpoint
            if getattr(request, "_api_token", None) or request.headers.get("Authorization", "").startswith("Bearer "):
                return jsonify({"error": "Session authentication required"}), 403
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
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
    """Make auth_enabled and module info available in all templates."""
    auth_enabled = bool(_config_manager and _config_manager.get("admin_password", ""))
    modules = _module_loader.get_enabled_modules() if _module_loader else []

    # Resolve active theme module's CSS variables
    active_theme_data = None
    if _module_loader and _config_manager:
        active_id = _config_manager.get("active_theme", "")
        theme_modules = _module_loader.get_theme_modules()
        active_mod = None
        for m in theme_modules:
            if m.enabled and m.theme_data:
                if m.id == active_id:
                    active_mod = m
                    break
                if active_mod is None:
                    active_mod = m  # fallback to first
        if active_mod:
            active_theme_data = active_mod.theme_data

    return {
        "auth_enabled": auth_enabled,
        "version": APP_VERSION,
        "update_available": _check_for_update(),
        "modules": modules,
        "active_theme_data": active_theme_data,
    }


def update_state(analysis=None, error=None, poll_interval=None, connection_info=None, device_info=None, speedtest_latest=None, weather_latest=None):
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
        if weather_latest is not None:
            _state["weather_latest"] = weather_latest


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
    bnetz_latest = None
    if _storage and bnetz_enabled:
        try:
            from app.modules.bnetz.storage import BnetzStorage
            _bs = BnetzStorage(_storage.db_path)
            bnetz_latest = _bs.get_latest_bnetz()
        except (ImportError, Exception):
            pass

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


@app.route("/health")
def health():
    """Simple health check endpoint."""
    if _state["analysis"]:
        return {"status": "ok", "docsis_health": _state["analysis"]["summary"]["health"], "version": APP_VERSION}
    return {"status": "ok", "docsis_health": "waiting", "version": APP_VERSION}


@app.route("/setup")
def setup():
    if _config_manager and (_config_manager.is_configured() or _config_manager.is_demo_mode()):
        return redirect("/")
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    from .drivers import DRIVER_REGISTRY, DRIVER_DISPLAY_NAMES
    modem_types = sorted([(k, DRIVER_DISPLAY_NAMES.get(k, k)) for k in DRIVER_REGISTRY], key=lambda x: x[1])
    iana_tz = _guess_iana_timezone()
    return render_template("setup.html", config=config, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, modem_types=modem_types, timezones=_get_iana_timezones(), iana_tz=iana_tz)


@app.route("/settings")
@require_auth
def settings():
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    from .drivers import DRIVER_REGISTRY, DRIVER_DISPLAY_NAMES
    modem_types = sorted([(k, DRIVER_DISPLAY_NAMES.get(k, k)) for k in DRIVER_REGISTRY], key=lambda x: x[1])
    demo_mode = _config_manager.is_demo_mode() if _config_manager else False
    iana_tz = _guess_iana_timezone()
    # Warn if server TZ looks like a POSIX abbreviation (no DST support)
    tz_is_posix = bool(tz_name) and "/" not in tz_name and tz_name not in ("UTC",)
    all_modules = _module_loader.get_modules() if _module_loader else []
    return render_template("settings.html", config=config, theme=theme, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, modem_types=modem_types, demo_mode=demo_mode, timezones=_get_iana_timezones(), iana_tz=iana_tz, tz_is_posix=tz_is_posix, all_modules=all_modules)


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
        "img-src 'self' data: blob: https:; "
        "connect-src 'self'"
    )
    return response


# ── Blueprint Registration ──
from .blueprints import register_blueprints
register_blueprints(app)

