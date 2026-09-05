"""Flask web UI for DOCSight – DOCSIS channel monitoring."""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable
from urllib.parse import urlencode

from flask import current_app, render_template, request, jsonify, redirect, session, send_from_directory, url_for
from markupsafe import Markup
from zoneinfo import available_timezones

from .config import DEFAULTS, MODULE_SECRET_KEYS, PASSWORD_MASK, POLL_MIN, POLL_MAX
from .analyzer import get_thresholds
from .base_path import normalize_base_path
from . import signal_health_view
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
from .web_auth import require_auth, _get_admin_password, _authenticate_login, _get_login_csrf_token, _sync_auth_state

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


def login():
    _config_manager = get_config_manager()
    _sync_auth_state()
    if not _get_admin_password():
        return redirect(url_for("index"))
    lang = _get_lang()
    t = get_translations(lang)
    theme = _config_manager.get_theme() if _config_manager else "dark"
    error = None
    status = 200
    csrf_token = _get_login_csrf_token()
    if request.method == "POST":
        error_key, status = _authenticate_login()
        if error_key is None:
            return redirect(url_for("index"))
        fallback = (
            "Too many attempts. Try again later."
            if error_key == "login_rate_limited" else "Invalid password"
        )
        error = t.get(error_key, fallback)
    return render_template("login.html", t=t, lang=lang, theme=theme, error=error, csrf_token=csrf_token), status


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
    auth_enabled = bool(_get_admin_password())
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
        uncorr_pct=signal_health_view.compute_uncorr_pct(analysis),
        has_us_ofdma=signal_health_view.has_us_ofdma(analysis),
        device_info=dev_info,
        demo_mode=demo_mode,
        gaming_quality_enabled=gaming_quality_enabled,
        segment_utilization_enabled=segment_utilization_enabled,
        gaming_index=gaming_index,
        is_fritzbox=is_fritzbox,
        bnetz_enabled=bnetz_enabled,
        bnetz_latest=bnetz_latest,
        metric_ranges=signal_health_view.build_metric_ranges(analysis, get_thresholds()),
        home_snr_display=signal_health_view.build_home_snr_display_context(analysis),
        home_modulation_context=signal_health_view.build_home_modulation_context(analysis),
        capacity_context=signal_health_view.build_capacity_context(analysis, booked_download, booked_upload),
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
