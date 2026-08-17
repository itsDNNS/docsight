"""Flask web UI for DOCSight – DOCSIS channel monitoring."""

import functools
import json
import logging
import math
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable, Mapping
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes, hmac
from flask import current_app, render_template, request, jsonify, redirect, session, send_from_directory, url_for
from markupsafe import Markup
from werkzeug.security import check_password_hash
from zoneinfo import available_timezones

from .config import DEFAULTS, MODULE_SECRET_KEYS, PASSWORD_MASK, POLL_MIN, POLL_MAX
from .analyzer import get_thresholds
from .base_path import normalize_base_path
from .docsis_utils import qam_rank
from .desktop_runtime import desktop_runtime_payload
from .desktop_runtime_contract import DESKTOP_MODE_ENV
from .gaming_index import compute_gaming_index
from .glossary import (
    get_glossary_categories,
    get_glossary_term,
    get_glossary_terms,
)
from .i18n import get_translations, LANGUAGES, LANG_FLAGS
from .maintainer_notices import coerce_dismissed_notice_ids, get_active_notices
from .module_loader import module_static_url
from .runtime import current_runtime, _version_newer as _runtime_version_newer
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

DESKTOP_PREVIEW_NOTICE_ID = "docsight-desktop-preview-v0"
DESKTOP_PREVIEW_DOC_URL = "https://github.com/itsDNNS/docsight/blob/main/docs/windows-desktop-preview.md"


def is_desktop_preview_mode() -> bool:
    """Return True when DOCSight runs as the local Desktop Preview build."""
    return os.environ.get(DESKTOP_MODE_ENV) == "1"


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

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 900  # 15 min
_LOGIN_LOCKOUT_BASE = 30  # seconds, doubles each excess attempt
_LOGIN_MAX_TRACKED_IPS = 2048
_LOGIN_CSRF_SESSION_KEY = "login_csrf_token"
_AUTH_MARKER_SESSION_KEY = "auth_marker"
_AUTH_MARKER_CONTEXT = b"docsight-admin-session-v1\0"
_AUTH_STATE_CONTEXT = b"docsight-admin-auth-state-v1\0"
_AUTH_STATE_FILENAME = ".auth_state"
_SESSION_LIFETIME_DEFAULT_DAYS = 30
_SESSION_LIFETIME_MIN_DAYS = 1
_SESSION_LIFETIME_MAX_DAYS = 365


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
    current_runtime().login_rate_limiter.prune(now)


def _check_login_rate_limit(ip):
    """Return seconds until retry allowed, or 0 if not limited."""
    return current_runtime().login_rate_limiter.retry_after(ip)


def _record_failed_login(ip):
    """Record a failed login attempt."""
    current_runtime().login_rate_limiter.record_failure(ip)


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

_UPDATE_CACHE_TTL = 3600  # 1 hour

def _check_for_update():
    """Return cached update info. Triggers background check if stale."""
    return current_runtime().update_checker.latest()

def _version_newer(latest, current):
    """Compare date-based version strings (e.g. '2026-02-16.1' > '2026-02-13.8').

    Splits on '.' to compare the date part lexicographically and the
    trailing build number numerically so that '.10' > '.9'.
    """
    return _runtime_version_newer(latest, current)

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


def safe_html_filter(value):
    """Allow only <b>, <a>, <strong>, <em>, <br> tags — strip everything else.

    On allowed tags, all attributes are removed except href on <a>.
    href values must match an allowlist (https://, http://, #, /).
    """
    cleaned = _STRIP_TAGS_RE.sub("", str(value))
    cleaned = _CLOSE_TAG_RE.sub(lambda m: f"</{m.group(1)}>", cleaned)
    cleaned = _OPEN_TAG_RE.sub(_clean_tag, cleaned)
    return Markup(cleaned)


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


def format_speed_unit(value):
    """Return speed unit: >= 1000 Mbps -> 'GBit/s', else 'MBit/s'."""
    try:
        value = float(value)
    except (ValueError, TypeError):
        return "MBit/s"
    return "GBit/s" if value >= 1000 else "MBit/s"


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
    _config_manager = get_config_manager()
    lang = request.args.get("lang")
    if lang and lang in LANGUAGES:
        return lang
    if _config_manager:
        return _config_manager.get("language", "en")
    return "en"


def _get_setup_lang():
    """Resolve and persist the language for the unconfigured setup route."""
    _config_manager = get_config_manager()
    lang = request.args.get("lang")
    if lang in LANGUAGES:
        if _config_manager:
            _config_manager.save({"language": lang})
        return lang

    if _config_manager and _config_manager.has_stored_value("language"):
        return _config_manager.get("language", DEFAULTS["language"])

    inferred = DEFAULTS["language"]
    for requested, quality in request.accept_languages:
        if quality <= 0:
            continue
        normalized = requested.lower().replace("_", "-")
        if normalized in LANGUAGES:
            inferred = normalized
            break
        base = normalized.split("-", 1)[0]
        if base in LANGUAGES:
            inferred = base
            break

    if _config_manager:
        _config_manager.save({"language": inferred})
    return inferred


def _get_tz_name():
    """Get configured IANA timezone name."""
    return _get_public_tz_name(get_config_manager())


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


def get_storage():
    """Get this application's snapshot storage, if configured."""
    return current_runtime().storage


def get_config_manager():
    """Get this application's configuration manager."""
    return current_runtime().config_manager


def get_modem_collector():
    """Get this application's modem collector, if running."""
    return current_runtime().modem_collector


def get_collectors():
    """Get this application's collectors."""
    return current_runtime().collectors


def get_module_loader():
    """Get the module loader instance."""
    return current_runtime().module_loader


def _get_dismissed_notice_ids():
    """Return locally persisted maintainer notice dismissals."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return []
    return coerce_dismissed_notice_ids(_config_manager.get("dismissed_notice_ids", []))


def get_on_config_changed():
    """Get the config changed callback."""
    return current_runtime().on_config_changed


def get_last_manual_poll():
    """Get the timestamp of the last manual poll."""
    return current_runtime().get_last_manual_poll()


def set_last_manual_poll(value):
    """Set the timestamp of the last manual poll."""
    current_runtime().set_last_manual_poll(value)


def _rotate_session_key():
    """Persist and activate a new signing key, invalidating all old cookies."""
    key = current_runtime().auth_state.rotate_session_key()
    # In-memory activation assumes today's single-process waitress deployment;
    # a future multi-worker server must coordinate shared signing-key rotation.
    current_app.secret_key = key


def _session_lifetime_days(environ: Mapping[str, str] | None = None):
    """Return the safe, bounded operator-configured session lifetime."""
    env = os.environ if environ is None else environ
    configured = env.get("SESSION_LIFETIME_DAYS", "").strip()
    if not configured:
        return _SESSION_LIFETIME_DEFAULT_DAYS
    try:
        days = int(configured)
    except (TypeError, ValueError):
        log.warning(
            "Invalid SESSION_LIFETIME_DAYS; using %d days",
            _SESSION_LIFETIME_DEFAULT_DAYS,
        )
        return _SESSION_LIFETIME_DEFAULT_DAYS
    return max(_SESSION_LIFETIME_MIN_DAYS, min(_SESSION_LIFETIME_MAX_DAYS, days))

def _keyed_sha256_hexdigest(key: bytes, message: bytes) -> str:
    """Return the HMAC-SHA256 of message as lowercase hexadecimal."""
    mac = hmac.HMAC(key, hashes.SHA256())
    mac.update(message)
    return mac.finalize().hex()


def _secret_values_match(left, right):
    """Compare secret representations without timing-sensitive equality."""
    return secrets.compare_digest(
        str(left or "").encode(), str(right or "").encode()
    )


def _admin_password_matches(effective_password, candidate):
    """Safely check whether candidate represents the current admin password."""
    effective_password = str(effective_password or "")
    candidate = str(candidate or "")
    if effective_password.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(effective_password, candidate)
        except (TypeError, ValueError):
            return False
    return _secret_values_match(effective_password, candidate)


def _auth_state_fingerprint(password_representation=None):
    """Return a keyed fingerprint of the effective admin-password state."""
    _config_manager = get_config_manager()
    if password_representation is None:
        password_representation = (
            _config_manager.get("admin_password", "") if _config_manager else ""
        )
    key = current_app.secret_key.encode() if isinstance(current_app.secret_key, str) else current_app.secret_key
    value = _AUTH_STATE_CONTEXT + str(password_representation or "").encode("utf-8")
    return _keyed_sha256_hexdigest(key, value)


def _read_auth_state():
    return current_runtime().auth_state.read_fingerprint()


def _write_auth_state():
    fingerprint = _auth_state_fingerprint()
    current_runtime().auth_state.write_fingerprint(fingerprint)


def _init_auth_state():
    """Create auth state or invalidate cookies after an offline state change."""
    stored = _read_auth_state()
    current = _auth_state_fingerprint()
    if stored is None:
        _write_auth_state()
    elif not _secret_values_match(stored, current):
        _rotate_session_key()
        _write_auth_state()


def bootstrap_auth_state(app, runtime):
    """Initialize durable authentication state for a newly created app."""
    if app.extensions.get("docsight") is not runtime:
        raise RuntimeError("DOCSight runtime is not attached to this application")
    with app.app_context():
        _init_auth_state()


def _sync_auth_state():
    """Observe runtime auth changes and durably invalidate existing cookies."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return
    stored = _read_auth_state()
    current = _auth_state_fingerprint()
    if stored is not None and _secret_values_match(stored, current):
        return
    _rotate_session_key()
    _write_auth_state()


def _admin_session_marker(password_representation=None):
    """Create a keyed, non-reversible marker for the effective password state."""
    _config_manager = get_config_manager()
    if password_representation is None:
        if not _config_manager:
            return ""
        password_representation = _config_manager.get("admin_password", "")
    if not password_representation:
        return ""
    key = current_app.secret_key.encode() if isinstance(current_app.secret_key, str) else current_app.secret_key
    value = _AUTH_MARKER_CONTEXT + str(password_representation).encode("utf-8")
    return _keyed_sha256_hexdigest(key, value)


def _authenticated_session_is_valid():
    """Return True only for a password-bound authenticated browser session."""
    if not session.get("authenticated"):
        return False
    actual = session.get(_AUTH_MARKER_SESSION_KEY, "")
    expected = _admin_session_marker()
    if actual and expected and _secret_values_match(actual, expected):
        return True
    session.clear()
    return False


def _invalidate_admin_sessions():
    """Globally invalidate signed cookies and clear the current request session."""
    _rotate_session_key()
    _write_auth_state()
    # The request cookie was loaded with the prior key. Clearing after rotation
    # makes Flask write the logged-out session using the new key on this response.
    session.clear()


def _auth_required():
    """Check if auth is enabled and user is not logged in.

    Also checks for valid Bearer token in Authorization header.
    Returns True if authentication is required but not provided.
    """
    _config_manager = get_config_manager()
    _storage = get_storage()
    if not _config_manager:
        return False
    _sync_auth_state()
    admin_pw = _config_manager.get("admin_password", "")
    if not admin_pw:
        return False
    if _authenticated_session_is_valid():
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
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _require_session_auth(f):
    """Decorator: only allow session-based login, no API tokens."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        _config_manager = get_config_manager()
        _sync_auth_state()
        if not _config_manager or not _config_manager.get("admin_password", ""):
            return f(*args, **kwargs)
        if not _authenticated_session_is_valid():
            # Token auth is not sufficient for this endpoint
            if getattr(request, "_api_token", None) or request.headers.get("Authorization", "").startswith("Bearer "):
                return jsonify({"error": "Session authentication required"}), 403
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def login():
    _config_manager = get_config_manager()
    _sync_auth_state()
    if not _config_manager or not _config_manager.get("admin_password", ""):
        return redirect(url_for("index"))
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
            success = _secret_values_match(pw, stored)
            if success and not os.environ.get("ADMIN_PASSWORD"):
                # Auto-upgrade plaintext password to hash
                _config_manager.save({"admin_password": pw})
                stored = _config_manager.get("admin_password", "")
                # This is the same credential in a safer representation, so
                # preserve the signing key while rebinding durable auth state.
                _write_auth_state()
                audit_log.info("Auto-upgraded plaintext password to hash for ip=%s", ip)
        if success:
            current_runtime().login_rate_limiter.reset(ip)
            session.permanent = True
            session["authenticated"] = True
            session[_AUTH_MARKER_SESSION_KEY] = _admin_session_marker(stored)
            session.pop(_LOGIN_CSRF_SESSION_KEY, None)
            audit_log.info("Login successful: ip=%s", ip)
            return redirect(url_for("index"))
        _record_failed_login(ip)
        audit_log.warning("Login failed: ip=%s", ip)
        error = t.get("login_failed", "Invalid password")
    return render_template("login.html", t=t, lang=lang, theme=theme, error=error, csrf_token=csrf_token)


def logout():
    session.clear()
    return redirect(url_for("login"))


def inject_browser_url_bootstrap():
    """Expose only the canonical mount path needed by browser URL sinks."""
    return {
        "browser_url_bootstrap": {
            "basePath": normalize_base_path(request.environ.get("SCRIPT_NAME", "")),
        },
    }


def inject_auth():
    """Make auth_enabled and module info available in all templates."""
    _config_manager = get_config_manager()
    _module_loader = get_module_loader()
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
            if m.enabled and not m.error and m.theme_data:
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

    desktop_mode = is_desktop_preview_mode()
    return {
        "auth_enabled": auth_enabled,
        "module_static_url": module_static_url,
        "version": APP_VERSION,
        "update_available": _check_for_update(),
        "modules": modules,
        "all_theme_modules": all_theme_modules,
        "theme_collections": theme_collections,
        "active_theme_data": active_theme_data,
        "active_theme_id": active_theme_id,
        "desktop_mode": desktop_mode,
        "desktop_preview_doc_url": DESKTOP_PREVIEW_DOC_URL,
        "desktop_preview_notice_id": DESKTOP_PREVIEW_NOTICE_ID,
        "desktop_preview_notice_dismissed": desktop_mode and DESKTOP_PREVIEW_NOTICE_ID in _get_dismissed_notice_ids(),
        "demo_mode_forced": bool(
            _config_manager
            and getattr(_config_manager, "is_demo_mode_forced", lambda: False)()
        ),
    }


def update_state(analysis=None, error=None, poll_interval=None, connection_info=None, device_info=None, speedtest_latest=None, weather_latest=None):
    """Update the shared web state from the main loop (thread-safe)."""
    current_runtime().update_state(
        analysis=analysis,
        error=error,
        poll_interval=poll_interval,
        connection_info=connection_info,
        device_info=device_info,
        speedtest_latest=speedtest_latest,
        weather_latest=weather_latest,
    )


def clear_speedtest_latest():
    """Clear the cached speedtest_latest from state (e.g. after server reset)."""
    current_runtime().clear_speedtest_latest()


def get_state() -> dict[str, object]:
    """Return a snapshot of the shared web state (thread-safe)."""
    return current_runtime().get_state()


def reset_modem_state():
    """Clear modem-specific dashboard state before switching drivers.

    Keeps unrelated collector data like speedtest/weather cache intact so
    the dashboard only drops the modem-derived sections while a new poll
    is starting.
    """
    current_runtime().reset_modem_state()


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


def service_worker():
    return send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript")


def web_app_manifest():
    with open(os.path.join(current_app.static_folder, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["id"] = url_for("index")
    response = jsonify(manifest)
    response.mimetype = "application/manifest+json"
    return response


def _build_glossary_context(lang, t, selected_term_id=None):
    """Build static glossary view data for the app shell."""
    terms = sorted(get_glossary_terms(lang), key=lambda term: term["title"].casefold())
    categories = get_glossary_categories(lang)
    selected_term = get_glossary_term(selected_term_id, lang) if selected_term_id else None
    if not selected_term and terms:
        selected_term = terms[0]
    category_by_id = {category["id"]: category for category in categories}
    term_by_id = {term["id"]: term for term in terms}
    return {
        "glossary_terms": terms,
        "glossary_categories": categories,
        "glossary_category_by_id": category_by_id,
        "glossary_term_by_id": term_by_id,
        "glossary_selected_term": selected_term,
    }


@require_auth
def glossary_page():
    """Compatibility endpoint for existing glossary deep links."""
    lang = _get_lang()
    terms = {term["id"] for term in get_glossary_terms(lang)}
    hash_params = {}
    term_id = request.args.get("term", "")
    if term_id in terms:
        hash_params["term"] = term_id
    hash_query = f"?{urlencode(hash_params)}" if hash_params else ""
    return redirect(
        url_for("index", lang=lang, _anchor=f"glossary{hash_query}")
    )


@require_auth
def index():
    _config_manager = get_config_manager()
    _storage = get_storage()
    demo_mode = _config_manager.is_demo_mode() if _config_manager else False
    if _config_manager and not demo_mode and not _config_manager.is_configured():
        return redirect(url_for("setup"))

    theme = _config_manager.get_theme() if _config_manager else "dark"
    lang = _get_lang()
    t = get_translations(lang)

    isp_name = _config_manager.get("isp_name", "") if _config_manager else ""
    report_customer_name = ""
    report_customer_number = ""
    report_customer_address = ""
    if _config_manager and not demo_mode:
        report_customer_name = _config_manager.get("report_customer_name", "")
        report_customer_number = _config_manager.get("report_customer_number", "")
        report_customer_address = _config_manager.get("report_customer_address", "")
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
        report_customer_name=report_customer_name,
        report_customer_number=report_customer_number,
        report_customer_address=report_customer_address,
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
        **_build_glossary_context(lang, t, request.args.get("term")),
    )


def health():
    """Simple health check endpoint."""
    state = get_state()
    if state["analysis"]:
        return {"status": "ok", "docsis_health": state["analysis"]["summary"]["health"], "version": APP_VERSION}
    return {"status": "ok", "docsis_health": "waiting", "version": APP_VERSION}


def desktop_runtime():
    """Return authenticated process identity only for desktop loopback clients."""
    payload, status = desktop_runtime_payload(
        env=os.environ,
        remote_address=request.remote_addr,
        authorization=request.headers.get("Authorization"),
    )
    return jsonify(payload), status


def setup():
    _config_manager = get_config_manager()
    if _config_manager and (_config_manager.is_configured() or _config_manager.is_demo_mode()):
        return redirect(url_for("index"))
    config = _config_manager.get_all(mask_secrets=True) if _config_manager else {}
    lang = _get_setup_lang()
    t = get_translations(lang)
    tz_name, tz_offset = _server_tz_info()
    from .drivers import driver_registry
    modem_types = driver_registry.get_available_drivers()
    driver_hints = driver_registry.get_driver_hints()
    iana_tz = _guess_iana_timezone()
    theme = _config_manager.get_theme() if _config_manager else "dark"
    return render_template("setup.html", config=config, poll_min=POLL_MIN, poll_max=POLL_MAX, t=t, lang=lang, languages=LANGUAGES, lang_flags=LANG_FLAGS, server_tz=tz_name, server_tz_offset=tz_offset, modem_types=modem_types, driver_hints=driver_hints, timezones=_get_iana_timezones(), iana_tz=iana_tz, theme=theme)


@require_auth
def settings():
    _config_manager = get_config_manager()
    _module_loader = get_module_loader()
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
        module_secret_fields=sorted(MODULE_SECRET_KEYS),
        saved_module_secret_fields=sorted(
            key for key in MODULE_SECRET_KEYS if config.get(key) == PASSWORD_MASK
        ),
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


@dataclass(frozen=True)
class RouteSpec:
    rule: str
    endpoint: str
    view: Callable
    methods: tuple[str, ...]


CORE_ROUTES = (
    RouteSpec("/login", "login", login, ("GET", "POST")),
    RouteSpec("/logout", "logout", logout, ("POST",)),
    RouteSpec("/", "index", index, ("GET",)),
    RouteSpec("/glossary", "glossary_page", glossary_page, ("GET",)),
    RouteSpec("/health", "health", health, ("GET",)),
    RouteSpec("/desktop-runtime", "desktop_runtime", desktop_runtime, ("GET",)),
    RouteSpec("/setup", "setup", setup, ("GET",)),
    RouteSpec("/settings", "settings", settings, ("GET",)),
    RouteSpec("/sw.js", "service_worker", service_worker, ("GET",)),
    RouteSpec("/static/manifest.json", "web_app_manifest", web_app_manifest, ("GET",)),
)
CORE_TEMPLATE_FILTERS = {
    "safe_html": safe_html_filter,
    "fmt_k": format_k,
    "fmt_speed_value": format_speed_value,
    "fmt_speed_unit": format_speed_unit,
    "fmt_uptime": format_uptime,
    "localtime": _jinja_localtime,
    "localiso": _jinja_localiso,
}


def install_core_template_hooks(app) -> None:
    """Install non-route template and response hooks on one application."""
    for name, function in CORE_TEMPLATE_FILTERS.items():
        app.add_template_filter(function, name)
    app.context_processor(inject_browser_url_bootstrap)
    app.context_processor(inject_auth)
    app.after_request(add_security_headers)
