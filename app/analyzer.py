"""DOCSIS channel health analysis with configurable thresholds.

Thresholds come from the built-in analyzer profile registry, with optional
community threshold profiles loaded through the module system.
"""

from __future__ import annotations

import logging
from typing import Literal

from .docsis_utils import (
    classify_channel_family as _shared_classify_channel_family,
    modulation_threshold_key as _modulation_threshold_key,
    parse_qam_order as _parse_qam_order,
)
from .types import AnalysisResult, DocsisData, SignalFamilyHealthCause
from .tz import utc_now, _parse_utc

log = logging.getLogger("docsis.analyzer")

# --- Dynamic thresholds (set by module loader) ---
_thresholds = {}
ANALYZER_SCHEMA_VERSION = 1
_threshold_profile = {"id": None, "version": None}

# Hardcoded fallback (VFKD values) used if no threshold profile is loaded
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


def set_thresholds(
    data: dict[str, object],
    *,
    profile_id: str | None = None,
    profile_version: str | None = None,
) -> None:
    """Set thresholds from a loaded threshold profile."""
    global _thresholds, _threshold_profile
    _thresholds = data
    _threshold_profile = {"id": profile_id, "version": profile_version}
    log.info("Thresholds updated (%d sections)", len(data))


def get_analysis_metadata(app_version: str | None = None) -> dict[str, object]:
    """Return provenance metadata for newly persisted analysis snapshots."""
    return {
        "analyzer_schema": ANALYZER_SCHEMA_VERSION,
        "app_version": app_version,
        "threshold_profile": dict(_threshold_profile),
    }


def _t():
    """Return active thresholds with fallback."""
    return _thresholds if _thresholds else _FALLBACK_THRESHOLDS


_MODULATION_ALIASES = {
    "OFDM": "4096QAM",
    "OFDMA": "4096QAM",
}


def _resolve_modulation(modulation, section):
    """Resolve modulation string to a key in thresholds config."""
    return _modulation_threshold_key(modulation, section)


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

    # DOCSIS 3.0 downstream commonly uses 64QAM or 256QAM. A 64QAM
    # downstream channel is valid and must not be treated as marginal.
    if qam_order >= 64:
        return "good"
    return "critical"


def _assess_us_modulation(ch, docsis_ver: str) -> str:
    """Return upstream modulation health, including OFDMA profile QAM."""
    modulation = ch.get("modulation") or ch.get("type") or ""
    profile_modulation = ch.get("profile_modulation") or ch.get("profileModulation")
    family = _classify_us_family({
        "type": ch.get("type", ""),
        "multiplex": ch.get("multiplex", ""),
        "modulation": modulation,
        "profile_modulation": profile_modulation,
        "docsis_version": docsis_ver,
    })
    assessment_modulation = profile_modulation if family == "ofdma" and profile_modulation else modulation
    qam_order = _parse_qam_order(assessment_modulation)
    if qam_order is None:
        return "good"

    if docsis_ver == "3.1" and family == "ofdma":
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


# DOCSIS SC-QAM default symbol rates (kSym/s) used when modems omit the
# symbol-rate field. Upstream commonly uses 5.12 MSym/s channels; downstream
# EuroDOCSIS 8 MHz channels use ~6.952 MSym/s.
_DEFAULT_US_SC_QAM_SYMBOL_RATE = 5120
_DEFAULT_DS_SC_QAM_SYMBOL_RATE = 6952

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


def _channel_bitrate_mbps(
    modulation_str,
    symbol_rate_ksym=None,
    default_symbol_rate=_DEFAULT_US_SC_QAM_SYMBOL_RATE,
):
    """Calculate theoretical gross bitrate for a SC-QAM channel in Mbit/s.

    Returns None if modulation is unparseable (for example OFDM/OFDMA) or no
    symbol rate/default symbol rate is available.
    """
    qam_order = _parse_qam_order(modulation_str)
    if qam_order is None or qam_order not in _BITS_PER_SYMBOL:
        return None
    rate = symbol_rate_ksym if symbol_rate_ksym is not None else default_symbol_rate
    if rate is None:
        return None
    return round(float(rate) * _BITS_PER_SYMBOL[qam_order] / 1000, 2)


def _capacity_coverage(channels):
    """Return calculated/unsupported coverage for theoretical channel capacity."""
    total = len(channels)
    calculated = sum(
        1 for ch in channels
        if ch.get("theoretical_bitrate") is not None
    )
    return {
        "calculated": calculated,
        "total": total,
        "unsupported": max(0, total - calculated),
    }


def get_thresholds():
    """Return a copy of loaded thresholds, stripped of internal keys."""
    def _strip(obj):
        if not isinstance(obj, dict):
            return obj
        return {k: _strip(v) for k, v in obj.items() if not k.startswith("_")}
    return _strip(_t())


def _parse_float(val, default=None):
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


_HEALTH_RANK = {"missing": -1, "good": 0, "tolerated": 1, "warning": 2, "critical": 3}


def _worst_health(values):
    """Return the worst health value, ignoring missing/unavailable metrics."""
    ranked = [value for value in values if value and value != "missing"]
    if not ranked:
        return "missing"
    return max(ranked, key=lambda value: _HEALTH_RANK.get(value, 0))


def _stats(values):
    """Return rounded min/avg/max stats without turning unavailable into zero."""
    filtered = [value for value in values if value is not None]
    if not filtered:
        return {"available": False, "min": None, "avg": None, "max": None}
    return {
        "available": True,
        "min": round(min(filtered), 1),
        "avg": round(sum(filtered) / len(filtered), 1),
        "max": round(max(filtered), 1),
    }


def _channel_modulation_value(channel, *, prefer_profile=False):
    if prefer_profile:
        return channel.get("profile_modulation") or channel.get("modulation")
    return channel.get("modulation") or channel.get("profile_modulation")


def _modulation_sort_key(value):
    return _parse_qam_order(value) or 0, value


def _distinct_modulation_healths(channels, *, prefer_profile=False):
    health_by_value = {}
    for channel in channels:
        value = _channel_modulation_value(channel, prefer_profile=prefer_profile)
        if not value:
            continue
        value = str(value)
        health = channel.get("modulation_health", "good")
        if value in health_by_value:
            health = _worst_health([health_by_value[value], health])
        health_by_value[value] = health
    return [
        {"value": value, "health": health_by_value[value]}
        for value in sorted(health_by_value, key=_modulation_sort_key)
    ]


def _family_health_counts(channels):
    """Count composite channel health states for one signal family."""
    counts = {"good": 0, "tolerated": 0, "warning": 0, "critical": 0}
    for channel in channels:
        health = channel.get("health") or "good"
        if health in counts:
            counts[health] += 1
    return counts


def _driver_value(channel, cause: SignalFamilyHealthCause, *, prefer_profile=False):
    if cause == "power":
        return channel.get("power"), "dBmV"
    if cause in {"snr", "mer"}:
        return channel.get("snr"), "dB"
    value = _channel_modulation_value(channel, prefer_profile=prefer_profile)
    return (str(value) if value else None), None


def _driver_health(channel, cause: SignalFamilyHealthCause):
    if cause == "power":
        return channel.get("power_health", "good") if channel.get("power") is not None else "missing"
    if cause in {"snr", "mer"}:
        return channel.get("snr_health", "good") if channel.get("snr") is not None else "missing"
    return channel.get("modulation_health", "good")


def _family_health_driver(family, channels, *, direction, cause, family_health, prefer_profile=False):
    """Return the channel/dimension that explains a family's worst status."""
    if not cause or family_health in {"good", "missing"}:
        return None

    candidates = []
    for channel in channels:
        value, unit = _driver_value(channel, cause, prefer_profile=prefer_profile)
        if value is None:
            continue
        health = _driver_health(channel, cause)
        if health == "missing":
            continue
        candidates.append({
            "channel_id": channel.get("channel_id"),
            "dimension": cause,
            "family": family,
            "direction": direction,
            "health": health,
            "unit": unit,
            "value": value,
        })

    if not candidates:
        return None

    matching_family_health = [candidate for candidate in candidates if candidate["health"] == family_health]
    if matching_family_health:
        return matching_family_health[0]
    return max(candidates, key=lambda candidate: _HEALTH_RANK.get(candidate["health"], 0))


def _classify_ds_family(channel):
    """Classify downstream channels into SC-QAM, OFDM, or unknown families."""
    return _shared_classify_channel_family("ds", channel)


def _classify_us_family(channel):
    """Classify upstream channels into SC-QAM, OFDMA, or unknown families."""
    return _shared_classify_channel_family("us", channel)


def _family_summary(family, channels, *, direction):
    # The analyzer normalizes downstream OFDM MER into the per-channel `snr` slot;
    # expose it as `mer` at the family-summary boundary so Home labels stay honest.
    quality_key: Literal["snr", "mer"] = "mer" if direction == "downstream" and family == "ofdm" else "snr"
    prefer_profile = family in {"ofdm", "ofdma"}
    power = _stats([channel.get("power") for channel in channels])
    quality = _stats([channel.get("snr") for channel in channels]) if direction == "downstream" else None
    modulation_value_healths = _distinct_modulation_healths(channels, prefer_profile=prefer_profile)
    modulation_values = [entry["value"] for entry in modulation_value_healths]
    power_health = _worst_health(
        channel.get("power_health", "good") for channel in channels if channel.get("power") is not None
    )
    quality_health = (
        _worst_health(channel.get("snr_health", "good") for channel in channels if channel.get("snr") is not None)
        if direction == "downstream"
        else "missing"
    )
    modulation_health = _worst_health(entry["health"] for entry in modulation_value_healths)

    metrics = [power_health, modulation_health]
    if direction == "downstream":
        metrics.append(quality_health)

    family_health = _worst_health(metrics)
    # Surface the most useful hidden cause first: modulation degradations are
    # otherwise easy to miss on power/SNR/MER cards, followed by power, then
    # downstream quality.
    health_cause: SignalFamilyHealthCause | None = None
    if family_health not in {"good", "missing"}:
        if modulation_health == family_health:
            health_cause = "modulation"
        elif power_health == family_health:
            health_cause = "power"
        elif direction == "downstream" and quality_health == family_health:
            health_cause = quality_key

    result = {
        "family": family,
        "count": len(channels),
        "health": family_health,
        "health_cause": health_cause,
        "health_counts": _family_health_counts(channels),
        "health_driver": _family_health_driver(
            family,
            channels,
            direction=direction,
            cause=health_cause,
            family_health=family_health,
            prefer_profile=prefer_profile,
        ),
        "power": {**power, "health": power_health},
        "modulation": {
            "available": bool(modulation_values),
            "value": modulation_values[0] if modulation_values else None,
            "secondary": modulation_values[-1] if len(modulation_values) > 1 else None,
            "distinct": modulation_values,
            "values": modulation_value_healths,
            "health": modulation_health,
        },
    }
    if direction == "downstream":
        assert quality is not None
        result[quality_key] = {**quality, "health": quality_health}
    return result


def _build_signal_family_summary(ds_channels, us_channels):
    """Build family-level signal summaries for Home without changing legacy globals."""
    ds_groups = {"sc_qam": [], "ofdm": [], "unknown": []}
    for channel in ds_channels:
        family = channel.get("channel_family") or _classify_ds_family(channel)
        ds_groups.setdefault(family, []).append(channel)

    us_groups = {"sc_qam": [], "ofdma": [], "unknown": []}
    for channel in us_channels:
        family = channel.get("channel_family") or _classify_us_family(channel)
        us_groups.setdefault(family, []).append(channel)

    downstream = {
        key: _family_summary(key, channels, direction="downstream")
        for key, channels in ds_groups.items()
        if channels
    }
    upstream = {
        key: _family_summary(key, channels, direction="upstream")
        for key, channels in us_groups.items()
        if channels
    }
    return {
        "downstream": {
            "health": _worst_health(family["health"] for family in downstream.values()),
            "families": downstream,
        },
        "upstream": {
            "health": _worst_health(family["health"] for family in upstream.values()),
            "families": upstream,
        },
    }


def _assess_ds_channel(ch, docsis_ver, *, modulation_docsis_ver: str | None = None):
    """Assess a single downstream channel. Returns (health, health_detail)."""
    issues = []
    raw_power = ch.get("powerLevel")
    modulation = (ch.get("modulation") or ch.get("type") or "").upper().replace("-", "")

    if raw_power is not None:
        power = _parse_float(raw_power)
        if power is not None:
            pt = _get_ds_power_thresholds(modulation)
            if power < pt["crit_min"] or power > pt["crit_max"]:
                issues.append("power critical")
            elif power < pt["warn_min"] or power > pt["warn_max"]:
                issues.append("power warning")
            elif power < pt["good_min"] or power > pt["good_max"]:
                issues.append("power tolerated")

    snr_val = None
    raw_mse = ch.get("mse")
    raw_mer = ch.get("mer")
    if docsis_ver == "3.0" and raw_mse is not None:
        parsed_mse = _parse_float(raw_mse)
        snr_val = abs(parsed_mse) if parsed_mse is not None else None
    elif docsis_ver == "3.1" and raw_mer is not None:
        snr_val = _parse_float(raw_mer)

    if snr_val is not None:
        st = _get_snr_thresholds(modulation)
        if snr_val < st["crit_min"]:
            issues.append("snr critical")
        elif snr_val < st["warn_min"]:
            issues.append("snr warning")
        elif snr_val < st["good_min"]:
            issues.append("snr tolerated")

    mod_issue = _modulation_issue(_assess_ds_modulation(modulation, modulation_docsis_ver or docsis_ver))
    if mod_issue:
        issues.append(mod_issue)

    return _channel_health(issues), _health_detail(issues)


def _assess_us_channel(ch, docsis_ver="3.0"):
    """Assess a single upstream channel. Returns (health, health_detail)."""
    issues = []
    raw_power = ch.get("powerLevel")

    modulation = ch.get("modulation") or ch.get("type") or ""
    profile_modulation = ch.get("profile_modulation") or ch.get("profileModulation")
    channel_family = _classify_us_family({
        "type": ch.get("type", ""),
        "multiplex": ch.get("multiplex", ""),
        "modulation": modulation,
        "profile_modulation": profile_modulation,
        "docsis_version": docsis_ver,
    })
    if channel_family == "ofdma":
        channel_type = "OFDMA"
    else:
        channel_type = (ch.get("type") or ch.get("multiplex") or modulation).upper().replace("-", "").strip()

    if raw_power is not None:
        power = _parse_float(raw_power)
        if power is not None:
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
        raw_mse = ch.get("mse")
        parsed_mse = _parse_float(raw_mse) if raw_mse is not None else None
        snr = abs(parsed_mse) if parsed_mse is not None else None
        health, health_detail = _assess_ds_channel(ch, "3.0")
        metric_h = _metric_healths(health_detail.split(" + ") if health_detail else [])
        ds_modulation = ch.get("modulation") or ch.get("type", "")
        metric_h["modulation_health"] = _assess_ds_modulation(ds_modulation, "3.0")
        profile_modulation = ch.get("profile_modulation") or ch.get("profileModulation")
        bitrate = _channel_bitrate_mbps(
            ds_modulation,
            ch.get("symbolRate"),
            _DEFAULT_DS_SC_QAM_SYMBOL_RATE,
        )
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": power,
            "modulation": ds_modulation,
            "snr": snr,
            "correctable_errors": ch.get("corrErrors"),
            "uncorrectable_errors": ch.get("nonCorrErrors"),
            "docsis_version": "3.0",
            "channel_family": "sc_qam",
            "health": health,
            "health_detail": health_detail,
            "theoretical_bitrate": bitrate,
            **metric_h,
        }
        if profile_modulation:
            channel["profile_modulation"] = profile_modulation
        ds_channels.append(channel)
    for ch in ds31:
        raw_power = ch.get("powerLevel")
        power = _parse_float(raw_power) if raw_power is not None else None
        raw_mer = ch.get("mer")
        snr = _parse_float(raw_mer) if raw_mer is not None else None
        ds_modulation = ch.get("modulation") or ch.get("type", "")
        profile_modulation = ch.get("profile_modulation") or ch.get("profileModulation")
        channel_family = _classify_ds_family({
            "type": ch.get("type", ""),
            "modulation": ds_modulation,
            "profile_modulation": profile_modulation,
            "docsis_version": "3.1",
        })
        modulation_docsis_ver = "3.0" if channel_family == "sc_qam" else "3.1"
        health, health_detail = _assess_ds_channel(
            ch,
            "3.1",
            modulation_docsis_ver=modulation_docsis_ver,
        )
        metric_h = _metric_healths(health_detail.split(" + ") if health_detail else [])
        metric_h["modulation_health"] = _assess_ds_modulation(ds_modulation, modulation_docsis_ver)
        bitrate = (
            _channel_bitrate_mbps(
                ds_modulation,
                ch.get("symbolRate"),
                _DEFAULT_DS_SC_QAM_SYMBOL_RATE,
            )
            if channel_family == "sc_qam"
            else None
        )
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": power,
            "modulation": ds_modulation,
            "snr": snr,
            "correctable_errors": ch.get("corrErrors"),
            "uncorrectable_errors": ch.get("nonCorrErrors"),
            "docsis_version": "3.1",
            "channel_family": channel_family,
            "health": health,
            "health_detail": health_detail,
            "theoretical_bitrate": bitrate,
            **metric_h,
        }
        if profile_modulation:
            channel["profile_modulation"] = profile_modulation
        ds_channels.append(channel)

    ds_channels.sort(key=lambda c: c["channel_id"])

    # --- Parse upstream channels ---
    us_channels = []
    for ch in us30:
        health, health_detail = _assess_us_channel(ch, "3.0")
        metric_h = _metric_healths(health_detail.split(" + ") if health_detail else [])
        metric_h["modulation_health"] = _assess_us_modulation(ch, "3.0")
        mod = ch.get("modulation") or ch.get("type", "")
        bitrate = _channel_bitrate_mbps(
            mod,
            ch.get("symbolRate"),
            _DEFAULT_US_SC_QAM_SYMBOL_RATE,
        )
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(ch.get("powerLevel")),
            "modulation": mod,
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.0",
            "channel_family": "sc_qam",
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
        raw_power = ch.get("powerLevel")
        profile_modulation = ch.get("profile_modulation") or ch.get("profileModulation")
        channel_family = _classify_us_family({
            "type": ch.get("type", ""),
            "multiplex": ch.get("multiplex", ""),
            "modulation": mod,
            "profile_modulation": profile_modulation,
            "docsis_version": "3.1",
        })
        bitrate = (
            _channel_bitrate_mbps(
                mod,
                ch.get("symbolRate"),
                _DEFAULT_US_SC_QAM_SYMBOL_RATE,
            )
            if channel_family == "sc_qam"
            else None
        )
        channel = {
            "channel_id": _parse_channel_id(ch.get("channelID", 0)),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(raw_power) if raw_power is not None else None,
            "modulation": mod,
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.1",
            "channel_family": channel_family,
            "health": health,
            "health_detail": health_detail,
            "theoretical_bitrate": bitrate,
            **metric_h,
        }
        if profile_modulation:
            channel["profile_modulation"] = profile_modulation
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

    ds_bitrates = [c["theoretical_bitrate"] for c in ds_channels if c.get("theoretical_bitrate") is not None]
    ds_capacity = round(sum(ds_bitrates), 1) if ds_bitrates else None
    us_bitrates = [c["theoretical_bitrate"] for c in us_channels if c["theoretical_bitrate"] is not None]
    us_capacity = round(sum(us_bitrates), 1) if us_bitrates else None
    capacity_coverage = {
        "downstream": _capacity_coverage(ds_channels),
        "upstream": _capacity_coverage(us_channels),
    }

    signal_families = _build_signal_family_summary(ds_channels, us_channels)
    ds_family_summaries = signal_families["downstream"]["families"]
    us_family_summaries = signal_families["upstream"]["families"]

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
        "ds_capacity_mbps": ds_capacity,
        "us_capacity_mbps": us_capacity,
        "capacity_coverage": capacity_coverage,
        "signal_families": signal_families,
        "ds_scqam_power_avg": ds_family_summaries.get("sc_qam", {}).get("power", {}).get("avg"),
        "ds_scqam_snr_avg": ds_family_summaries.get("sc_qam", {}).get("snr", {}).get("avg"),
        "ds_ofdm_power_avg": ds_family_summaries.get("ofdm", {}).get("power", {}).get("avg"),
        "ds_ofdm_mer_avg": ds_family_summaries.get("ofdm", {}).get("mer", {}).get("avg"),
        "us_scqam_power_avg": us_family_summaries.get("sc_qam", {}).get("power", {}).get("avg"),
        "us_ofdma_power_avg": us_family_summaries.get("ofdma", {}).get("power", {}).get("avg"),
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
