"""DOCSIS channel health analysis with configurable thresholds.

Thresholds are loaded from thresholds.json (Vodafone VFKD guidelines).
The file supports per-modulation thresholds for DS power, US power, and SNR.
"""

import json
import logging
import os
import re

log = logging.getLogger("docsis.analyzer")

# --- Load thresholds from JSON ---
_THRESHOLDS_PATH = os.path.join(os.path.dirname(__file__), "thresholds.json")
_thresholds = {}


def _load_thresholds():
    """Load thresholds from JSON file. Falls back to hardcoded defaults."""
    global _thresholds
    try:
        with open(_THRESHOLDS_PATH, "r") as f:
            _thresholds = json.load(f)
        log.info("Loaded thresholds from %s", _THRESHOLDS_PATH)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.warning("Could not load thresholds.json (%s), using defaults", e)
        _thresholds = {}


_MODULATION_ALIASES = {
    "OFDM": "4096QAM",
    "OFDMA": "4096QAM",
}


def _resolve_modulation(modulation, section):
    """Resolve modulation string to a key in thresholds config."""
    if modulation in section:
        return modulation
    return _MODULATION_ALIASES.get(modulation, section.get("_default", "256QAM"))


def _get_ds_power_thresholds(modulation=None):
    """Get DS power thresholds for a given modulation."""
    ds = _thresholds.get("downstream_power", {})
    mod = _resolve_modulation(modulation, ds)
    t = ds.get(mod, {})
    return {
        "good_min": t.get("good_min", -4.0),
        "good_max": t.get("good_max", 13.0),
        "crit_min": t.get("immediate_min", -8.0),
        "crit_max": t.get("immediate_max", 20.0),
    }


def _get_us_power_thresholds(docsis_version=None):
    """Get US power thresholds for a given DOCSIS version."""
    us = _thresholds.get("upstream_power", {})
    default_ver = us.get("_default", "EuroDOCSIS 3.0")
    # Map version strings
    ver = default_ver
    if docsis_version in ("3.1", "DOCSIS 3.1"):
        ver = "DOCSIS 3.1"
    elif docsis_version in ("3.0", "EuroDOCSIS 3.0"):
        ver = "EuroDOCSIS 3.0"
    t = us.get(ver, us.get(default_ver, {}))
    return {
        "good_min": t.get("good_min", 41.0),
        "good_max": t.get("good_max", 47.0),
        "crit_min": t.get("immediate_min", 35.0),
        "crit_max": t.get("immediate_max", 53.0),
    }


def _get_snr_thresholds(modulation=None):
    """Get SNR thresholds for a given modulation."""
    snr = _thresholds.get("snr", {})
    mod = _resolve_modulation(modulation, snr)
    t = snr.get(mod, {})
    return {
        "good_min": t.get("good_min", 33.0),
        "crit_min": t.get("immediate_min", 29.0),
    }


def _get_us_modulation_thresholds():
    """Get upstream modulation QAM order thresholds."""
    us_mod = _thresholds.get("upstream_modulation", {})
    return {
        "critical_max_qam": us_mod.get("critical_max_qam", 4),
        "warning_max_qam": us_mod.get("warning_max_qam", 16),
    }


def _parse_qam_order(modulation_str):
    """Extract QAM order from modulation string. Returns None if unparseable."""
    if not modulation_str:
        return None
    mod = modulation_str.upper().replace("-", "").strip()
    if mod in ("QPSK",):
        return 4
    m = re.match(r"(\d+)\s*QAM", mod)
    if m:
        return int(m.group(1))
    return None


def _get_uncorr_threshold():
    return _thresholds.get("errors", {}).get("uncorrectable_threshold", 10000)


# EuroDOCSIS default symbol rate (kSym/s)
_DEFAULT_SYMBOL_RATE = 5120

_BITS_PER_SYMBOL = {
    4: 2,      # QPSK / 4-QAM
    8: 3,
    16: 4,
    32: 5,
    64: 6,
    128: 7,
    256: 8,
    512: 9,
    1024: 10,
    2048: 11,
    4096: 12,
}


def _channel_bitrate_mbps(modulation_str, symbol_rate_ksym=None):
    """Calculate theoretical bitrate for a channel in Mbit/s.

    Returns None if modulation is unparseable (e.g. OFDMA).
    """
    qam_order = _parse_qam_order(modulation_str)
    if qam_order is None or qam_order not in _BITS_PER_SYMBOL:
        return None
    rate = symbol_rate_ksym or _DEFAULT_SYMBOL_RATE
    return round(rate * _BITS_PER_SYMBOL[qam_order] / 1000, 2)


def get_thresholds():
    """Return the currently loaded thresholds dict (read-only access)."""
    return _thresholds


# Load on module import
_load_thresholds()


def _parse_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _channel_health(issues):
    """Return health string from issue list."""
    if not issues:
        return "good"
    if any("critical" in i for i in issues):
        return "critical"
    return "warning"


def _health_detail(issues):
    """Build a machine-readable detail string from issue list."""
    if not issues:
        return ""
    return " + ".join(issues)


def _assess_ds_channel(ch, docsis_ver):
    """Assess a single downstream channel. Returns (health, health_detail)."""
    issues = []
    raw_power = ch.get("powerLevel")
    modulation = (ch.get("modulation") or ch.get("type") or "").upper().replace("-", "")

    if raw_power is not None:
        power = _parse_float(raw_power)
        pt = _get_ds_power_thresholds(modulation)
        if power < pt["crit_min"] or power > pt["crit_max"]:
            issues.append("power critical")
        elif power < pt["good_min"] or power > pt["good_max"]:
            issues.append("power warning")

    snr_val = None
    if docsis_ver == "3.0" and ch.get("mse"):
        snr_val = abs(_parse_float(ch["mse"]))
    elif docsis_ver == "3.1" and ch.get("mer"):
        snr_val = _parse_float(ch["mer"])

    if snr_val is not None:
        st = _get_snr_thresholds(modulation)
        if snr_val < st["crit_min"]:
            issues.append("snr critical")
        elif snr_val < st["good_min"]:
            issues.append("snr warning")

    return _channel_health(issues), _health_detail(issues)


def _assess_us_channel(ch, docsis_ver="3.0"):
    """Assess a single upstream channel. Returns (health, health_detail)."""
    issues = []
    raw_power = ch.get("powerLevel")

    if raw_power is not None:
        power = _parse_float(raw_power)
        pt = _get_us_power_thresholds(docsis_ver)
        if power < pt["crit_min"]:
            issues.append("power critical low")
        elif power > pt["crit_max"]:
            issues.append("power critical high")
        elif power < pt["good_min"]:
            issues.append("power warning low")
        elif power > pt["good_max"]:
            issues.append("power warning high")

    modulation = ch.get("modulation") or ch.get("type") or ""
    qam_order = _parse_qam_order(modulation)
    if qam_order is not None:
        mt = _get_us_modulation_thresholds()
        if qam_order <= mt["critical_max_qam"]:
            issues.append("modulation critical")
        elif qam_order <= mt["warning_max_qam"]:
            issues.append("modulation warning")

    return _channel_health(issues), _health_detail(issues)


def analyze(data: dict) -> dict:
    """Analyze DOCSIS data and return structured result.

    Returns dict with keys:
        summary: dict of summary metrics
        ds_channels: list of downstream channel dicts
        us_channels: list of upstream channel dicts
    """
    # Handle new driver format (TC4400, Ultra Hub 7, Vodafone Station, etc.)
    # These drivers return {"docsis": "3.1", "downstream": [...], "upstream": [...]}
    # Convert to FritzBox-compatible format for unified processing
    if "downstream" in data and "upstream" in data:
        docsis_version = data.get("docsis", "3.1")
        ds_key = "docsis31" if docsis_version == "3.1" else "docsis30"
        us_key = "docsis31" if docsis_version == "3.1" else "docsis30"
        
        data = {
            "channelDs": {ds_key: data["downstream"]},
            "channelUs": {us_key: data["upstream"]},
        }
    
    ds = data.get("channelDs", {})
    ds31 = ds.get("docsis31", [])
    ds30 = ds.get("docsis30", [])

    us = data.get("channelUs", {})
    us31 = us.get("docsis31", [])
    us30 = us.get("docsis30", [])

    # --- Parse downstream channels ---
    ds_channels = []
    for ch in ds30:
        power = _parse_float(ch.get("powerLevel"))
        snr = abs(_parse_float(ch.get("mse"))) if ch.get("mse") else None
        health, health_detail = _assess_ds_channel(ch, "3.0")
        ds_channels.append({
            "channel_id": ch.get("channelID", 0),
            "frequency": ch.get("frequency", ""),
            "power": power,
            "modulation": ch.get("modulation") or ch.get("type", ""),
            "snr": snr,
            "correctable_errors": ch.get("corrErrors", 0),
            "uncorrectable_errors": ch.get("nonCorrErrors", 0),
            "docsis_version": "3.0",
            "health": health,
            "health_detail": health_detail,
        })
    for ch in ds31:
        raw_power = ch.get("powerLevel")
        power = _parse_float(raw_power) if raw_power is not None else None
        snr = _parse_float(ch.get("mer")) if ch.get("mer") else None
        health, health_detail = _assess_ds_channel(ch, "3.1")
        ds_channels.append({
            "channel_id": ch.get("channelID", 0),
            "frequency": ch.get("frequency", ""),
            "power": power,
            "modulation": ch.get("modulation") or ch.get("type", ""),
            "snr": snr,
            "correctable_errors": ch.get("corrErrors", 0),
            "uncorrectable_errors": ch.get("nonCorrErrors", 0),
            "docsis_version": "3.1",
            "health": health,
            "health_detail": health_detail,
        })

    ds_channels.sort(key=lambda c: c["channel_id"])

    # --- Parse upstream channels ---
    us_channels = []
    for ch in us30:
        health, health_detail = _assess_us_channel(ch, "3.0")
        mod = ch.get("modulation") or ch.get("type", "")
        bitrate = _channel_bitrate_mbps(mod, ch.get("symbolRate"))
        us_channels.append({
            "channel_id": ch.get("channelID", 0),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(ch.get("powerLevel")),
            "modulation": mod,
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.0",
            "health": health,
            "health_detail": health_detail,
            "theoretical_bitrate": bitrate,
        })
    for ch in us31:
        health, health_detail = _assess_us_channel(ch, "3.1")
        mod = ch.get("modulation") or ch.get("type", "")
        bitrate = _channel_bitrate_mbps(mod, ch.get("symbolRate"))
        raw_power = ch.get("powerLevel")
        us_channels.append({
            "channel_id": ch.get("channelID", 0),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(raw_power) if raw_power is not None else None,
            "modulation": mod,
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.1",
            "health": health,
            "health_detail": health_detail,
            "theoretical_bitrate": bitrate,
        })

    us_channels.sort(key=lambda c: c["channel_id"])

    # --- Summary metrics ---
    ds_powers = [c["power"] for c in ds_channels if c["power"] is not None]
    us_powers = [c["power"] for c in us_channels if c["power"] is not None]
    ds_snrs = [c["snr"] for c in ds_channels if c["snr"] is not None]

    total_corr = sum(c["correctable_errors"] for c in ds_channels)
    total_uncorr = sum(c["uncorrectable_errors"] for c in ds_channels)

    us_bitrates = [c["theoretical_bitrate"] for c in us_channels if c["theoretical_bitrate"] is not None]
    us_capacity = round(sum(us_bitrates), 1) if us_bitrates else None

    summary = {
        "ds_total": len(ds_channels),
        "us_total": len(us_channels),
        "ds_power_min": round(min(ds_powers), 1) if ds_powers else 0,
        "ds_power_max": round(max(ds_powers), 1) if ds_powers else 0,
        "ds_power_avg": round(sum(ds_powers) / len(ds_powers), 1) if ds_powers else 0,
        "us_power_min": round(min(us_powers), 1) if us_powers else 0,
        "us_power_max": round(max(us_powers), 1) if us_powers else 0,
        "us_power_avg": round(sum(us_powers) / len(us_powers), 1) if us_powers else 0,
        "ds_snr_min": round(min(ds_snrs), 1) if ds_snrs else 0,
        "ds_snr_max": round(max(ds_snrs), 1) if ds_snrs else 0,
        "ds_snr_avg": round(sum(ds_snrs) / len(ds_snrs), 1) if ds_snrs else 0,
        "ds_correctable_errors": total_corr,
        "ds_uncorrectable_errors": total_uncorr,
        "us_capacity_mbps": us_capacity,
    }

    # --- Overall health (aggregate from per-channel assessments) ---
    issues = []

    # DS power: aggregate from individual channel health_detail
    if any("power critical" in c["health_detail"] for c in ds_channels):
        issues.append("ds_power_critical")
    elif any("power warning" in c["health_detail"] for c in ds_channels):
        issues.append("ds_power_warn")

    # US power: aggregate from individual channel health_detail (directional)
    us_crit_low = any("power critical low" in c["health_detail"] for c in us_channels)
    us_crit_high = any("power critical high" in c["health_detail"] for c in us_channels)
    us_warn_low = any("power warning low" in c["health_detail"] for c in us_channels)
    us_warn_high = any("power warning high" in c["health_detail"] for c in us_channels)
    if us_crit_low:
        issues.append("us_power_critical_low")
    if us_crit_high:
        issues.append("us_power_critical_high")
    if us_warn_low and not us_crit_low:
        issues.append("us_power_warn_low")
    if us_warn_high and not us_crit_high:
        issues.append("us_power_warn_high")

    # US modulation: aggregate from individual channel health_detail
    if any("modulation critical" in c["health_detail"] for c in us_channels):
        issues.append("us_modulation_critical")
    elif any("modulation warning" in c["health_detail"] for c in us_channels):
        issues.append("us_modulation_warn")

    # SNR: aggregate from individual channel health_detail
    if any("snr critical" in c["health_detail"] for c in ds_channels):
        issues.append("snr_critical")
    elif any("snr warning" in c["health_detail"] for c in ds_channels):
        issues.append("snr_warn")

    if total_uncorr > _get_uncorr_threshold():
        issues.append("uncorr_errors_high")

    if not issues:
        summary["health"] = "good"
    elif any("critical" in i for i in issues):
        summary["health"] = "poor"
    else:
        summary["health"] = "marginal"
    summary["health_issues"] = issues

    log.info(
        "Analysis: DS=%d US=%d Health=%s",
        len(ds_channels), len(us_channels), summary["health"],
    )

    return {
        "summary": summary,
        "ds_channels": ds_channels,
        "us_channels": us_channels,
    }
