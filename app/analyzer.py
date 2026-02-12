"""DOCSIS channel health analysis with configurable thresholds."""

import logging

log = logging.getLogger("docsis.analyzer")

# --- Reference thresholds (based on Vodafone VFKD guidelines, 256QAM) ---
# Downstream Power (dBmV): asymmetric range
# Regelkonform: -3.9 to 13.0, toleriert: -5.9/-4.0 / 13.1-18.0, sofort: <-8 / >20
DS_POWER_LOW_GOOD = -4.0
DS_POWER_HIGH_GOOD = 13.0
DS_POWER_LOW_WARN = -6.0
DS_POWER_HIGH_WARN = 18.0
DS_POWER_LOW_CRIT = -8.0
DS_POWER_HIGH_CRIT = 20.0

# Upstream Power (dBmV): based on VFKD 64QAM
# Regelkonform: 41.1-47.0, toleriert: 38.1-41.0 / 47.1-50.0, sofort: <35 / >53
US_POWER_LOW_GOOD = 41.0
US_POWER_HIGH_GOOD = 47.0
US_POWER_LOW_WARN = 38.0
US_POWER_HIGH_WARN = 50.0
US_POWER_LOW_CRIT = 35.0
US_POWER_HIGH_CRIT = 53.0

# SNR / MER (dB): good >33, marginal 29-33, bad <29
# Based on Vodafone VFKD guidelines: 256QAM regelkonform > 33.1 dB
SNR_WARN = 33.0
SNR_CRIT = 29.0

# Uncorrectable errors threshold
UNCORR_ERRORS_CRIT = 10000


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
    power = _parse_float(ch.get("powerLevel"))

    if power < DS_POWER_LOW_CRIT or power > DS_POWER_HIGH_CRIT:
        issues.append("power critical")
    elif power < DS_POWER_LOW_GOOD or power > DS_POWER_HIGH_GOOD:
        issues.append("power warning")

    if docsis_ver == "3.0" and ch.get("mse"):
        snr = abs(_parse_float(ch["mse"]))
        if snr < SNR_CRIT:
            issues.append("snr critical")
        elif snr < SNR_WARN:
            issues.append("snr warning")
    elif docsis_ver == "3.1" and ch.get("mer"):
        snr = _parse_float(ch["mer"])
        if snr < SNR_CRIT:
            issues.append("snr critical")
        elif snr < SNR_WARN:
            issues.append("snr warning")

    return _channel_health(issues), _health_detail(issues)


def _assess_us_channel(ch):
    """Assess a single upstream channel. Returns (health, health_detail)."""
    issues = []
    power = _parse_float(ch.get("powerLevel"))

    if power < US_POWER_LOW_CRIT or power > US_POWER_HIGH_CRIT:
        issues.append("power critical")
    elif power < US_POWER_LOW_GOOD or power > US_POWER_HIGH_GOOD:
        issues.append("power warning")

    return _channel_health(issues), _health_detail(issues)


def analyze(data: dict) -> dict:
    """Analyze DOCSIS data and return structured result.

    Returns dict with keys:
        summary: dict of summary metrics
        ds_channels: list of downstream channel dicts
        us_channels: list of upstream channel dicts
    """
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
        power = _parse_float(ch.get("powerLevel"))
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
        health, health_detail = _assess_us_channel(ch)
        us_channels.append({
            "channel_id": ch.get("channelID", 0),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(ch.get("powerLevel")),
            "modulation": ch.get("modulation") or ch.get("type", ""),
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.0",
            "health": health,
            "health_detail": health_detail,
        })
    for ch in us31:
        health, health_detail = _assess_us_channel(ch)
        us_channels.append({
            "channel_id": ch.get("channelID", 0),
            "frequency": ch.get("frequency", ""),
            "power": _parse_float(ch.get("powerLevel")),
            "modulation": ch.get("modulation") or ch.get("type", ""),
            "multiplex": ch.get("multiplex", ""),
            "docsis_version": "3.1",
            "health": health,
            "health_detail": health_detail,
        })

    us_channels.sort(key=lambda c: c["channel_id"])

    # --- Summary metrics ---
    ds_powers = [c["power"] for c in ds_channels]
    us_powers = [c["power"] for c in us_channels]
    ds_snrs = [c["snr"] for c in ds_channels if c["snr"] is not None]

    total_corr = sum(c["correctable_errors"] for c in ds_channels)
    total_uncorr = sum(c["uncorrectable_errors"] for c in ds_channels)

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
        "ds_snr_avg": round(sum(ds_snrs) / len(ds_snrs), 1) if ds_snrs else 0,
        "ds_correctable_errors": total_corr,
        "ds_uncorrectable_errors": total_uncorr,
    }

    # --- Overall health ---
    issues = []
    if ds_powers and (min(ds_powers) < DS_POWER_LOW_CRIT or max(ds_powers) > DS_POWER_HIGH_CRIT):
        issues.append("ds_power_critical")
    elif ds_powers and (min(ds_powers) < DS_POWER_LOW_GOOD or max(ds_powers) > DS_POWER_HIGH_GOOD):
        issues.append("ds_power_warn")
    if us_powers and (min(us_powers) < US_POWER_LOW_CRIT or max(us_powers) > US_POWER_HIGH_CRIT):
        issues.append("us_power_critical")
    elif us_powers and (min(us_powers) < US_POWER_LOW_GOOD or max(us_powers) > US_POWER_HIGH_GOOD):
        issues.append("us_power_warn")
    if ds_snrs and min(ds_snrs) < SNR_CRIT:
        issues.append("snr_critical")
    elif ds_snrs and min(ds_snrs) < SNR_WARN:
        issues.append("snr_warn")
    if total_uncorr > UNCORR_ERRORS_CRIT:
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
