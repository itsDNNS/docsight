"""Prometheus text format exposition formatter for DOCSight metrics.

Pure function — no Flask dependency, no side effects.
"""

from .analyzer import _parse_qam_order

# Health string to numeric mapping
_HEALTH_MAP = {"good": 0, "tolerated": 1, "marginal": 2, "critical": 3}


def _frequency_label(value):
    """Normalize channel frequency for Prometheus labels.

    Returns a string in MHz where possible, without the trailing unit.
    """
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered.endswith("mhz"):
        text = text[:-3].strip()
        return text or None

    try:
        numeric = float(text)
    except ValueError:
        return text

    if abs(numeric) >= 1_000_000:
        numeric /= 1_000_000

    if numeric.is_integer():
        return str(int(numeric))

    return f"{numeric:.3f}".rstrip("0").rstrip(".")


def _channel_labels(channel):
    """Build Prometheus labels for a DOCSIS channel metric."""
    labels = {"channel_id": str(channel["channel_id"])}
    frequency = _frequency_label(channel.get("frequency"))
    if frequency is not None:
        labels["frequency"] = frequency
    return labels


def _metric(lines, help_text, metric_type, name, value, labels=None):
    """Append HELP, TYPE, and a single value line to lines list."""
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {metric_type}")
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")


def _metric_family_open(lines, help_text, metric_type, name):
    """Append HELP and TYPE for a multi-value metric family."""
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {metric_type}")


def _metric_value(lines, name, value, labels=None):
    """Append a single value line for an already-opened metric family."""
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")


def format_metrics(analysis, device_info, connection_info, last_poll_timestamp):
    """Format DOCSight state as Prometheus text exposition format.

    Args:
        analysis: dict from analyzer.analyze() or None
        device_info: dict from driver.get_device_info() or None
        connection_info: dict from driver.get_connection_info() or None
        last_poll_timestamp: float (Unix epoch) or 0.0

    Returns:
        str: Prometheus text exposition format string, ending with newline
    """
    lines = []

    # --- Health status ---
    if analysis is not None:
        health_str = analysis.get("summary", {}).get("health", "good")
        health_val = _HEALTH_MAP.get(health_str, 4)
    else:
        health_val = 4

    _metric(
        lines,
        "DOCSIS signal health status: 0=good 1=tolerated 2=marginal 3=critical 4=unknown",
        "gauge",
        "docsight_health_status",
        health_val,
    )

    # --- Channel counts ---
    if analysis is not None:
        summary = analysis.get("summary", {})
        ds_total = summary.get("ds_total", 0)
        us_total = summary.get("us_total", 0)
    else:
        ds_total = 0
        us_total = 0

    _metric(
        lines,
        "Number of active downstream channels",
        "gauge",
        "docsight_downstream_channels_total",
        ds_total,
    )
    _metric(
        lines,
        "Number of active upstream channels",
        "gauge",
        "docsight_upstream_channels_total",
        us_total,
    )

    # --- Downstream channel metrics ---
    ds_channels = analysis.get("ds_channels", []) if analysis else []

    if ds_channels:
        _metric_family_open(
            lines,
            "Downstream channel receive power level in dBmV",
            "gauge",
            "docsight_downstream_power_dbmv",
        )
        for ch in ds_channels:
            ch["channel_id"]
            if ch.get("power") is not None:
                _metric_value(lines, "docsight_downstream_power_dbmv", ch["power"],
                              _channel_labels(ch))

        _metric_family_open(
            lines,
            "Downstream channel signal-to-noise ratio in dB",
            "gauge",
            "docsight_downstream_snr_db",
        )
        for ch in ds_channels:
            if ch.get("snr") is not None:
                _metric_value(lines, "docsight_downstream_snr_db", ch["snr"],
                              _channel_labels(ch))

        _metric_family_open(
            lines,
            "Downstream channel correctable codeword errors (cumulative)",
            "counter",
            "docsight_downstream_corrected_errors_total",
        )
        for ch in ds_channels:
            if ch.get("correctable_errors") is not None:
                _metric_value(lines, "docsight_downstream_corrected_errors_total",
                              ch["correctable_errors"],
                              _channel_labels(ch))

        _metric_family_open(
            lines,
            "Downstream channel uncorrectable codeword errors (cumulative)",
            "counter",
            "docsight_downstream_uncorrected_errors_total",
        )
        for ch in ds_channels:
            if ch.get("uncorrectable_errors") is not None:
                _metric_value(lines, "docsight_downstream_uncorrected_errors_total",
                              ch["uncorrectable_errors"],
                              _channel_labels(ch))

        _metric_family_open(
            lines,
            "Downstream channel QAM modulation order (e.g. 256 for 256-QAM)",
            "gauge",
            "docsight_downstream_modulation",
        )
        for ch in ds_channels:
            qam = _parse_qam_order(ch.get("modulation", ""))
            if qam is not None:
                _metric_value(lines, "docsight_downstream_modulation", qam,
                              _channel_labels(ch))

    # --- Upstream channel metrics ---
    us_channels = analysis.get("us_channels", []) if analysis else []

    if us_channels:
        _metric_family_open(
            lines,
            "Upstream channel transmit power level in dBmV",
            "gauge",
            "docsight_upstream_power_dbmv",
        )
        for ch in us_channels:
            if ch.get("power") is not None:
                _metric_value(lines, "docsight_upstream_power_dbmv", ch["power"],
                              _channel_labels(ch))

        _metric_family_open(
            lines,
            "Upstream channel QAM modulation order (e.g. 64 for 64-QAM)",
            "gauge",
            "docsight_upstream_modulation",
        )
        for ch in us_channels:
            qam = _parse_qam_order(ch.get("modulation", ""))
            if qam is not None:
                _metric_value(lines, "docsight_upstream_modulation", qam,
                              _channel_labels(ch))

    # --- Device info ---
    if device_info is not None:
        model = device_info.get("model", "")
        sw_version = device_info.get("sw_version", "")
        _metric(
            lines,
            "Device information (model, firmware version)",
            "gauge",
            "docsight_device_info",
            1,
            {"model": model, "sw_version": sw_version},
        )
        uptime = device_info.get("uptime_seconds")
        if uptime is not None:
            _metric(
                lines,
                "Device uptime in seconds",
                "gauge",
                "docsight_device_uptime_seconds",
                uptime,
            )

    # --- Connection info ---
    if connection_info is not None:
        ds_kbps = connection_info.get("max_downstream_kbps")
        us_kbps = connection_info.get("max_upstream_kbps")
        if ds_kbps is not None:
            _metric(
                lines,
                "Maximum downstream speed in kbps as reported by modem",
                "gauge",
                "docsight_connection_max_downstream_kbps",
                ds_kbps,
            )
        if us_kbps is not None:
            _metric(
                lines,
                "Maximum upstream speed in kbps as reported by modem",
                "gauge",
                "docsight_connection_max_upstream_kbps",
                us_kbps,
            )

    # --- Poll timestamp ---
    _metric(
        lines,
        "Unix timestamp of the last successful modem data poll",
        "gauge",
        "docsight_last_poll_timestamp_seconds",
        float(last_poll_timestamp),
    )

    return "\n".join(lines) + "\n"
