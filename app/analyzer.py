"""DOCSIS channel health analysis with configurable thresholds,
OFDMA analysis, and channel heatmap data."""

import logging

log = logging.getLogger("docsis.analyzer")

# --- Reference thresholds ---
# Downstream Power (dBmV): ideal 0, good -7..+7, marginal -10..+10
DS_POWER_WARN = 7.0
DS_POWER_CRIT = 10.0

# Upstream Power (dBmV): good 35-49, marginal 50-54, bad >54
US_POWER_WARN = 50.0
US_POWER_CRIT = 54.0

# SNR / MER (dB): good >30, marginal 25-30, bad <25
SNR_WARN = 30.0
SNR_CRIT = 25.0

# Uncorrectable errors threshold
UNCORR_ERRORS_CRIT = 10000

# QAM quality ranking (higher = better)
QAM_QUALITY = {
    "4096QAM": 100,
    "2048QAM": 95,
    "1024QAM": 90,
    "512QAM": 80,
    "256QAM": 70,
    "128QAM": 55,
    "64QAM": 40,
    "32QAM": 30,
    "16QAM": 20,
    "QPSK": 10,
    "BPSK": 5,
}


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

    if abs(power) > DS_POWER_CRIT:
        issues.append("power critical")
    elif abs(power) > DS_POWER_WARN:
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

    if power > US_POWER_CRIT:
        issues.append("power critical")
    elif power > US_POWER_WARN:
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
    if ds_powers and (min(ds_powers) < -DS_POWER_CRIT or max(ds_powers) > DS_POWER_CRIT):
        issues.append("ds_power_critical")
    if us_powers and max(us_powers) > US_POWER_CRIT:
        issues.append("us_power_critical")
    elif us_powers and max(us_powers) > US_POWER_WARN:
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


# ── OFDMA Analysis ──

def analyze_ofdma(data: dict) -> dict:
    """Analyze OFDMA (DOCSIS 3.1) channel usage.

    Detects whether the modem uses wide OFDMA blocks vs many narrow SC-QAMs.
    Returns dict with:
        has_ofdma_ds: bool
        has_ofdma_us: bool
        ds_31_count: int (number of DOCSIS 3.1 DS channels)
        ds_30_count: int (number of DOCSIS 3.0 DS channels)
        us_31_count: int (number of DOCSIS 3.1 US channels)
        us_30_count: int (number of DOCSIS 3.0 US channels)
        ofdma_type: str ("wide_block", "narrow_scqam", "mixed", "none")
        assessment: str (human-readable assessment)
    """
    ds = data.get("channelDs", {})
    us = data.get("channelUs", {})

    ds31_count = len(ds.get("docsis31", []))
    ds30_count = len(ds.get("docsis30", []))
    us31_count = len(us.get("docsis31", []))
    us30_count = len(us.get("docsis30", []))

    has_ofdma_ds = ds31_count > 0
    has_ofdma_us = us31_count > 0

    # Determine OFDMA type
    total_ds = ds31_count + ds30_count
    if not has_ofdma_ds:
        ofdma_type = "none"
        assessment = "No OFDMA (DOCSIS 3.1) channels detected. Using SC-QAM only (DOCSIS 3.0)."
    elif ds30_count == 0:
        ofdma_type = "wide_block"
        assessment = "Using wide OFDMA block exclusively. All downstream on DOCSIS 3.1."
    elif ds31_count <= 2 and ds30_count > 10:
        ofdma_type = "narrow_scqam"
        assessment = (
            f"Primarily using narrow SC-QAM channels ({ds30_count} x DOCSIS 3.0) "
            f"with {ds31_count} OFDMA channel(s). This is the typical hybrid config."
        )
    else:
        ofdma_type = "mixed"
        assessment = (
            f"Mixed configuration: {ds31_count} OFDMA + {ds30_count} SC-QAM channels."
        )

    return {
        "has_ofdma_ds": has_ofdma_ds,
        "has_ofdma_us": has_ofdma_us,
        "ds_31_count": ds31_count,
        "ds_30_count": ds30_count,
        "us_31_count": us31_count,
        "us_30_count": us30_count,
        "ofdma_type": ofdma_type,
        "assessment": assessment,
    }


# ── Channel Heatmap ──

def build_channel_heatmap(analysis: dict) -> dict:
    """Build a heatmap data structure for all channels, color-coded by quality.

    Returns dict with:
        ds: list of {channel_id, frequency, quality, color, modulation, power, snr, health}
        us: list of {channel_id, frequency, quality, color, modulation, power, health}

    quality: 0-100 score based on power, SNR, and modulation
    color: "green", "yellow", "orange", "red" based on quality
    """
    ds_heatmap = []
    for ch in analysis.get("ds_channels", []):
        quality = _compute_ds_quality(ch)
        ds_heatmap.append({
            "channel_id": ch["channel_id"],
            "frequency": ch["frequency"],
            "quality": quality,
            "color": _quality_to_color(quality),
            "modulation": ch["modulation"],
            "power": ch["power"],
            "snr": ch.get("snr"),
            "health": ch["health"],
            "correctable_errors": ch.get("correctable_errors", 0),
            "uncorrectable_errors": ch.get("uncorrectable_errors", 0),
            "docsis_version": ch["docsis_version"],
        })

    us_heatmap = []
    for ch in analysis.get("us_channels", []):
        quality = _compute_us_quality(ch)
        us_heatmap.append({
            "channel_id": ch["channel_id"],
            "frequency": ch["frequency"],
            "quality": quality,
            "color": _quality_to_color(quality),
            "modulation": ch["modulation"],
            "power": ch["power"],
            "health": ch["health"],
            "docsis_version": ch["docsis_version"],
        })

    return {"ds": ds_heatmap, "us": us_heatmap}


def _compute_ds_quality(ch: dict) -> int:
    """Compute a 0-100 quality score for a downstream channel."""
    score = 100

    # Power penalty (ideal = 0, bad > ±10)
    power = abs(ch.get("power", 0))
    if power > DS_POWER_CRIT:
        score -= 40
    elif power > DS_POWER_WARN:
        score -= 20
    elif power > 3:
        score -= 5

    # SNR penalty
    snr = ch.get("snr")
    if snr is not None:
        if snr < SNR_CRIT:
            score -= 40
        elif snr < SNR_WARN:
            score -= 20
        elif snr < 35:
            score -= 5

    # Modulation bonus/penalty
    mod = ch.get("modulation", "")
    mod_quality = QAM_QUALITY.get(mod, 50)
    score = score * (mod_quality / 100)

    return max(0, min(100, int(score)))


def _compute_us_quality(ch: dict) -> int:
    """Compute a 0-100 quality score for an upstream channel."""
    score = 100

    power = ch.get("power", 0)
    if power > US_POWER_CRIT:
        score -= 40
    elif power > US_POWER_WARN:
        score -= 20
    elif power < 35:
        score -= 10

    # Modulation
    mod = ch.get("modulation", "")
    mod_quality = QAM_QUALITY.get(mod, 50)
    score = score * (mod_quality / 100)

    return max(0, min(100, int(score)))


def _quality_to_color(quality: int) -> str:
    """Map quality score to a color."""
    if quality >= 80:
        return "green"
    elif quality >= 60:
        return "yellow"
    elif quality >= 40:
        return "orange"
    return "red"


# ── Before/After Comparison ──

def compare_periods(snapshots_before: list[dict], snapshots_after: list[dict]) -> dict:
    """Compare two sets of snapshots (before/after a change).

    Returns dict with:
        before: averaged summary metrics
        after: averaged summary metrics
        changes: dict of metric -> {before, after, delta, improved}
    """
    def _avg_summary(snapshots):
        if not snapshots:
            return {}
        keys = [
            "ds_power_min", "ds_power_max", "ds_power_avg",
            "us_power_min", "us_power_max", "us_power_avg",
            "ds_snr_min", "ds_snr_avg",
            "ds_correctable_errors", "ds_uncorrectable_errors",
        ]
        result = {}
        for key in keys:
            values = [s.get("summary", {}).get(key, 0) for s in snapshots]
            if values:
                result[key] = round(sum(values) / len(values), 2)
        # Health distribution
        healths = [s.get("summary", {}).get("health", "unknown") for s in snapshots]
        result["health_distribution"] = {
            h: healths.count(h) for h in set(healths)
        }
        result["total_snapshots"] = len(snapshots)
        return result

    before_avg = _avg_summary(snapshots_before)
    after_avg = _avg_summary(snapshots_after)

    changes = {}
    improvement_metrics = {"ds_snr_min", "ds_snr_avg"}  # higher is better
    degradation_metrics = {
        "ds_power_max", "us_power_max",
        "ds_correctable_errors", "ds_uncorrectable_errors",
    }  # lower is better (for abs values)

    for key in before_avg:
        if key in ("health_distribution", "total_snapshots"):
            continue
        bval = before_avg.get(key, 0)
        aval = after_avg.get(key, 0)
        delta = round(aval - bval, 2)

        if key in improvement_metrics:
            improved = delta > 0
        elif key in degradation_metrics:
            improved = delta < 0
        else:
            improved = abs(aval) < abs(bval)

        changes[key] = {
            "before": bval,
            "after": aval,
            "delta": delta,
            "improved": improved,
        }

    return {
        "before": before_avg,
        "after": after_avg,
        "changes": changes,
    }
