"""Pure dashboard signal ranges and presentation from explicit snapshot data."""

import math

from .docsis_utils import classify_channel_family, qam_rank


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


def build_metric_ranges(analysis, thresholds):
    """Project analysis into template ranges using the supplied active thresholds."""
    if not analysis:
        return {}
    summary = analysis.get("summary", {})
    ds_channels = analysis.get("ds_channels", [])
    ds_power_threshold = _choose_threshold(
        thresholds.get("downstream_power", {}),
        _channel_threshold_candidates(ds_channels) + ["256QAM", "4096QAM", "1024QAM", "64QAM"],
    )
    us_power_threshold = _choose_threshold(
        thresholds.get("upstream_power", {}),
        (["ofdma"] if has_us_ofdma(analysis) else [])
        + ["sc_qam", "ofdma"],
    )
    snr_display = build_home_snr_display_context(analysis)
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

    def _add_family_range(range_key, family, metric_name, candidates, threshold_group="snr"):
        values = _family_metric_values(family, metric_name)
        if not values:
            return
        threshold = _choose_threshold(thresholds.get(threshold_group, {}), candidates)
        if metric_name == "power":
            ranges[range_key] = _power_metric_range(*values, threshold, "dBmV")
        else:
            ranges[range_key] = _snr_metric_range(*values, threshold)

    sc_qam_candidates = _family_modulation_threshold_candidates(ds_families.get("sc_qam")) + ["256QAM", "64QAM"]
    ofdm_candidates = ["ofdm"] + _family_modulation_threshold_candidates(ds_families.get("ofdm")) + ["4096QAM", "1024QAM"]
    _add_family_range("ds_sc_qam_power", ds_families.get("sc_qam"), "power", sc_qam_candidates, "downstream_power")
    _add_family_range("ds_ofdm_power", ds_families.get("ofdm"), "power", ofdm_candidates, "downstream_power")
    _add_family_range("ds_sc_qam_snr", ds_families.get("sc_qam"), "snr", sc_qam_candidates)
    _add_family_range("ds_ofdm_mer", ds_families.get("ofdm"), "mer", ofdm_candidates)
    _add_family_range("us_sc_qam_power", us_families.get("sc_qam"), "power", ["sc_qam"], "upstream_power")
    _add_family_range("us_ofdma_power", us_families.get("ofdma"), "power", ["ofdma"], "upstream_power")
    return ranges


def _snr_channel_family(channel):
    """Use normalized analyzer metadata, with shared classification for legacy data."""
    family = channel.get("channel_family")
    # Only normalized downstream values are authoritative; unknown or invalid
    # metadata must take the same shared fallback path as legacy snapshots.
    if family in ("sc_qam", "ofdm"):
        return family
    return classify_channel_family("ds", channel)


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


def build_home_snr_display_context(analysis):
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


def build_home_modulation_context(analysis):
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


def build_capacity_context(analysis, booked_download=0, booked_upload=0):
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


def compute_uncorr_pct(analysis):
    """Compute log-scale percentage for uncorrectable errors gauge."""
    if not analysis:
        return 0
    uncorr = analysis.get("summary", {}).get("ds_uncorrectable_errors") or 0
    return min(100, math.log10(max(1, uncorr)) / 5 * 100)

def has_us_ofdma(analysis):
    """Check if any upstream channel uses DOCSIS 3.1+ (OFDMA)."""
    if not analysis:
        return True  # don't warn when no data yet
    return any(
        str(ch.get("docsis_version", "")) in ("3.1", "4.0") for ch in analysis.get("us_channels", [])
    )
