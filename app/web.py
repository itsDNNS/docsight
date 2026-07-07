"""Flask web UI for DOCSight – DOCSIS channel monitoring."""

import functools
import logging
import math
import os
import re
import secrets
import stat
import threading
import time
from datetime import datetime, timedelta

import requests as _requests

from flask import Flask, render_template, request, jsonify, redirect, session, send_from_directory
from jinja2 import FileSystemLoader, ChoiceLoader
from markupsafe import Markup
from werkzeug.security import check_password_hash
from zoneinfo import available_timezones

from .config import POLL_MIN, POLL_MAX
from .analyzer import get_thresholds
from .docsis_utils import qam_rank
from .gaming_index import compute_gaming_index
from .glossary import (
    GLOSSARY_LEVELS,
    get_glossary_categories,
    get_glossary_term,
    get_glossary_terms,
    get_related_terms,
)
from .i18n import get_translations, LANGUAGES, LANG_FLAGS
from .maintainer_notices import coerce_dismissed_notice_ids, get_active_notices
from .tz import guess_iana_timezone as _guess_iana_timezone, get_tz_name as _get_public_tz_name, to_local as _to_local
from .version import get_app_version

_IANA_REGIONS = {"Africa", "America", "Antarctica", "Arctic", "Asia",
                 "Atlantic", "Australia", "Europe", "Indian", "Pacific"}

def _get_iana_timezones():
    """Return sorted list of IANA timezone names (no POSIX abbreviations)."""
    return ["UTC"] + sorted(
        tz for tz in available_timezones()
        if tz.split("/")[0] in _IANA_REGIONS
    )
def _server_tz_info():
    """Return server timezone name and UTC offset in minutes."""
    now = datetime.now().astimezone()
    name = now.strftime("%Z") or time.tzname[0] or "UTC"
    offset_min = int(now.utcoffset().total_seconds() // 60)
    return name, offset_min

log = logging.getLogger("docsis.web")
audit_log = logging.getLogger("docsis.audit")

_THEME_COLLECTIONS = [
    {
        "key": "signature",
        "title_key": "theme_collection_signature",
        "title_fallback": "Signature Themes",
        "description_key": "theme_collection_signature_desc",
        "description_fallback": "DOCSight's built-in identity themes",
        "ids": (
            "docsight.theme_classic",
            "docsight.theme_tribu",
            "docsight.theme_ocean",
        ),
    },
    {
        "key": "community",
        "title_key": "theme_collection_community",
        "title_fallback": "Community Favorites",
        "description_key": "theme_collection_community_desc",
        "description_fallback": "Popular palettes inspired by widely loved developer themes",
        "ids": (
            "docsight.theme_one_dark",
            "docsight.theme_dracula",
            "docsight.theme_catppuccin_mocha",
            "docsight.theme_tokyo_night",
            "docsight.theme_nord",
            "docsight.theme_synthwave",
            "docsight.theme_gruvbox",
        ),
    },
    {
        "key": "playful",
        "title_key": "theme_collection_playful",
        "title_fallback": "Easter Eggs",
        "description_key": "theme_collection_playful_desc",
        "description_fallback": "Delight-first themes for fun installs and screenshots",
        "ids": (
            "docsight.theme_matrix",
            "docsight.theme_amber_terminal",
            "docsight.theme_gameboy",
            "docsight.theme_doom",
        ),
    },
]

_THEME_COLLECTION_INDEX = {
    theme_id: (collection["key"], position)
    for collection in _THEME_COLLECTIONS
    for position, theme_id in enumerate(collection["ids"])
}


def _build_theme_collections(theme_modules):
    """Group theme modules into curated gallery collections."""
    grouped = {collection["key"]: [] for collection in _THEME_COLLECTIONS}

    for mod in theme_modules:
        collection_key = _THEME_COLLECTION_INDEX.get(mod.id, ("community", 999))[0]
        grouped.setdefault(collection_key, []).append(mod)

    collections = []
    for collection in _THEME_COLLECTIONS:
        modules = grouped.get(collection["key"], [])
        if not modules:
            continue
        modules.sort(
            key=lambda mod: (
                _THEME_COLLECTION_INDEX.get(mod.id, (collection["key"], 999))[1],
                mod.name.lower(),
            )
        )
        collections.append({
            **collection,
            "modules": modules,
        })

    return collections

# ── Login rate limiting (in-memory) ──
_login_attempts = {}  # IP -> [timestamp, ...]
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 900  # 15 min
_LOGIN_LOCKOUT_BASE = 30  # seconds, doubles each excess attempt
_LOGIN_MAX_TRACKED_IPS = 2048
_LOGIN_CSRF_SESSION_KEY = "login_csrf_token"


def _get_client_ip():
    """Get client IP from request.remote_addr.

    When REVERSE_PROXY is configured, Werkzeug's ProxyFix middleware
    rewrites remote_addr from trusted X-Forwarded-For headers before
    the request reaches Flask.  Without ProxyFix the raw TCP peer
    address is used, which prevents X-Forwarded-For spoofing.
    """
    return request.remote_addr or "unknown"


def _prune_login_attempts(now=None):
    """Drop expired and oldest login-attempt buckets to keep memory bounded."""
    now = now or time.time()
    expired = [ip for ip, attempts in _login_attempts.items() if not [t for t in attempts if now - t < _LOGIN_WINDOW]]
    for ip in expired:
        _login_attempts.pop(ip, None)

    for ip, attempts in list(_login_attempts.items()):
        _login_attempts[ip] = [t for t in attempts if now - t < _LOGIN_WINDOW]

    if len(_login_attempts) <= _LOGIN_MAX_TRACKED_IPS:
        return

    oldest_first = sorted(
        _login_attempts,
        key=lambda ip: _login_attempts[ip][-1] if _login_attempts[ip] else 0,
    )
    for ip in oldest_first[: len(_login_attempts) - _LOGIN_MAX_TRACKED_IPS]:
        _login_attempts.pop(ip, None)


def _check_login_rate_limit(ip):
    """Return seconds until retry allowed, or 0 if not limited."""
    now = time.time()
    _prune_login_attempts(now)
    attempts = _login_attempts.get(ip, [])
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        excess = len(attempts) - _LOGIN_MAX_ATTEMPTS
        lockout = _LOGIN_LOCKOUT_BASE * (2 ** min(excess, 8))
        remaining = lockout - (now - attempts[-1])
        if remaining > 0:
            return remaining
    return 0


def _record_failed_login(ip):
    """Record a failed login attempt."""
    now = time.time()
    _prune_login_attempts(now)
    _login_attempts.setdefault(ip, []).append(now)
    _prune_login_attempts(now)


def _get_login_csrf_token():
    """Return the session-bound token used by the login form."""
    token = session.get(_LOGIN_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_LOGIN_CSRF_SESSION_KEY] = token
    return token


def _valid_login_csrf_token(candidate):
    """Validate the submitted login CSRF token against the session token."""
    token = session.get(_LOGIN_CSRF_SESSION_KEY)
    return bool(
        token and candidate
        and secrets.compare_digest(token.encode("utf-8"), candidate.encode("utf-8"))
    )

APP_VERSION = get_app_version()

# GitHub update check (background, never blocks page loads)
_update_cache = {"latest": None, "checked_at": 0, "checking": False}
_UPDATE_CACHE_TTL = 3600  # 1 hour

def _check_for_update():
    """Return cached update info. Triggers background check if stale."""
    update_checks_enabled = getattr(_config_manager, "is_update_check_enabled", None)
    if not callable(update_checks_enabled) or not update_checks_enabled():
        return None
    now = time.time()
    if now - _update_cache["checked_at"] < _UPDATE_CACHE_TTL:
        return _update_cache["latest"]
    if APP_VERSION == "dev":
        return None
    if not _update_cache["checking"]:
        _update_cache["checking"] = True
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
    """Compare date-based version strings (e.g. '2026-02-16.1' > '2026-02-13.8').

    Splits on '.' to compare the date part lexicographically and the
    trailing build number numerically so that '.10' > '.9'.
    """
    def _parts(v):
        # "2026-02-16.1" -> ("2026-02-16", 1)
        dot = v.rfind(".")
        if dot == -1:
            return (v, 0)
        date_part = v[:dot]
        try:
            build = int(v[dot + 1:])
        except ValueError:
            build = 0
        return (date_part, build)

    return _parts(latest) > _parts(current)


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
_STRIP_TAGS_RE = re.compile(r"<(?!/?(?:b|a|strong|em|br)\b)[^>]+>", re.IGNORECASE)
_CLOSE_TAG_RE = re.compile(r"</(a|b|strong|em|br)\s[^>]*>", re.IGNORECASE)
_OPEN_TAG_RE = re.compile(r"<(a|b|strong|em|br)([\s/][^>]*)?>", re.IGNORECASE)
_HREF_VAL_RE = re.compile(r'href\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))', re.IGNORECASE)
_SAFE_HREF_RE = re.compile(r'^(?:https?://|#|/(?!/))[\x20-\x7E]*$', re.IGNORECASE)


def _clean_tag(match: re.Match) -> str:
    """Strip all attributes from allowed tags, except safe href on <a>."""
    tag_name = match.group(1).lower()
    attrs = match.group(2) or ""

    if tag_name != "a" or not attrs.strip():
        return f"<{tag_name}>"

    # Extract and validate href
    href_match = _HREF_VAL_RE.search(attrs)
    if not href_match:
        return "<a>"

    href_val = href_match.group(1) or href_match.group(2) or href_match.group(3) or ""
    # Strip control characters and HTML entities that could hide javascript:
    stripped = re.sub(r'[\x00-\x1f]|&#?\w+;', '', href_val)
    if _SAFE_HREF_RE.match(stripped):
        return f'<a href="{stripped}">'
    return '<a href="#">'


@app.template_filter("safe_html")
def safe_html_filter(value):
    """Allow only <b>, <a>, <strong>, <em>, <br> tags — strip everything else.

    On allowed tags, all attributes are removed except href on <a>.
    href values must match an allowlist (https://, http://, #, /).
    """
    cleaned = _STRIP_TAGS_RE.sub("", str(value))
    cleaned = _CLOSE_TAG_RE.sub(lambda m: f"</{m.group(1)}>", cleaned)
    cleaned = _OPEN_TAG_RE.sub(_clean_tag, cleaned)
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


@app.template_filter("fmt_uptime")
def format_uptime(seconds):
    """Format uptime seconds to human-readable string: '3d 12h 5m'."""
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return ""
    if seconds < 0:
        return ""
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


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
    return _get_public_tz_name(_config_manager)


def _localize_timestamps(data, keys=("timestamp", "created_at", "updated_at", "last_used_at")):
    """Convert UTC timestamps to local time in-place for API responses.

    Works on dicts and lists of dicts. Modifies data in-place and returns it.
    """
    tz = _get_tz_name()
    if not tz:
        return data
    if isinstance(data, dict):
        for k in keys:
            if k in data and data[k] and isinstance(data[k], str) and data[k].endswith("Z"):
                data[k] = _to_local(data[k], tz)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for k in keys:
                    if k in item and item[k] and isinstance(item[k], str) and item[k].endswith("Z"):
                        item[k] = _to_local(item[k], tz)
    return data


# ── Jinja2 Filters for timestamp display ──

def _jinja_localtime(value):
    """Jinja2 filter: convert UTC timestamp to local display time."""
    if not value or not isinstance(value, str):
        return value
    tz = _get_tz_name()
    return _to_local(value, tz) if tz else value.rstrip("Z")


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


def _get_dismissed_notice_ids():
    """Return locally persisted maintainer notice dismissals."""
    if not _config_manager:
        return []
    return coerce_dismissed_notice_ids(_config_manager.get("dismissed_notice_ids", []))


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
    csrf_token = _get_login_csrf_token()
    if request.method == "POST":
        ip = _get_client_ip()
        if not _valid_login_csrf_token(request.form.get("csrf_token", "")):
            _record_failed_login(ip)
            audit_log.warning("Login rejected: invalid csrf token for ip=%s", ip)
            error = t.get("login_failed", "Invalid password")
            return render_template("login.html", t=t, lang=lang, theme=theme, error=error, csrf_token=csrf_token), 400
        wait = _check_login_rate_limit(ip)
        if wait > 0:
            audit_log.warning("Login rate-limited: ip=%s (retry in %ds)", ip, int(wait))
            error = t.get("login_rate_limited", "Too many attempts. Try again later.")
            return render_template("login.html", t=t, lang=lang, theme=theme, error=error, csrf_token=csrf_token)
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
            session.pop(_LOGIN_CSRF_SESSION_KEY, None)
            audit_log.info("Login successful: ip=%s", ip)
            return redirect("/")
        _record_failed_login(ip)
        audit_log.warning("Login failed: ip=%s", ip)
        error = t.get("login_failed", "Invalid password")
    return render_template("login.html", t=t, lang=lang, theme=theme, error=error, csrf_token=csrf_token)


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
    active_theme_id = ""
    if _module_loader and _config_manager:
        active_id = _config_manager.get("active_theme", "")
        theme_modules = _module_loader.get_theme_modules()
        active_mod = None
        classic_mod = None
        first_with_data = None
        for m in theme_modules:
            if m.theme_data:
                if first_with_data is None:
                    first_with_data = m
                if m.id == "docsight.theme_classic":
                    classic_mod = m
                if m.id == active_id:
                    active_mod = m
                    break
        if active_mod is None:
            active_mod = classic_mod or first_with_data
        if active_mod:
            active_theme_data = active_mod.theme_data
            active_theme_id = active_mod.id

    # All themes with loaded data (enabled + disabled) for settings gallery
    all_theme_modules = [
        m for m in (_module_loader.get_theme_modules() if _module_loader else [])
        if m.theme_data
    ]
    theme_collections = _build_theme_collections(all_theme_modules)

    return {
        "auth_enabled": auth_enabled,
        "version": APP_VERSION,
        "update_available": _check_for_update(),
        "modules": modules,
        "all_theme_modules": all_theme_modules,
        "theme_collections": theme_collections,
        "active_theme_data": active_theme_data,
        "active_theme_id": active_theme_id,
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


def clear_speedtest_latest():
    """Clear the cached speedtest_latest from state (e.g. after server reset)."""
    with _state_lock:
        _state["speedtest_latest"] = None


def get_state() -> dict[str, object]:
    """Return a snapshot of the shared web state (thread-safe)."""
    with _state_lock:
        return dict(_state)


def reset_modem_state():
    """Clear modem-specific dashboard state before switching drivers.

    Keeps unrelated collector data like speedtest/weather cache intact so
    the dashboard only drops the modem-derived sections while a new poll
    is starting.
    """
    with _state_lock:
        _state["analysis"] = None
        _state["last_update"] = None
        _state["error"] = None
        _state["connection_info"] = None
        _state["device_info"] = None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _range_pct(value, minimum, maximum):
    if value is None or maximum <= minimum:
        return 0.0
    return round(max(0.0, min(100.0, (value - minimum) / (maximum - minimum) * 100)), 3)


def _range_band(kind, start, end, minimum, maximum):
    left = _range_pct(start, minimum, maximum)
    right = _range_pct(end, minimum, maximum)
    if right <= left:
        return None
    return {"kind": kind, "left": left, "width": round(right - left, 3)}


def _range_span(observed_min, observed_max, minimum, maximum):
    start = _range_pct(observed_min, minimum, maximum)
    end = _range_pct(observed_max, minimum, maximum)
    return start, round(min(100.0 - start, max(1.6, end - start)), 3)


def _format_range_value(value):
    if value is None:
        return "—"
    return f"{value:g}"


def _choose_threshold(section, preferred_keys):
    if not isinstance(section, dict):
        return {}
    for key in preferred_keys:
        if key in section and isinstance(section[key], dict):
            return section[key]
    for value in section.values():
        if isinstance(value, dict):
            return value
    return {}


def _channel_threshold_candidates(channels, *, snr=False):
    candidates = []
    for channel in channels or []:
        text = " ".join(
            str(channel.get(key, ""))
            for key in ("modulation", "type", "docsis_version")
            if channel.get(key) is not None
        ).upper()
        if snr and _snr_channel_family(channel) == "ofdm":
            candidates.append("ofdm")
        for qam in ("4096QAM", "1024QAM", "256QAM", "64QAM"):
            if qam in text:
                candidates.append(qam)
    return candidates


def _family_modulation_threshold_candidates(family):
    modulation = (family or {}).get("modulation") or {}
    raw_values = []
    for key in ("value", "secondary"):
        if modulation.get(key):
            raw_values.append(modulation.get(key))
    raw_values.extend(modulation.get("distinct") or [])

    candidates = []
    text = " ".join(str(value) for value in raw_values if value is not None).upper()
    for qam in ("4096QAM", "1024QAM", "256QAM", "64QAM"):
        if qam in text:
            candidates.append(qam)
    return candidates


def _power_metric_health(value, threshold):
    if value is None:
        return "good"
    good = threshold.get("good") or [-4.0, 13.0]
    warning = threshold.get("warning") or good
    critical = threshold.get("critical") or [warning[0] - 2.0, warning[1] + 2.0]
    crit_min, crit_max = float(critical[0]), float(critical[1])
    warn_min, warn_max = float(warning[0]), float(warning[1])
    good_min, good_max = float(good[0]), float(good[1])
    if value < crit_min or value > crit_max:
        return "crit"
    if value < warn_min or value > warn_max:
        return "warn"
    if value < good_min or value > good_max:
        return "tolerated"
    return "good"


def _snr_metric_health(value, threshold):
    if value is None:
        return "good"
    crit_min = float(threshold.get("critical_min", 29.0))
    warn_min = float(threshold.get("warning_min", threshold.get("good_min", 33.0)))
    good_min = float(threshold.get("good_min", 33.0))
    if value < crit_min:
        return "crit"
    if value < warn_min:
        return "warn"
    if value < good_min:
        return "tolerated"
    return "good"


def _power_metric_range(value, observed_min, observed_max, threshold, unit):
    good = threshold.get("good") or [-4.0, 13.0]
    warning = threshold.get("warning") or good
    critical = threshold.get("critical") or [warning[0] - 2.0, warning[1] + 2.0]
    crit_min, crit_max = float(critical[0]), float(critical[1])
    warn_min, warn_max = float(warning[0]), float(warning[1])
    good_min, good_max = float(good[0]), float(good[1])
    padding = max((crit_max - crit_min) * 0.06, 0.5)
    minimum = crit_min - padding
    maximum = crit_max + padding
    bands = [
        _range_band("crit", minimum, crit_min, minimum, maximum),
        _range_band("warn", crit_min, warn_min, minimum, maximum),
        _range_band("tolerated", warn_min, good_min, minimum, maximum),
        _range_band("good", good_min, good_max, minimum, maximum),
        _range_band("tolerated", good_max, warn_max, minimum, maximum),
        _range_band("warn", warn_max, crit_max, minimum, maximum),
        _range_band("crit", crit_max, maximum, minimum, maximum),
    ]
    span_start, span_width = _range_span(observed_min, observed_max, minimum, maximum)
    return {
        "health": _power_metric_health(value, threshold),
        "marker": _range_pct(value, minimum, maximum),
        "span_start": span_start,
        "span_width": span_width,
        "low_label": f"{_format_range_value(crit_min)} {unit}",
        "high_label": f"{_format_range_value(crit_max)} {unit}",
        "good_label": f"{_format_range_value(good_min)} - {_format_range_value(good_max)} {unit}",
        "bands": [band for band in bands if band],
    }


def _snr_metric_range(value, observed_min, observed_max, threshold):
    crit_min = float(threshold.get("critical_min", 29.0))
    warn_min = float(threshold.get("warning_min", threshold.get("good_min", 33.0)))
    good_min = float(threshold.get("good_min", 33.0))
    threshold_span = max(good_min - crit_min, 1.0)
    minimum = crit_min - max(threshold_span * 0.4, 1.0)
    maximum = max(
        good_min + threshold_span * 0.9,
        value or good_min,
        observed_max or good_min,
    )
    bands = [
        _range_band("crit", minimum, crit_min, minimum, maximum),
        _range_band("warn", crit_min, warn_min, minimum, maximum),
        _range_band("tolerated", warn_min, good_min, minimum, maximum),
        _range_band("good", good_min, maximum, minimum, maximum),
    ]
    span_start, span_width = _range_span(observed_min, observed_max, minimum, maximum)
    return {
        "health": _snr_metric_health(value, threshold),
        "marker": _range_pct(value, minimum, maximum),
        "span_start": span_start,
        "span_width": span_width,
        "low_label": f"{_format_range_value(crit_min)} dB",
        "high_label": f"{_format_range_value(maximum)} dB",
        "good_label": f"≥ {_format_range_value(good_min)} dB",
        "bands": [band for band in bands if band],
    }


def _error_metric_range(value, threshold):
    pct_threshold = threshold.get("uncorrectable_pct", {}) if isinstance(threshold, dict) else {}
    warning = float(pct_threshold.get("warning", 1.0))
    critical = float(pct_threshold.get("critical", 3.0))
    minimum = 0.0
    maximum = max(critical * 1.4, (value or 0) * 1.15, critical + 0.5)
    bands = [
        _range_band("good", minimum, warning, minimum, maximum),
        _range_band("warn", warning, critical, minimum, maximum),
        _range_band("crit", critical, maximum, minimum, maximum),
    ]
    span_start, span_width = _range_span(value, value, minimum, maximum)
    return {
        "marker": _range_pct(value, minimum, maximum),
        "span_start": span_start,
        "span_width": span_width,
        "low_label": "0%",
        "high_label": f"{_format_range_value(maximum)}%",
        "good_label": f"< {_format_range_value(warning)}%",
        "bands": [band for band in bands if band],
    }


def _build_metric_ranges(analysis):
    if not analysis:
        return {}
    summary = analysis.get("summary", {})
    thresholds = get_thresholds()
    ds_channels = analysis.get("ds_channels", [])
    us_channels = analysis.get("us_channels", [])
    ds_power_threshold = _choose_threshold(
        thresholds.get("downstream_power", {}),
        _channel_threshold_candidates(ds_channels) + ["256QAM", "4096QAM", "1024QAM", "64QAM"],
    )
    us_power_threshold = _choose_threshold(
        thresholds.get("upstream_power", {}),
        (["ofdma"] if any(str(ch.get("docsis_version", "")) in ("3.1", "4.0") for ch in us_channels) else [])
        + ["sc_qam", "ofdma"],
    )
    snr_display = _build_home_snr_display_context(analysis)
    snr_channels = snr_display.get("channels") or ds_channels
    if snr_display.get("kind") == "ofdm":
        snr_candidates = ["ofdm"] + _channel_threshold_candidates(snr_channels, snr=True)
    elif snr_display.get("kind") == "sc_qam":
        snr_candidates = _channel_threshold_candidates(snr_channels, snr=True) + ["256QAM", "1024QAM", "64QAM"]
    else:
        snr_candidates = _channel_threshold_candidates(ds_channels, snr=True) + ["256QAM", "ofdm", "4096QAM", "1024QAM", "64QAM"]
    snr_threshold = _choose_threshold(thresholds.get("snr", {}), snr_candidates)

    ranges = {
        "ds_power": _power_metric_range(
            _to_float(summary.get("ds_power_avg")),
            _to_float(summary.get("ds_power_min")),
            _to_float(summary.get("ds_power_max")),
            ds_power_threshold,
            "dBmV",
        ),
        "us_power": _power_metric_range(
            _to_float(summary.get("us_power_avg")),
            _to_float(summary.get("us_power_min")),
            _to_float(summary.get("us_power_max")),
            us_power_threshold,
            "dBmV",
        ),
        "snr": _snr_metric_range(
            _to_float(snr_display.get("value")),
            _to_float(snr_display.get("min")),
            _to_float(snr_display.get("max")),
            snr_threshold,
        ),
        "errors": _error_metric_range(
            _to_float(summary.get("ds_uncorr_pct")),
            thresholds.get("errors", {}),
        ),
    }

    signal_families = summary.get("signal_families") or {}
    ds_families = (signal_families.get("downstream") or {}).get("families") or {}
    us_families = (signal_families.get("upstream") or {}).get("families") or {}

    def _family_metric_values(family, metric_name):
        metric = (family or {}).get(metric_name) or {}
        if metric.get("available") is False:
            return None
        value = _to_float(metric.get("avg"))
        if value is None:
            return None
        minimum = _to_float(metric.get("min"))
        maximum = _to_float(metric.get("max"))
        return value, minimum if minimum is not None else value, maximum if maximum is not None else value

    def _add_family_snr_range(range_key, family, metric_name, candidates):
        values = _family_metric_values(family, metric_name)
        if not values:
            return
        threshold = _choose_threshold(thresholds.get("snr", {}), candidates)
        ranges[range_key] = _snr_metric_range(values[0], values[1], values[2], threshold)

    def _add_family_power_range(range_key, family, candidates, threshold_group="upstream_power"):
        values = _family_metric_values(family, "power")
        if not values:
            return
        threshold = _choose_threshold(thresholds.get(threshold_group, {}), candidates)
        ranges[range_key] = _power_metric_range(values[0], values[1], values[2], threshold, "dBmV")

    sc_qam_candidates = _family_modulation_threshold_candidates(ds_families.get("sc_qam")) + ["256QAM", "64QAM"]
    ofdm_candidates = ["ofdm"] + _family_modulation_threshold_candidates(ds_families.get("ofdm")) + ["4096QAM", "1024QAM"]
    _add_family_power_range("ds_sc_qam_power", ds_families.get("sc_qam"), sc_qam_candidates, "downstream_power")
    _add_family_power_range("ds_ofdm_power", ds_families.get("ofdm"), ofdm_candidates, "downstream_power")
    _add_family_snr_range("ds_sc_qam_snr", ds_families.get("sc_qam"), "snr", sc_qam_candidates)
    _add_family_snr_range("ds_ofdm_mer", ds_families.get("ofdm"), "mer", ofdm_candidates)
    _add_family_power_range("us_sc_qam_power", us_families.get("sc_qam"), ["sc_qam"])
    _add_family_power_range("us_ofdma_power", us_families.get("ofdma"), ["ofdma"])
    return ranges


def _snr_channel_family(channel):
    """Infer the SNR/MER channel family from explicit channel data first."""
    type_text = str(channel.get("type", "") or "").upper()
    modulation_text = str(channel.get("modulation", "") or "").upper()
    docsis_version = str(channel.get("docsis_version", "") or "").upper()

    if "OFDM" in type_text or "OFDMA" in type_text:
        return "ofdm"
    if "SC-QAM" in type_text or type_text in {"QAM", "SCQAM"}:
        return "sc_qam"
    type_rank = qam_rank(type_text)
    if type_rank:
        if type_rank >= qam_rank("1024QAM") and ("3.1" in docsis_version or "4.0" in docsis_version):
            return "ofdm"
        return "sc_qam"
    if "OFDM" in modulation_text or "OFDMA" in modulation_text:
        return "ofdm"

    modulation_rank = qam_rank(modulation_text)
    if modulation_rank:
        if modulation_rank >= qam_rank("1024QAM") and ("3.1" in docsis_version or "4.0" in docsis_version):
            return "ofdm"
        return "sc_qam"

    profile_text = str(channel.get("profile_modulation", "") or "").upper()
    if "OFDM" in profile_text or "OFDMA" in profile_text:
        return "ofdm"
    profile_rank = qam_rank(profile_text)
    if profile_rank:
        if profile_rank >= qam_rank("1024QAM") and ("3.1" in docsis_version or "4.0" in docsis_version):
            return "ofdm"
        return "sc_qam"

    if "3.1" in docsis_version or "4.0" in docsis_version:
        return "ofdm"
    if "3.0" in docsis_version:
        return "sc_qam"
    return None


def _snr_channel_items(analysis):
    items = []
    for channel in (analysis or {}).get("ds_channels", []):
        snr = _to_float(channel.get("snr"))
        if snr is None:
            continue
        items.append({"channel": channel, "family": _snr_channel_family(channel), "snr": snr})
    return items


def _snr_display_stats(items):
    values = [item["snr"] for item in items]
    if not values:
        return {"value": None, "min": None, "max": None}
    return {
        "value": round(sum(values) / len(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def _build_home_snr_display_context(analysis):
    """Choose the single channel-family basis used by the compact Home SNR/MER card."""
    items = _snr_channel_items(analysis)
    if not items:
        return {
            "kind": "unavailable",
            "label_key": "metric_snr_label_fallback",
            "channels": [],
            "value": None,
            "min": None,
            "max": None,
            "total": 0,
            "selected": 0,
            "sc_qam": 0,
            "ofdm": 0,
            "unknown": 0,
        }

    sc_qam_items = [item for item in items if item["family"] == "sc_qam"]
    ofdm_items = [item for item in items if item["family"] == "ofdm"]
    unknown_items = [item for item in items if item["family"] not in {"sc_qam", "ofdm"}]

    if sc_qam_items:
        kind = "sc_qam"
        selected_items = sc_qam_items
        label_key = "metric_snr_label_sc_qam"
    elif ofdm_items:
        kind = "ofdm"
        selected_items = ofdm_items
        label_key = "metric_snr_label_ofdm"
    else:
        kind = "fallback"
        selected_items = unknown_items
        label_key = "metric_snr_label_fallback"

    stats = _snr_display_stats(selected_items)
    return {
        "kind": kind,
        "label_key": label_key,
        "channels": [item["channel"] for item in selected_items],
        "value": stats["value"],
        "min": stats["min"],
        "max": stats["max"],
        "total": len(items),
        "selected": len(selected_items),
        "sc_qam": len(sc_qam_items),
        "ofdm": len(ofdm_items),
        "unknown": len(unknown_items),
    }


def _build_home_modulation_context(analysis):
    """Build concise Home dashboard modulation context for DS/US channels."""
    summary = analysis.get("summary", {}) if analysis else {}
    issues = set(summary.get("health_issues") or [])

    def _direction_context(direction, channels):
        values = []
        for channel in channels or []:
            raw_mod = channel.get("modulation")
            rank = qam_rank(raw_mod)
            if raw_mod and rank > 0:
                values.append({"value": str(raw_mod), "rank": rank})
        if not values:
            return {
                "dir": direction,
                "health": "missing",
                "primary": None,
                "secondary": None,
                "issue": None,
            }

        values.sort(key=lambda item: item["rank"])
        lowest = values[0]
        highest = values[-1]
        distinct = sorted({item["value"] for item in values}, key=lambda value: qam_rank(value))
        health = "good"
        issue = None
        if direction == "us":
            if "us_modulation_critical" in issues:
                health = "crit"
                issue = "us_modulation_critical"
            elif "us_modulation_marginal" in issues or "us_modulation_warn" in issues:
                health = "warn"
                issue = "us_modulation_marginal"
        return {
            "dir": direction,
            "health": health,
            "primary": lowest["value"],
            "secondary": highest["value"] if highest["value"] != lowest["value"] else None,
            "count": len(values),
            "distinct": distinct,
            "issue": issue,
        }

    return [
        _direction_context("ds", analysis.get("ds_channels", []) if analysis else []),
        _direction_context("us", analysis.get("us_channels", []) if analysis else []),
    ]


def _build_capacity_context(analysis, booked_download=0, booked_upload=0):
    """Build current theoretical channel-capacity context for dashboard views."""
    summary = analysis.get("summary", {}) if analysis else {}

    def _direction(direction, channel_key, summary_key, tariff):
        channels = analysis.get(channel_key, []) if analysis else []
        coverage_all = summary.get("capacity_coverage") or {}
        coverage = dict(coverage_all.get(direction) or {})
        total = int(coverage.get("total", len(channels)) or 0)
        calculated = int(coverage.get("calculated", 0) or 0)
        if not coverage and channels:
            calculated = sum(1 for ch in channels if ch.get("theoretical_bitrate") is not None)
            total = len(channels)
        unsupported = max(0, int(coverage.get("unsupported", total - calculated) or 0))
        capacity = _to_float(summary.get(summary_key))
        tariff_value = _to_float(tariff)
        ratio = round(capacity / tariff_value, 2) if capacity is not None and tariff_value and tariff_value > 0 else None

        if capacity is None or calculated == 0:
            status = "unavailable"
        elif unsupported > 0:
            status = "partial"
        elif ratio is None:
            status = "calculated"
        elif ratio < 1.0:
            status = "below"
        elif ratio < 1.3:
            status = "close"
        else:
            status = "headroom"

        return {
            "direction": direction,
            "capacity_mbps": capacity,
            "tariff_mbps": tariff_value,
            "ratio": ratio,
            "calculated": calculated,
            "total": total,
            "unsupported": unsupported,
            "status": status,
        }

    return {
        "downstream": _direction("downstream", "ds_channels", "ds_capacity_mbps", booked_download),
        "upstream": _direction("upstream", "us_channels", "us_capacity_mbps", booked_upload),
    }


@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")


_GLOSSARY_LEVEL_KEYS = {
    "eli5": {
        "label_key": "glossary_level_eli5",
        "label_default": "ELI5",
        "description_key": "glossary_level_eli5_desc",
        "description_default": "Plain-language first explanation",
    },
    "basic": {
        "label_key": "glossary_level_basic",
        "label_default": "Basic",
        "description_key": "glossary_level_basic_desc",
        "description_default": "Practical meaning for end users",
    },
    "advanced": {
        "label_key": "glossary_level_advanced",
        "label_default": "Advanced",
        "description_key": "glossary_level_advanced_desc",
        "description_default": "Technical context without provider-only assumptions",
    },
    "technician": {
        "label_key": "glossary_level_technician",
        "label_default": "Technician",
        "description_key": "glossary_level_technician_desc",
        "description_default": "Precise DOCSIS and diagnostics boundaries",
    },
}


@app.route("/glossary")
@require_auth
def glossary_page():
    """Render the canonical in-app glossary foundation."""
    lang = _get_lang()
    t = get_translations(lang)
    theme = _config_manager.get_theme() if _config_manager else "dark"
    terms = sorted(get_glossary_terms(lang), key=lambda term: term["title"].casefold())
    categories = get_glossary_categories(lang)
    selected_level = request.args.get("level", "basic")
    if selected_level not in GLOSSARY_LEVELS:
        selected_level = "basic"
    selected_term_id = request.args.get("term") or (terms[0]["id"] if terms else "")
    selected_term = get_glossary_term(selected_term_id, lang) or (terms[0] if terms else None)
    related_terms = get_related_terms(selected_term, lang) if selected_term else []
    level_options = [
        {
            "id": level,
            "label": t.get(config["label_key"], config["label_default"]),
            "description": t.get(config["description_key"], config["description_default"]),
        }
        for level, config in _GLOSSARY_LEVEL_KEYS.items()
    ]
    selected_level_label = next(item["label"] for item in level_options if item["id"] == selected_level)
    category_by_id = {category["id"]: category for category in categories}
    return render_template(
        "glossary.html",
        t=t,
        lang=lang,
        languages=LANGUAGES,
        lang_flags=LANG_FLAGS,
        theme=theme,
        version=APP_VERSION,
        categories=categories,
        category_by_id=category_by_id,
        terms=terms,
        selected_term=selected_term,
        selected_level=selected_level,
        selected_level_label=selected_level_label,
        level_options=level_options,
        related_terms=related_terms,
    )


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
    if demo_mode and not isp_name:
        isp_name = "Vodafone Kabel"
    bqm_configured = bool(
        _config_manager and (
            _config_manager.is_bqm_configured()
            or _config_manager.get("bqm_url")
        )
    )
    smokeping_configured = _config_manager.is_smokeping_configured() if _config_manager else False
    speedtest_configured = _config_manager.is_speedtest_configured() if _config_manager else False
    gaming_quality_enabled = _config_manager.is_gaming_quality_enabled() if _config_manager else False
    segment_utilization_enabled = _config_manager.is_segment_utilization_enabled() if _config_manager else False
    is_fritzbox = (_config_manager.get("modem_type") == "fritzbox") if _config_manager else False
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
        uncorr = analysis.get("summary", {}).get("ds_uncorrectable_errors") or 0
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
        segment_utilization_enabled=segment_utilization_enabled,
        gaming_index=gaming_index,
        is_fritzbox=is_fritzbox,
        bnetz_enabled=bnetz_enabled,
        bnetz_latest=bnetz_latest,
        metric_ranges=_build_metric_ranges(analysis),
        home_snr_display=_build_home_snr_display_context(analysis),
        home_modulation_context=_build_home_modulation_context(analysis),
        capacity_context=_build_capacity_context(analysis, booked_download, booked_upload),
        t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS,
        temperature_unit=_config_manager.get("temperature_unit", "celsius") if _config_manager else "celsius",
        dashboard_notices=get_active_notices(
            dismissed_ids=_get_dismissed_notice_ids(),
            location="dashboard",
        ),
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
    from .drivers import driver_registry
    modem_types = driver_registry.get_available_drivers()
    driver_hints = driver_registry.get_driver_hints()
    iana_tz = _guess_iana_timezone()
    theme = _config_manager.get_theme() if _config_manager else "dark"
    return render_template("setup.html", config=config, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, modem_types=modem_types, driver_hints=driver_hints, timezones=_get_iana_timezones(), iana_tz=iana_tz, theme=theme)


@app.route("/settings")
@require_auth
def settings():
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    from .drivers import driver_registry
    modem_types = driver_registry.get_available_drivers()
    driver_hints = driver_registry.get_driver_hints()
    demo_mode = _config_manager.is_demo_mode() if _config_manager else False
    iana_tz = _guess_iana_timezone()
    # Warn if server TZ looks like a POSIX abbreviation (no DST support)
    tz_is_posix = bool(tz_name) and "/" not in tz_name and tz_name not in ("UTC",)
    all_modules = _module_loader.get_modules() if _module_loader else []
    is_fritzbox = config.get("modem_type") == "fritzbox"
    gaming_quality_enabled = _config_manager.is_gaming_quality_enabled() if _config_manager else False
    segment_utilization_enabled = _config_manager.is_segment_utilization_enabled() if _config_manager else False
    built_in_features = [
        {
            "id": "core.gaming_quality",
            "name": t.get("gaming_quality_label", "Gaming Quality Index"),
            "description": t.get(
                "gaming_quality_hint",
                "Show a gaming quality badge in the dashboard hero card based on latency, jitter, and signal health.",
            ),
            "icon": "gamepad-2",
            "status_label": t.get("modules_enabled" if gaming_quality_enabled else "modules_disabled", "Enabled" if gaming_quality_enabled else "Disabled"),
            "status_class": "badge-success" if gaming_quality_enabled else "badge-muted",
            "manage_section": "system",
            "manage_label": t.get("system", "System"),
        },
        {
            "id": "core.segment_utilization",
            "name": t.get("seg_title", "Segment Utilization"),
            "description": t.get(
                "seg_subtitle",
                "Cable segment utilization from FRITZ!Box monitoring. Requires FRITZ!OS 8.20 or newer on supported cable firmware.",
            ),
            "icon": "gauge",
            "status_label": (
                t.get("modules_requires_fritzbox", "Requires FRITZ!Box")
                if not is_fritzbox else
                t.get(
                    "modules_enabled" if segment_utilization_enabled else "modules_disabled",
                    "Enabled" if segment_utilization_enabled else "Disabled",
                )
            ),
            "status_class": "badge-warning" if not is_fritzbox else ("badge-success" if segment_utilization_enabled else "badge-muted"),
            "manage_section": "connection",
            "manage_label": t.get("step_modem", "Modem"),
        },
    ]
    return render_template(
        "settings.html",
        config=config,
        theme=theme,
        poll_min=POLL_MIN,
        poll_max=POLL_MAX,
        t=t,
        lang=lang,
        languages=LANGUAGES,
        lang_flags=LANG_FLAGS,
        server_tz=tz_name,
        server_tz_offset=tz_offset,
        modem_types=modem_types,
        driver_hints=driver_hints,
        demo_mode=demo_mode,
        timezones=_get_iana_timezones(),
        iana_tz=iana_tz,
        tz_is_posix=tz_is_posix,
        all_modules=all_modules,
        built_in_features=built_in_features,
        app_version=APP_VERSION,
        settings_notices=get_active_notices(
            dismissed_ids=_get_dismissed_notice_ids(),
            location="settings",
        ),
    )


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
from .blueprints import register_blueprints  # noqa: E402
register_blueprints(app)
