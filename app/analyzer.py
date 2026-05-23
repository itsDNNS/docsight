"""DOCSIS channel health analysis with configurable thresholds.

Thresholds are loaded dynamically from the active threshold module.
The module loader calls set_thresholds() during startup.
"""

from __future__ import annotations

import logging
import re

from .types import AnalysisResult, DocsisData
from .tz import utc_now, _parse_utc

log = logging.getLogger("docsis.analyzer")

# --- Dynamic thresholds (set by module loader) ---
_thresholds = {}

# Hardcoded fallback (VFKD values) used if no threshold module is loaded
_FALLBACK_THRESHOLDS = {
    "downstream_power": {
        "_default": "256QAM",
        "64QAM":   {"good": [-10.0, 7.0],  "warning": [-12.0, 12.0], "critical": [-14.0, 16.0]},
        "256QAM":  {"good": [-4.0, 13.0],  "warning": [-6.0, 15.0],  "critical": [-8.0, 16.0]},
        "1024QAM": {"good": [-2.0, 15.0],  "warning": [-4.0, 16.0],  "critical": [-6.0, 16.0]},
        "4096QAM": {"good": [-2.0, 15.0],  "warning": [-4.0, 16.0],  "critical": [-6.0, 16.0]},
    },
    "upstream_power": {
        "_default": "sc_qam",
        "sc_qam": {"good": [41.1, 47.0], "warning": [37.1, 51.0], "critical": [35.0, 53.0]},
        "ofdma":  {"good": [44.1, 47.0], "warning": [40.1, 48.0], "critical": [38.0, 50.0]},
    },
    "snr": {
        "_default": "256QAM",
        "64QAM":   {"good_min": 27.0, "warning_min": 25.0, "critical_min": 23.0},
        "256QAM":  {"good_min": 33.0, "warning_min": 31.0, "critical_min": 29.0},
        "ofdm":    {"good_min": 27.0, "warning_min": 25.5, "critical_min": 24.5},
        "1024QAM": {"good_min": 39.0, "warning_min": 37.0, "critical_min": 36.0},
        "4096QAM": {"good_min": 40.0, "warning_min": 38.0, "critical_min": 36.0},
    },
    "upstream_modulation": {"critical_max_qam": 4, "warning_max_qam": 16},
    "errors": {"uncorrectable_pct": {"warning": 1.0, "critical": 3.0, "min_codewords": 1000}},
}


def set_thresholds(data: dict[str, object]) -> None:
    """Set thresholds from a loaded threshold module."""
    global _thresholds
    _thresholds = data
    log.info("Thresholds updated (%d sections)", len(data))


def _t():
    """Return active thresholds with fallback."""
    return _thresholds if _thresholds else _FALLBACK_THRESHOLDS


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
    ds = _t().get("downstream_power", {})
    mod = _resolve_modulation(modulation, ds)
    t = ds.get(mod, {})
    good = t.get("good", [-4.0, 13.0])
    warn = t.get("warning", good)
    crit = t.get("critical", [-8.0, 20.0])
    return {
        "good_min": good[0],
        "good_max": good[1],
        "warn_min": warn[0],
        "warn_max": warn[1],
        "crit_min": crit[0],
        "crit_max": crit[1],
    }


def _get_us_power_thresholds(channel_type=None):
    """Get US power thresholds by channel type (sc_qam or ofdma)."""
    us = _t().get("upstream_power", {})
    default_key = us.get("_default", "sc_qam")
    if channel_type and channel_type.upper() in ("OFDMA",):
        key = "ofdma"
    else:
        key = "sc_qam"
    t = us.get(key, us.get(default_key, {}))
    good = t.get("good", [41.0, 47.0])
    warn = t.get("warning", good)
    crit = t.get("critical", [35.0, 53.0])
    return {
        "good_min": good[0],
        "good_max": good[1],
        "warn_min": warn[0],
        "warn_max": warn[1],
        "crit_min": crit[0],
        "crit_max": crit[1],
    }


def _get_snr_thresholds(modulation=None):
    """Get SNR thresholds for a given modulation."""
    snr = _t().get("snr", {})
    mod = _resolve_modulation(modulation, snr)
    t = snr.get(mod, {})
    return {
        "good_min": t.get("good_min", 33.0),
        "warn_min": t.get("warning_min", t.get("good_min", 33.0)),
        "crit_min": t.get("critical_min", 29.0),
    }


def _get_us_modulation_thresholds():
    """Get upstream modulation QAM order thresholds."""
    us_mod = _t().get("upstream_modulation", {})
    return {
        "critical_max_qam": us_mod.get("critical_max_qam", 4),
        "warning_max_qam": us_mod.get("warning_max_qam", 16),
    }


def _modulation_issue(health: str | None) -> str | None:
    if health in {"critical", "warning", "tolerated"}:
        return f"modulation {health}"
    return None


def _assess_ds_modulation(modulation: str, docsis_ver: str) -> str:
    """Return downstream modulation health for display and channel scoring."""
    mod = (modulation or "").upper().replace("-", "").strip()
    if mod == "OFDM":
        return "good"
    qam_order = _parse_qam_order(mod)
    if qam_order is None:
        return "good"

    if docsis_ver == "3.1":
        if qam_order >= 1024:
            return "good"
        if qam_order >= 512:
            return "tolerated"
        if qam_order >= 256:
            return "warning"
        return "critical"

    if qam_order >= 256:
        return "good"
    if qam_order >= 128:
        return "tolerated"
    if qam_order >= 64:
        return "warning"
    return "critical"


def _assess_us_modulation(ch, docsis_ver: str) -> str:
    """Return upstream modulation health, including OFDMA profile QAM."""
    modulation = ch.get("modulation") or ch.get("type") or ""
    channel_type = (ch.get("type") or ch.get("multiplex") or modulation).upper().replace("-", "").strip()
    profile_modulation = ch.get("profile_modulation") or ch.get("profileModulation")
    assessment_modulation = profile_modulation if channel_type == "OFDMA" and profile_modulation else modulation
    qam_order = _parse_qam_order(assessment_modulation)
    if qam_order is None:
        return "good"

    if docsis_ver == "3.1" and channel_type == "OFDMA":
        if qam_order <= 32:
            return "critical"
        if qam_order <= 64:
            return "warning"
        if qam_order <= 128:
            return "tolerated"
        return "good"

    mt = _get_us_modulation_thresholds()
    if qam_order <= mt["critical_max_qam"]:
        return "critical"
    if qam_order <= mt["warning_max_qam"]:
        return "warning"
    return "good"


def _get_uncorr_thresholds():
    """Get uncorrectable error thresholds (percent-based)."""
    errors = _t().get("errors", {})
    pct = errors.get("uncorrectable_pct", {})
    return {
        "warning": pct.get("warning", 1.0),
        "critical": pct.get("critical", 3.0),
        "min_codewords": pct.get("min_codewords", 1000),
    }


def _get_spike_expiry_hours():
    """Get spike expiry window in hours (default 48)."""
    errors = _t().get("errors", {})
    return errors.get("spike_expiry_hours", 48)


def _uncorr_issue(issue: str) -> bool:
    return "uncorr" in issue


def _recalculate_summary_health(summary) -> None:
    """Recalculate aggregate health from summary health_issues."""
    issues = summary["health_issues"]
    if not issues:
        summary["health"] = "good"
    elif any("critical" in i for i in issues):
        summary["health"] = "critical"
    elif any("marginal" in i for i in issues):
        summary["health"] = "marginal"
    else:
        summary["health"] = "tolerated"


def _recent_spike_active(last_spike_ts: str | None) -> bool:
    """Return True while an observed error spike is still inside its expiry window."""
    if not last_spike_ts:
        return False
    try:
        now = _parse_utc(utc_now())
        spike_dt = _parse_utc(last_spike_ts)
    except Exception:
        return False
    return (now - spike_dt).total_seconds() / 3600 < _get_spike_expiry_hours()


def _coerce_counter(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def apply_cumulative_error_baseline(
    analysis: AnalysisResult,
    previous_analysis: AnalysisResult | None,
    *,
    recent_spike_active: bool = False,
) -> None:
    """Score uncorrectable errors against observed cumulative counter growth.

    Modems often expose correctable/uncorrectable counters as totals since the
    last modem reboot. The analyzer keeps those raw totals in the summary and
    channel data, but health should not treat pre-existing counters from the
    first DOCSight observation as active trouble forever. Once a previous
    snapshot exists, keep carrying the first comparable DOCSight totals as the
    health baseline and score the uncorrectable percentage from cumulative
    growth since that baseline. If counters decrease, treat it as a modem
    reset/reboot and establish a fresh baseline.

    A recent observed error_spike deliberately bypasses this baseline path so
    the existing spike-expiry window continues to hold the penalty until it
    expires.
    """
    if recent_spike_active or not isinstance(previous_analysis, dict):
        return

    summary = analysis.get("summary", {})
    previous_summary = previous_analysis.get("summary", {})
    if summary.get("errors_supported") is False or previous_summary.get("errors_supported") is False:
        return

    current_corr = _coerce_counter(summary.get("ds_correctable_errors"))
    current_uncorr = _coerce_counter(summary.get("ds_uncorrectable_errors"))
    previous_corr = _coerce_counter(previous_summary.get("ds_correctable_errors"))
    previous_uncorr = _coerce_counter(previous_summary.get("ds_uncorrectable_errors"))
    if any(v is None for v in (current_corr, current_uncorr, previous_corr, previous_uncorr)):
        return
    assert current_corr is not None
    assert current_uncorr is not None
    assert previous_corr is not None
    assert previous_uncorr is not None

    previous_baseline = previous_summary.get("error_baseline")
    if isinstance(previous_baseline, dict):
        baseline_corr = _coerce_counter(previous_baseline.get("ds_correctable_baseline"))
        baseline_uncorr = _coerce_counter(previous_baseline.get("ds_uncorrectable_baseline"))
    else:
        baseline_corr = None
        baseline_uncorr = None
    if baseline_corr is None or baseline_uncorr is None:
        baseline_corr = previous_corr
        baseline_uncorr = previous_uncorr

    counter_reset = (
        current_corr < previous_corr
        or current_uncorr < previous_uncorr
        or current_corr < baseline_corr
        or current_uncorr < baseline_uncorr
    )
    if counter_reset:
        baseline_corr = current_corr
        baseline_uncorr = current_uncorr
        corr_recent_delta = 0
        uncorr_recent_delta = 0
        corr_delta = 0
        uncorr_delta = 0
    else:
        corr_recent_delta = current_corr - previous_corr
        uncorr_recent_delta = current_uncorr - previous_uncorr
        corr_delta = current_corr - baseline_corr
        uncorr_delta = current_uncorr - baseline_uncorr

    et = _get_uncorr_thresholds()
    delta_codewords = corr_delta + uncorr_delta
    uncorr_pct = 0.0
    uncorr_issue = None
    if delta_codewords >= et["min_codewords"]:
        uncorr_pct = round((uncorr_delta / delta_codewords) * 100, 2)
        if uncorr_pct >= et["critical"]:
            uncorr_issue = "uncorr_errors_critical"
        elif uncorr_pct >= et["warning"]:
            uncorr_issue = "uncorr_errors_high"

    summary["ds_uncorr_pct"] = uncorr_pct
    summary["health_issues"] = [i for i in summary["health_issues"] if not _uncorr_issue(i)]
    if uncorr_issue:
        summary["health_issues"].append(uncorr_issue)
    summary["error_baseline"] = {
        "active": True,
        "basis": "docsight_baseline_delta",
        "counter_reset": counter_reset,
        "ds_correctable_baseline": baseline_corr,
        "ds_uncorrectable_baseline": baseline_uncorr,
        "ds_correctable_recent_delta": corr_recent_delta,
        "ds_uncorrectable_recent_delta": uncorr_recent_delta,
        "ds_correctable_delta": corr_delta,
        "ds_uncorrectable_delta": uncorr_delta,
    }
    _recalculate_summary_health(summary)


def apply_spike_suppression(analysis: AnalysisResult, last_spike_ts: str | None) -> None:
    """Suppress uncorrectable error penalization if a past spike has expired.

    Called as a post-processing step after analyze(). If the most recent
    error_spike event is older than spike_expiry_hours and no new spike has
    occurred since, the uncorrectable error percentage and related health
    issues are suppressed.

    Args:
        analysis: AnalysisResult from analyze() -- modified in place
        last_spike_ts: UTC timestamp string of latest error_spike, or None
    """
    if not last_spike_ts:
        return

    expiry_hours = _get_spike_expiry_hours()
    now = _parse_utc(utc_now())
    spike_dt = _parse_utc(last_spike_ts)
    hours_since = (now - spike_dt).total_seconds() / 3600

    if hours_since < expiry_hours:
        return  # Still in observation period

    summary = analysis["summary"]
    baseline = summary.get("error_baseline")
    baseline_uncorr_recent_delta = None
    if isinstance(baseline, dict):
        baseline_uncorr_recent_delta = _coerce_counter(baseline.get("ds_uncorrectable_recent_delta"))
    if baseline_uncorr_recent_delta and any(_uncorr_issue(i) for i in summary.get("health_issues", [])):
        return  # Preserve new DOCSight-observed growth after the old spike window.

    if summary.get("ds_uncorr_pct") is not None:
        summary["ds_uncorr_pct"] = 0.0
    summary["health_issues"] = [i for i in summary["health_issues"] if not _uncorr_issue(i)]
    summary["spike_suppression"] = {
        "active": True,
        "last_spike": last_spike_ts,
        "hours_since_spike": round(hours_since, 1),
        "expiry_hours": expiry_hours,
    }

    _recalculate_summary_health(summary)


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
    """Return a copy of loaded thresholds, stripped of internal keys."""
    def _strip(obj):
        if not isinstance(obj, dict):
            return obj
        return {k: _strip(v) for k, v in obj.items() if not k.startswith("_")}
    return _strip(_t())


def _parse_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_channel_id(val):
    """Parse channel ID to int, handling float strings like '1.0'."""
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0


def _channel_health(issues):
    """Return health string from issue list."""
    if not issues:
        return "good"
    if any("critical" in i for i in issues):
        return "critical"
    if any("warning" in i for i in issues):
        return "warning"
    return "tolerated"


def _health_detail(issues):
    """Build a machine-readable detail string from issue list."""
    if not issues:
        return ""
    return " + ".join(issues)


def _metric_healths(issues):
    """Extract per-metric health levels from issue list."""
    result = {}
    for metric in ("power", "snr", "modulation"):
        if any(i.startswith(metric + " critical") for i in issues):
            result[metric + "_health"] = "critical"
        elif any(i.startswith(metric + " warning") for i in issues):
            result[metric + "_health"] = "warning"
        elif any(i.startswith(metric + " tolerated") for i in issues):
            result[metric + "_health"] = "tolerated"
    return result


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
        elif power < pt["warn_min"] or power > pt["warn_max"]:
            issues.append("power warning")
        elif power < pt["good_min"] or power > pt["good_max"]:
            issues.append("power tolerated")

    snr_val = None
    if docsis_ver == "3.0" and ch.get("mse"):
        snr_val = abs(_parse_float(ch["mse"]))
    elif docsis_ver == "3.1" and ch.get("mer"):
        snr_val = _parse_float(ch["mer"])

    if snr_val is not None:
        st = _get_snr_thresholds(modulation)
        if snr_val < st["crit_min"]:
            issues.append("snr critical")
        elif snr_val < st["warn_min"]:
            issues.append("snr warning")
        elif snr_val < st["good_min"]:
            issues.append("snr tolerated")

    mod_issue = _modulation_issue(_assess_ds_modulation(modulation, docsis_ver))
    if mod_issue:
        issues.append(mod_issue)

    return _channel_health(issues), _health_detail(issues)


def _assess_us_channel(ch, docsis_ver="3.0"):
    """Assess a single upstream channel. Returns (health, health_detail)."""
    issues = []
    raw_power = ch.get("powerLevel")

    modulation = ch.get("modulation") or ch.get("type") or ""
    channel_type = (ch.get("type") or modulation).upper().replace("-", "").strip()

    if raw_power is not None:
        power = _parse_float(raw_power)
        pt = _get_us_power_thresholds(channel_type)
        if power < pt["crit_min"]:
            issues.append("power critical low")
        elif power > pt["crit_max"]:
            issues.append("power critical high")
        elif power < pt["warn_min"]:
            issues.append("power warning low")
        elif power > pt["warn_max"]:
            issues.append("power warning high")
        elif power < pt["good_min"]:
            issues.append("power tolerated low")
        elif power > pt["good_max"]:
            issues.append("power tolerated high")
    mod_health = _assess_us_modulation(ch, docsis_ver)
    mod_issue = _modulation_issue(mod_health)
    if mod_issue:
        issues.append(mod_issue)

    return _channel_health(issues), _health_detail(issues)


def analyze(data: DocsisData) -> AnalysisResult:
    """Analyze DOCSIS data and return structured result.

    Returns AnalysisResult with keys:
        summary: AnalysisSummary of aggregate metrics
        ds_channels: list of DownstreamChannel dicts
        us_channels: list of UpstreamChannel dicts
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
        metric_h = _metric_healths(health_detail.split(" + ") if health_detail else [])
        metric_h["modulation_health"] = _assess_ds_modulation(ch.get("modulation") or ch.get("type", ""), "3.0")
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": power,
            "modulation": ch.get("modulation") or ch.get("type", ""),
            "snr": snr,
            "correctable_errors": ch.get("corrErrors"),
            "uncorrectable_errors": ch.get("nonCorrErrors"),
            "docsis_version": "3.0",
            "health": health,
            "health_detail": health_detail,
            **metric_h,
        }
        if ch.get("profile_modulation"):
            channel["profile_modulation"] = ch["profile_modulation"]
        ds_channels.append(channel)
    for ch in ds31:
        raw_power = ch.get("powerLevel")
        power = _parse_float(raw_power) if raw_power is not None else None
        snr = _parse_float(ch.get("mer")) if ch.get("mer") else None
        health, health_detail = _assess_ds_channel(ch, "3.1")
        metric_h = _metric_healths(health_detail.split(" + ") if health_detail else [])
        metric_h["modulation_health"] = _assess_ds_modulation(ch.get("modulation") or ch.get("type", ""), "3.1")
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": power,
            "modulation": ch.get("modulation") or ch.get("type", ""),
            "snr": snr,
            "correctable_errors": ch.get("corrErrors"),
            "uncorrectable_errors": ch.get("nonCorrErrors"),
            "docsis_version": "3.1",
            "health": health,
            "health_detail": health_detail,
            **metric_h,
        }
        if ch.get("profile_modulation"):
            channel["profile_modulation"] = ch["profile_modulation"]
        ds_channels.append(channel)

    ds_channels.sort(key=lambda c: c["channel_id"])

    # --- Parse upstream channels ---
    us_channels = []
    for ch in us30:
        health, health_detail = _assess_us_channel(ch, "3.0")
        metric_h = _metric_healths(health_detail.split(" + ") if health_detail else [])
        metric_h["modulation_health"] = _assess_us_modulation(ch, "3.0")
        mod = ch.get("modulation") or ch.get("type", "")
        bitrate = _channel_bitrate_mbps(mod, ch.get("symbolRate"))
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(ch.get("powerLevel")),
            "modulation": mod,
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.0",
            "health": health,
            "health_detail": health_detail,
            "theoretical_bitrate": bitrate,
            **metric_h,
        }
        if ch.get("profile_modulation"):
            channel["profile_modulation"] = ch["profile_modulation"]
        us_channels.append(channel)
    for ch in us31:
        health, health_detail = _assess_us_channel(ch, "3.1")
        metric_h = _metric_healths(health_detail.split(" + ") if health_detail else [])
        metric_h["modulation_health"] = _assess_us_modulation(ch, "3.1")
        mod = ch.get("modulation") or ch.get("type", "")
        bitrate = _channel_bitrate_mbps(mod, ch.get("symbolRate"))
        raw_power = ch.get("powerLevel")
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(raw_power) if raw_power is not None else None,
            "modulation": mod,
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.1",
            "health": health,
            "health_detail": health_detail,
            "theoretical_bitrate": bitrate,
            **metric_h,
        }
        if ch.get("profile_modulation"):
            channel["profile_modulation"] = ch["profile_modulation"]
        us_channels.append(channel)

    us_channels.sort(key=lambda c: c["channel_id"])

    # --- Summary metrics ---
    ds_powers = [c["power"] for c in ds_channels if c["power"] is not None]
    us_powers = [c["power"] for c in us_channels if c["power"] is not None]
    ds_snrs = [c["snr"] for c in ds_channels if c["snr"] is not None]

    has_corr_data = any(c["correctable_errors"] is not None for c in ds_channels)
    has_uncorr_data = any(c["uncorrectable_errors"] is not None for c in ds_channels)
    has_error_data = has_corr_data or has_uncorr_data
    total_corr = (
        sum(c["correctable_errors"] for c in ds_channels if c["correctable_errors"] is not None)
        if has_corr_data
        else None
    )
    total_uncorr = (
        sum(c["uncorrectable_errors"] for c in ds_channels if c["uncorrectable_errors"] is not None)
        if has_uncorr_data
        else None
    )

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
        "errors_supported": has_error_data,
        "us_capacity_mbps": us_capacity,
    }

    # --- Overall health (aggregate from per-channel assessments) ---
    issues = []

    # DS power: aggregate from individual channel health_detail
    if any("power critical" in c["health_detail"] for c in ds_channels):
        issues.append("ds_power_critical")
    elif any("power warning" in c["health_detail"] for c in ds_channels):
        issues.append("ds_power_marginal")
    elif any("power tolerated" in c["health_detail"] for c in ds_channels):
        issues.append("ds_power_tolerated")

    # DS modulation: aggregate from individual channel health_detail
    if any("modulation critical" in c["health_detail"] for c in ds_channels):
        issues.append("ds_modulation_critical")
    elif any("modulation warning" in c["health_detail"] for c in ds_channels):
        issues.append("ds_modulation_marginal")
    elif any("modulation tolerated" in c["health_detail"] for c in ds_channels):
        issues.append("ds_modulation_tolerated")

    # US power: aggregate from individual channel health_detail (directional)
    us_crit_low = any("power critical low" in c["health_detail"] for c in us_channels)
    us_crit_high = any("power critical high" in c["health_detail"] for c in us_channels)
    us_warn_low = any("power warning low" in c["health_detail"] for c in us_channels)
    us_warn_high = any("power warning high" in c["health_detail"] for c in us_channels)
    us_tol_low = any("power tolerated low" in c["health_detail"] for c in us_channels)
    us_tol_high = any("power tolerated high" in c["health_detail"] for c in us_channels)
    if us_crit_low:
        issues.append("us_power_critical_low")
    if us_crit_high:
        issues.append("us_power_critical_high")
    if us_warn_low and not us_crit_low:
        issues.append("us_power_marginal_low")
    if us_warn_high and not us_crit_high:
        issues.append("us_power_marginal_high")
    if us_tol_low and not us_crit_low and not us_warn_low:
        issues.append("us_power_tolerated_low")
    if us_tol_high and not us_crit_high and not us_warn_high:
        issues.append("us_power_tolerated_high")

    # US modulation: aggregate from individual channel health_detail
    if any("modulation critical" in c["health_detail"] for c in us_channels):
        issues.append("us_modulation_critical")
    elif any("modulation warning" in c["health_detail"] for c in us_channels):
        issues.append("us_modulation_marginal")

    # SNR: aggregate from individual channel health_detail
    if any("snr critical" in c["health_detail"] for c in ds_channels):
        issues.append("snr_critical")
    elif any("snr warning" in c["health_detail"] for c in ds_channels):
        issues.append("snr_marginal")
    elif any("snr tolerated" in c["health_detail"] for c in ds_channels):
        issues.append("snr_tolerated")

    total_codewords = (total_corr or 0) + (total_uncorr or 0)
    et = _get_uncorr_thresholds()
    if has_corr_data and has_uncorr_data:
        if total_codewords >= et["min_codewords"]:
            uncorr_pct = round(((total_uncorr or 0) / total_codewords) * 100, 2)
            if uncorr_pct >= et["critical"]:
                issues.append("uncorr_errors_critical")
            elif uncorr_pct >= et["warning"]:
                issues.append("uncorr_errors_high")
        else:
            uncorr_pct = 0.0
    else:
        uncorr_pct = None
    summary["ds_uncorr_pct"] = uncorr_pct

    if not issues:
        summary["health"] = "good"
    elif any("critical" in i for i in issues):
        summary["health"] = "critical"
    elif any("marginal" in i for i in issues):
        summary["health"] = "marginal"
    else:
        summary["health"] = "tolerated"
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
