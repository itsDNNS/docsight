"""DOCSIS channel health analysis with configurable thresholds.

Thresholds come from the built-in analyzer profile registry, with optional
community threshold profiles loaded through the module system.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from typing import Any, Literal, cast

from .docsis_utils import (
    classify_channel_family as _shared_classify_channel_family,
)
from .docsis_utils import (
    modulation_threshold_key as _modulation_threshold_key,
)
from .docsis_utils import (
    parse_qam_order as _parse_qam_order,
)
from .error_counters import (
    aggregate_error_counters,
    calculate_error_counter_growth,
    uncorrectable_percentage,
)
from .docsis_utils import OFDMA_MIN_PLAUSIBLE_POWER_DBMV
from .threshold_profiles import BUILTIN_THRESHOLD_PROFILES
from .types import AnalysisResult, DocsisData, SignalFamilyHealthCause
from .tz import _parse_utc, utc_now

log = logging.getLogger("docsis.analyzer")

# --- Dynamic thresholds (set by module loader) ---
_thresholds = {}
# 4: low upstream power on its own is rated at most warning/marginal.
# 5: low OFDMA upstream power is not rated (no OFDM level range in the spec).
ANALYZER_SCHEMA_VERSION = 5
# First schema whose stored error baseline uses comparable counters. Later
# schemas keep that baseline instead of starting a fresh one after an update.
_ERROR_BASELINE_SCHEMA = 3
_threshold_profile = {"id": None, "version": None, "name": None}

# Fallback used if no threshold profile is loaded: the shipped VFKD values.
# Their sources are documented in the profile metadata, which is left out here.
_VFKD_PROFILE = next(p for p in BUILTIN_THRESHOLD_PROFILES if p["id"] == "docsight.thresholds_vfkd")
_FALLBACK_THRESHOLDS = {
    key: copy.deepcopy(value)
    for key, value in cast(dict[str, Any], _VFKD_PROFILE["thresholds"]).items()
    if key != "_meta"
}


def set_thresholds(
    data: dict[str, object],
    *,
    profile_id: str | None = None,
    profile_version: str | None = None,
    profile_name: str | None = None,
) -> None:
    """Set thresholds from a loaded threshold profile."""
    global _thresholds, _threshold_profile
    _thresholds = data
    _threshold_profile = {"id": profile_id, "version": profile_version, "name": profile_name}
    log.info("Thresholds updated (%d sections)", len(data))


def get_analysis_metadata(app_version: str | None = None) -> dict[str, object]:
    """Return provenance metadata for newly persisted analysis snapshots."""
    return {
        "analyzer_schema": ANALYZER_SCHEMA_VERSION,
        "app_version": app_version,
        "threshold_profile": _profile_identity(),
    }


def _profile_identity() -> dict[str, Any]:
    return {"id": _threshold_profile.get("id"), "version": _threshold_profile.get("version")}


def active_threshold_profile() -> dict[str, Any]:
    """Describe the profile whose values the analyzer currently applies."""
    if _thresholds:
        profile = dict(_threshold_profile)
        meta = _thresholds.get("_meta")
    else:
        profile = {key: _VFKD_PROFILE[key] for key in ("id", "version", "name")}
        meta = cast(dict[str, Any], _VFKD_PROFILE["thresholds"])["_meta"]
    name = profile.get("name") or profile.get("id")
    version = profile.get("version")
    # Only shipped profiles may use a short label; a community profile that
    # copied built-in metadata must still be named as itself.
    builtin = next((p for p in BUILTIN_THRESHOLD_PROFILES if p["id"] == profile.get("id")), {})
    return {
        "label": f"{name} {version}" if name and version else name,
        "short_name": builtin.get("short_name") or name,
        "meta": copy.deepcopy(meta) if isinstance(meta, dict) else {},
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


def resolve_ds_power_thresholds(
    modulation=None,
    *,
    channel_family: str | None = None,
    thresholds: Mapping[str, Any],
):
    """Resolve downstream power thresholds from an explicit plain-data mapping."""
    ds = thresholds.get("downstream_power", {})
    if channel_family == "ofdm" and "ofdm" in ds:
        t = ds["ofdm"]
    else:
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


def _get_ds_power_thresholds(modulation=None, *, channel_family: str | None = None):
    """Get DS power thresholds for a given modulation."""
    return resolve_ds_power_thresholds(
        modulation, channel_family=channel_family, thresholds=_t()
    )


def resolve_us_power_thresholds(channel_type=None, *, thresholds: Mapping[str, Any]):
    """Resolve upstream power thresholds from an explicit plain-data mapping.

    ``rate_low`` is False for OFDMA: the operator specification gives no OFDM
    level range and DOCSIS 3.1 only defines what a modem can transmit, so low
    OFDMA power is not rated and the profile minimums only scale displays.
    Levels below ``plausible_min`` are still rated as a warning.
    """
    us = thresholds.get("upstream_power", {})
    default_key = us.get("_default", "sc_qam")
    if channel_type and channel_type.upper() == "OFDMA":
        key = "ofdma"
    else:
        key = "sc_qam"
    t = us.get(key, us.get(default_key, {}))
    good = t.get("good", [41.0, 47.0])
    warn = t.get("warning", good)
    crit = t.get("critical", [35.0, 53.0])
    rate_low = key != "ofdma"
    return {
        "good_min": good[0],
        "good_max": good[1],
        "warn_min": warn[0],
        "warn_max": warn[1],
        "crit_min": crit[0],
        "crit_max": crit[1],
        "rate_low": rate_low,
        "plausible_min": None if rate_low else OFDMA_MIN_PLAUSIBLE_POWER_DBMV,
    }


def _get_us_power_thresholds(channel_type=None):
    """Get US power thresholds by channel type (sc_qam or ofdma)."""
    return resolve_us_power_thresholds(channel_type, thresholds=_t())


def resolve_snr_thresholds(
    modulation=None,
    *,
    channel_family: str | None = None,
    thresholds: Mapping[str, Any],
):
    """Resolve downstream SNR thresholds from an explicit plain-data mapping."""
    snr = thresholds.get("snr", {})
    if not isinstance(snr, dict):
        snr = {}
    if channel_family == "ofdm" and "ofdm" in snr:
        t = snr["ofdm"]
    else:
        mod = _resolve_modulation(modulation, snr)
        t = snr.get(mod, {})
    return {
        "good_min": t.get("good_min", 33.0),
        "warn_min": t.get("warning_min", t.get("good_min", 33.0)),
        "crit_min": t.get("critical_min", 29.0),
    }


def _get_snr_thresholds(modulation=None, *, channel_family: str | None = None):
    """Get SNR thresholds for a given modulation."""
    return resolve_snr_thresholds(
        modulation, channel_family=channel_family, thresholds=_t()
    )


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


def _assess_us_modulation(modulation, family: str, docsis_ver: str) -> str:
    """Return upstream modulation health; OFDMA channels pass their profile QAM."""
    qam_order = _parse_qam_order(modulation)
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


_QAM_ORDERS = (4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096)


def modulation_target(direction: str, channel: dict) -> str | None:
    """Return the lowest modulation the channel scoring rates good, e.g. "1024QAM".

    Probes the same assessment the analyzer uses, so the shown target can never
    drift from the rating. Returns None when the channel's modulation is not rated.
    """
    family = channel.get("channel_family") or ""
    docsis_ver = channel.get("docsis_version") or "3.0"

    def rated_good(order: int) -> bool:
        qam = f"{order}QAM"
        if direction == "ds":
            return _assess_ds_modulation(qam, "3.0" if family == "sc_qam" else docsis_ver) == "good"
        return _assess_us_modulation(qam, family, docsis_ver) == "good"

    good = [order for order in _QAM_ORDERS if rated_good(order)]
    if not good or len(good) == len(_QAM_ORDERS):
        return None
    lowest = good[0]
    # The target is only meaningful when every higher order is good as well.
    if any(order > lowest and order not in good for order in _QAM_ORDERS):
        return None
    return f"{lowest}QAM"


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


def _summary_health(issues) -> str:
    """Return aggregate health from summary health_issues."""
    if not issues:
        return "good"
    if any("critical" in i for i in issues):
        return "critical"
    if any("marginal" in i for i in issues):
        return "marginal"
    return "tolerated"


def _uncorr_pct_issue(uncorr_pct, et) -> str | None:
    """Return the summary issue for an uncorrectable-error percentage."""
    if uncorr_pct is None:
        return None
    if uncorr_pct >= et["critical"]:
        return "uncorr_errors_critical"
    if uncorr_pct >= et["warning"]:
        return "uncorr_errors_high"
    return None


def _has_comparable_baseline_schema(schema) -> bool:
    if isinstance(schema, float) and schema.is_integer():
        schema = int(schema)
    return isinstance(schema, int) and not isinstance(schema, bool) and schema >= _ERROR_BASELINE_SCHEMA


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
    last modem reboot. The analyzer keeps all available raw totals in the
    summary and channel data, but health should not treat pre-existing counters
    as active trouble forever. Once a predecessor of schema 3 or later exists, score the
    ratio from cumulative growth on channels that expose both counter types.
    Raw all-channel uncorrectable growth is tracked separately for evidence.
    Cohort changes and counter decreases establish a fresh baseline.

    A recent observed error_spike deliberately bypasses this baseline path so
    the existing spike-expiry window continues to hold the penalty until it
    expires.
    """
    if recent_spike_active or not isinstance(previous_analysis, dict):
        return

    summary = analysis.get("summary", {})
    previous_summary = previous_analysis.get("summary", {})
    current_counters = aggregate_error_counters(analysis.get("ds_channels", []))
    previous_counters = aggregate_error_counters(previous_analysis.get("ds_channels", []))
    previous_baseline = previous_summary.get("error_baseline")
    if not isinstance(previous_baseline, dict):
        previous_baseline = None

    previous_meta = previous_analysis.get("analysis_meta")
    previous_schema = previous_meta.get("analyzer_schema") if isinstance(previous_meta, dict) else None
    has_comparable_provenance = (
        "ds_comparable_correctable_errors" in previous_summary
        and "ds_comparable_uncorrectable_errors" in previous_summary
        and isinstance(previous_summary.get("error_counter_coverage"), dict)
    )
    growth = calculate_error_counter_growth(
        current_counters,
        previous_counters,
        previous_baseline=previous_baseline,
        force_fresh_baseline=not _has_comparable_baseline_schema(previous_schema) or not has_comparable_provenance,
    )

    et = _get_uncorr_thresholds()
    uncorr_pct = uncorrectable_percentage(
        growth.comparable_correctable_delta,
        growth.comparable_uncorrectable_delta,
        min_codewords=et["min_codewords"],
    )
    uncorr_issue = _uncorr_pct_issue(uncorr_pct, et)

    summary["ds_uncorr_pct"] = uncorr_pct
    summary["health_issues"] = [i for i in summary["health_issues"] if not _uncorr_issue(i)]
    if uncorr_issue:
        summary["health_issues"].append(uncorr_issue)
    summary["error_baseline"] = {
        "active": True,
        "basis": "comparable_channel_baseline_delta",
        "counter_reset": growth.counter_reset,
        "comparable_counter_reset": growth.comparable_counter_reset,
        "raw_uncorrectable_counter_reset": growth.raw_uncorrectable_counter_reset,
        "schema_baseline": growth.schema_baseline,
        "comparable_channel_keys": list(growth.comparable_channel_keys),
        "ds_comparable_correctable_baseline": growth.comparable_correctable_baseline,
        "ds_comparable_uncorrectable_baseline": growth.comparable_uncorrectable_baseline,
        "ds_raw_uncorrectable_baseline": growth.raw_uncorrectable_baseline,
        "ds_comparable_correctable_recent_delta": growth.comparable_correctable_recent_delta,
        "ds_comparable_uncorrectable_recent_delta": growth.comparable_uncorrectable_recent_delta,
        "ds_raw_uncorrectable_recent_delta": growth.raw_uncorrectable_recent_delta,
        "ds_comparable_correctable_delta": growth.comparable_correctable_delta,
        "ds_comparable_uncorrectable_delta": growth.comparable_uncorrectable_delta,
        "ds_raw_uncorrectable_delta": growth.raw_uncorrectable_delta,
        # Compatibility aliases now explicitly describe the comparable cohort.
        "ds_correctable_baseline": growth.comparable_correctable_baseline,
        "ds_uncorrectable_baseline": growth.comparable_uncorrectable_baseline,
        "ds_correctable_recent_delta": growth.comparable_correctable_recent_delta,
        "ds_uncorrectable_recent_delta": growth.comparable_uncorrectable_recent_delta,
        "ds_correctable_delta": growth.comparable_correctable_delta,
        "ds_uncorrectable_delta": growth.comparable_uncorrectable_delta,
    }
    summary["health"] = _summary_health(summary["health_issues"])


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

    summary["health"] = _summary_health(summary["health_issues"])


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
        "unsupported": total - calculated,
    }


def get_thresholds():
    """Return a copy of loaded thresholds, stripped of internal keys."""
    def _strip(obj):
        if not isinstance(obj, dict):
            return obj
        return {k: _strip(v) for k, v in obj.items() if not k.startswith("_")}
    return _strip(_t())


def threshold_snapshot() -> dict[str, Any]:
    """Return an independent plain-data capture of active thresholds and provenance."""
    return {
        "thresholds": copy.deepcopy(_t()),
        "profile": _profile_identity(),
    }


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


def _signal_family_fields(ds_channels, us_channels):
    """Summary fields built from the per-family channel statistics."""
    signal_families = _build_signal_family_summary(ds_channels, us_channels)
    ds_family_summaries = signal_families["downstream"]["families"]
    us_family_summaries = signal_families["upstream"]["families"]
    return {
        "signal_families": signal_families,
        "ds_scqam_power_avg": ds_family_summaries.get("sc_qam", {}).get("power", {}).get("avg"),
        "ds_scqam_snr_avg": ds_family_summaries.get("sc_qam", {}).get("snr", {}).get("avg"),
        "ds_ofdm_power_avg": ds_family_summaries.get("ofdm", {}).get("power", {}).get("avg"),
        "ds_ofdm_mer_avg": ds_family_summaries.get("ofdm", {}).get("mer", {}).get("avg"),
        "us_scqam_power_avg": us_family_summaries.get("sc_qam", {}).get("power", {}).get("avg"),
        "us_ofdma_power_avg": us_family_summaries.get("ofdma", {}).get("power", {}).get("avg"),
    }


def _assess_ds_channel(power, snr, modulation, family):
    """Assess one downstream channel. Returns (issues, modulation_health)."""
    issues = []
    if power is not None:
        pt = _get_ds_power_thresholds(modulation, channel_family=family)
        if power < pt["crit_min"] or power > pt["crit_max"]:
            issues.append("power critical")
        elif power < pt["warn_min"] or power > pt["warn_max"]:
            issues.append("power warning")
        elif power < pt["good_min"] or power > pt["good_max"]:
            issues.append("power tolerated")

    if snr is not None:
        st = _get_snr_thresholds(modulation, channel_family=family)
        if snr < st["crit_min"]:
            issues.append("snr critical")
        elif snr < st["warn_min"]:
            issues.append("snr warning")
        elif snr < st["good_min"]:
            issues.append("snr tolerated")

    modulation_health = _assess_ds_modulation(modulation, "3.0" if family == "sc_qam" else "3.1")
    mod_issue = _modulation_issue(modulation_health)
    if mod_issue:
        issues.append(mod_issue)
    return issues, modulation_health


def _keep_power_display_offset(raw_channel, channel):
    """Carry a driver's correction of the modem's displayed power to the UI."""
    offset = _parse_float(raw_channel.get("powerDisplayOffset"))
    if offset:
        channel["modem_power_offset_db"] = offset


def _assess_us_channel(power, modulation, family, docsis_ver):
    """Assess one upstream channel. Returns (issues, modulation_health).

    ``modulation`` is the profile QAM for OFDMA channels that report one.
    """
    issues = []
    if power is not None:
        pt = _get_us_power_thresholds(family)
        # Low transmit power is rated at most as a warning. It usually means
        # low attenuation in the home wiring, does not degrade the modem's
        # own link, and the operator specification defines no lower limit.
        # Rating the channel, not only the summary, keeps the channel badge,
        # line status and overall health consistent. The profile's critical
        # minimum still scales displays and explains older snapshots.
        # Low OFDMA power is not rated at all (see resolve_us_power_thresholds);
        # the OFDMA profile modulation carries the line quality there, and
        # sudden drops are reported as power_change events.
        rate_low = pt["rate_low"]
        plausible_min = pt["plausible_min"]
        if power > pt["crit_max"]:
            issues.append("power critical high")
        elif plausible_min is not None and power < plausible_min:
            issues.append("power warning low")
        elif rate_low and power < pt["warn_min"]:
            issues.append("power warning low")
        elif power > pt["warn_max"]:
            issues.append("power warning high")
        elif rate_low and power < pt["good_min"]:
            issues.append("power tolerated low")
        elif power > pt["good_max"]:
            issues.append("power tolerated high")
    modulation_health = _assess_us_modulation(modulation, family, docsis_ver)
    mod_issue = _modulation_issue(modulation_health)
    if mod_issue:
        issues.append(mod_issue)
    return issues, modulation_health


def _read_channel(direction, ch, docsis_ver):
    """Return a raw channel's (modulation, profile_modulation, channel family)."""
    modulation = ch.get("modulation") or ch.get("type", "")
    profile_modulation = ch.get("profile_modulation") or ch.get("profileModulation")
    family = _shared_classify_channel_family(direction, {
        "type": ch.get("type", ""),
        "multiplex": ch.get("multiplex", ""),
        "modulation": modulation,
        "profile_modulation": profile_modulation,
        "docsis_version": docsis_ver,
    })
    return modulation, profile_modulation, family


def _channel_entry(ch, measured, *, docsis_ver, family, assessment, profile_modulation, default_symbol_rate):
    """Build one analyzed channel from its raw row, parsed values and assessment."""
    issues, modulation_health = assessment
    channel = {
        "channel_id": _parse_channel_id(ch.get("channelID", 0)),
        "frequency": ch.get("frequency", ""),
        **measured,
        "docsis_version": docsis_ver,
        "channel_family": family,
        "health": _channel_health(issues),
        "health_detail": " + ".join(issues),
        "theoretical_bitrate": (
            _channel_bitrate_mbps(measured["modulation"], ch.get("symbolRate"), default_symbol_rate)
            if family == "sc_qam"
            else None
        ),
        **_metric_healths(issues),
        "modulation_health": modulation_health,
    }
    if profile_modulation:
        channel["profile_modulation"] = profile_modulation
    return channel


def _build_ds_channel(ch, docsis_ver):
    modulation, profile_modulation, family = _read_channel("ds", ch, docsis_ver)
    power = _parse_float(ch.get("powerLevel"))
    if docsis_ver == "3.0":
        family = "sc_qam"
        mse = _parse_float(ch.get("mse"))
        snr = abs(mse) if mse is not None else None
    else:
        snr = _parse_float(ch.get("mer"))
    measured = {
        "power": power,
        "modulation": modulation,
        "snr": snr,
        "correctable_errors": ch.get("corrErrors"),
        "uncorrectable_errors": ch.get("nonCorrErrors"),
    }
    return _channel_entry(
        ch,
        measured,
        docsis_ver=docsis_ver,
        family=family,
        assessment=_assess_ds_channel(power, snr, modulation, family),
        profile_modulation=profile_modulation,
        default_symbol_rate=_DEFAULT_DS_SC_QAM_SYMBOL_RATE,
    )


def _build_us_channel(ch, docsis_ver):
    modulation, profile_modulation, family = _read_channel("us", ch, docsis_ver)
    power = _parse_float(ch.get("powerLevel"))
    assessed_modulation = profile_modulation if family == "ofdma" and profile_modulation else modulation
    channel = _channel_entry(
        ch,
        {"power": power, "modulation": modulation, "multiplex": ch.get("multiplex", "")},
        docsis_ver=docsis_ver,
        # DOCSIS 3.0 upstream channels are stored as SC-QAM; their rating still uses the classified family.
        family=family if docsis_ver == "3.1" else "sc_qam",
        assessment=_assess_us_channel(power, assessed_modulation, family, docsis_ver),
        profile_modulation=profile_modulation,
        default_symbol_rate=_DEFAULT_US_SC_QAM_SYMBOL_RATE,
    )
    _keep_power_display_offset(ch, channel)
    return channel


def _aggregate_issue(channels, metric, critical, marginal, tolerated):
    """Return the summary issue for the worst channel health of one metric, or None."""
    healths = {c.get(f"{metric}_health") for c in channels}
    if "critical" in healths:
        return critical
    if "warning" in healths:
        return marginal
    if "tolerated" in healths:
        return tolerated
    return None


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
        key = "docsis31" if data.get("docsis", "3.1") == "3.1" else "docsis30"
        data = {"channelDs": {key: data["downstream"]}, "channelUs": {key: data["upstream"]}}

    ds = data.get("channelDs", {})
    us = data.get("channelUs", {})
    ds_channels = sorted(
        [_build_ds_channel(ch, "3.0") for ch in ds.get("docsis30", [])]
        + [_build_ds_channel(ch, "3.1") for ch in ds.get("docsis31", [])],
        key=lambda c: c["channel_id"],
    )
    us_channels = sorted(
        [_build_us_channel(ch, "3.0") for ch in us.get("docsis30", [])]
        + [_build_us_channel(ch, "3.1") for ch in us.get("docsis31", [])],
        key=lambda c: c["channel_id"],
    )

    # --- Summary metrics ---
    stats = {
        "ds_power": _stats([c["power"] for c in ds_channels]),
        "us_power": _stats([c["power"] for c in us_channels]),
        "ds_snr": _stats([c["snr"] for c in ds_channels]),
    }

    error_counters = aggregate_error_counters(ds_channels)
    total_corr = error_counters.raw_correctable
    total_uncorr = error_counters.raw_uncorrectable

    ds_bitrates = [c["theoretical_bitrate"] for c in ds_channels if c.get("theoretical_bitrate") is not None]
    ds_capacity = round(sum(ds_bitrates), 1) if ds_bitrates else None
    us_bitrates = [c["theoretical_bitrate"] for c in us_channels if c["theoretical_bitrate"] is not None]
    us_capacity = round(sum(us_bitrates), 1) if us_bitrates else None
    capacity_coverage = {
        "downstream": _capacity_coverage(ds_channels),
        "upstream": _capacity_coverage(us_channels),
    }

    summary = {
        "ds_total": len(ds_channels),
        "us_total": len(us_channels),
        **{f"{name}_{part}": values[part] for name, values in stats.items() for part in ("min", "max", "avg")},
        "ds_correctable_errors": total_corr,
        "ds_uncorrectable_errors": total_uncorr,
        "ds_comparable_correctable_errors": error_counters.comparable_correctable,
        "ds_comparable_uncorrectable_errors": error_counters.comparable_uncorrectable,
        "error_counter_coverage": error_counters.coverage_dict(),
        "errors_supported": error_counters.supported,
        "ds_capacity_mbps": ds_capacity,
        "us_capacity_mbps": us_capacity,
        "capacity_coverage": capacity_coverage,
        **_signal_family_fields(ds_channels, us_channels),
    }

    # --- Overall health (aggregate from per-channel assessments) ---
    issues = [
        _aggregate_issue(ds_channels, "power", "ds_power_critical", "ds_power_marginal", "ds_power_tolerated"),
        _aggregate_issue(
            ds_channels, "modulation", "ds_modulation_critical", "ds_modulation_marginal", "ds_modulation_tolerated"
        ),
    ]

    # US power: aggregate from individual channel health_detail (directional).
    # Low power caps at marginal (see _assess_us_channel). Snapshots stored
    # before analyzer schema 4 may still carry us_power_critical_low, which
    # keeps its texts so their history stays readable.
    us_crit_high = any("power critical high" in c["health_detail"] for c in us_channels)
    us_warn_low = any("power warning low" in c["health_detail"] for c in us_channels)
    us_warn_high = any("power warning high" in c["health_detail"] for c in us_channels)
    us_tol_low = any("power tolerated low" in c["health_detail"] for c in us_channels)
    us_tol_high = any("power tolerated high" in c["health_detail"] for c in us_channels)
    if us_crit_high:
        issues.append("us_power_critical_high")
    if us_warn_low:
        issues.append("us_power_marginal_low")
    if us_warn_high and not us_crit_high:
        issues.append("us_power_marginal_high")
    if us_tol_low and not us_warn_low:
        issues.append("us_power_tolerated_low")
    if us_tol_high and not us_crit_high and not us_warn_high:
        issues.append("us_power_tolerated_high")

    et = _get_uncorr_thresholds()
    uncorr_pct = uncorrectable_percentage(
        error_counters.comparable_correctable,
        error_counters.comparable_uncorrectable,
        min_codewords=et["min_codewords"],
    )
    issues += [
        _aggregate_issue(
            us_channels, "modulation", "us_modulation_critical", "us_modulation_marginal", "us_modulation_tolerated"
        ),
        _aggregate_issue(ds_channels, "snr", "snr_critical", "snr_marginal", "snr_tolerated"),
        _uncorr_pct_issue(uncorr_pct, et),
    ]
    issues = [issue for issue in issues if issue]
    summary["ds_uncorr_pct"] = uncorr_pct
    summary["health"] = _summary_health(issues)
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
