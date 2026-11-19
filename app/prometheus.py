"""Prometheus text format exposition formatter for DOCSight metrics.

Pure function -- no Flask dependency, no side effects.
"""

from __future__ import annotations

from .docsis_utils import SUMMARY_HEALTH_RANK, parse_qam_order as _parse_qam_order
from .types import AnalysisResult, ConnectionInfo, DeviceInfo


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


def _escape_label_value(value):
    """Escape a Prometheus label value per the text exposition spec:
    backslash, double-quote, and newline."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _format_labels(labels):
    return ",".join(f'{k}="{_escape_label_value(v)}"' for k, v in labels.items())


def _metric_family_open(lines, help_text, metric_type, name):
    """Append HELP and TYPE for a multi-value metric family."""
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {metric_type}")


def _metric_value(lines, name, value, labels=None):
    """Append a single value line for an already-opened metric family."""
    if labels:
        lines.append(f"{name}{{{_format_labels(labels)}}} {value}")
    else:
        lines.append(f"{name} {value}")


def _metric(lines, help_text, metric_type, name, value, labels=None):
    """Append HELP, TYPE, and a single value line to lines list."""
    _metric_family_open(lines, help_text, metric_type, name)
    _metric_value(lines, name, value, labels)


# Per-channel metric families in output order:
# (analysis key, metric name, type, help text, value accessor).
_CHANNEL_METRICS = (
    ("ds_channels", "docsight_downstream_power_dbmv", "gauge",
     "Downstream channel receive power level in dBmV", lambda ch: ch.get("power")),
    ("ds_channels", "docsight_downstream_snr_db", "gauge",
     "Downstream channel signal-to-noise ratio in dB", lambda ch: ch.get("snr")),
    ("ds_channels", "docsight_downstream_corrected_errors_total", "counter",
     "Downstream channel correctable codeword errors (cumulative)", lambda ch: ch.get("correctable_errors")),
    ("ds_channels", "docsight_downstream_uncorrected_errors_total", "counter",
     "Downstream channel uncorrectable codeword errors (cumulative)", lambda ch: ch.get("uncorrectable_errors")),
    ("ds_channels", "docsight_downstream_modulation", "gauge",
     "Downstream channel QAM modulation order (e.g. 256 for 256-QAM)",
     lambda ch: _parse_qam_order(ch.get("modulation", ""))),
    ("us_channels", "docsight_upstream_power_dbmv", "gauge",
     "Upstream channel transmit power level in dBmV", lambda ch: ch.get("power")),
    ("us_channels", "docsight_upstream_modulation", "gauge",
     "Upstream channel QAM modulation order (e.g. 64 for 64-QAM)",
     lambda ch: _parse_qam_order(ch.get("modulation", ""))),
)

# Info metrics whose label carries a mutable device value:
# (device_info key, metric name, label name, help text prefix).
_DEVICE_INFO_LABEL_METRICS = (
    ("reboot_reason", "docsight_last_reboot_reason_info", "reason", "Reason reported for the last modem reboot"),
    ("wan_ipv4", "docsight_device_wan_ipv4_info", "wan_ipv4", "WAN IPv4 address"),
    ("wan_ipv6", "docsight_device_wan_ipv6_info", "wan_ipv6", "WAN IPv6 address"),
)


def format_metrics(
    analysis: AnalysisResult | None,
    device_info: DeviceInfo | None,
    connection_info: ConnectionInfo | None,
    last_poll_timestamp: float,
) -> str:
    """Format DOCSight state as Prometheus text exposition format.

    Args:
        analysis: AnalysisResult from analyzer.analyze() or None
        device_info: DeviceInfo from driver.get_device_info() or None
        connection_info: ConnectionInfo from driver.get_connection_info() or None
        last_poll_timestamp: float (Unix epoch) or 0.0

    Returns:
        str: Prometheus text exposition format string, ending with newline
    """
    lines = []

    # --- Health status and channel counts ---
    if analysis is not None:
        summary = analysis.get("summary", {})
        health_val = SUMMARY_HEALTH_RANK.get(summary.get("health", "good"), 4)
    else:
        summary = {}
        health_val = 4

    _metric(
        lines,
        "DOCSIS signal health status: 0=good 1=tolerated 2=marginal 3=critical 4=unknown",
        "gauge",
        "docsight_health_status",
        health_val,
    )
    _metric(
        lines,
        "Number of active downstream channels",
        "gauge",
        "docsight_downstream_channels_total",
        summary.get("ds_total", 0),
    )
    _metric(
        lines,
        "Number of active upstream channels",
        "gauge",
        "docsight_upstream_channels_total",
        summary.get("us_total", 0),
    )

    # --- Per-channel metrics ---
    for key, name, metric_type, help_text, value_of in _CHANNEL_METRICS:
        channels = analysis.get(key, []) if analysis else []
        if channels:
            _metric_family_open(lines, help_text, metric_type, name)
            for ch in channels:
                value = value_of(ch)
                if value is not None:
                    _metric_value(lines, name, value, _channel_labels(ch))

    # --- Device info ---
    if device_info is not None:
        # docsight_device_info holds only immutable identifying labels.
        # Mutable fields (docsis_status, reboot_reason) are exposed as
        # separate metrics below so they refresh on every scrape.
        labels = {
            "model": device_info.get("model"),
            "hw_version": device_info.get("hw_version"),
            "sw_version": device_info.get("sw_version"),
        }
        labels = {k: v for k, v in labels.items() if v not in (None, "")}
        _metric(
            lines,
            "Device identification (model, hw/sw version)",
            "gauge",
            "docsight_device_info",
            1,
            labels,
        )

        docsis_status = device_info.get("docsis_status")
        if docsis_status not in (None, ""):
            _metric(
                lines,
                "1 when the modem reports DOCSIS online, 0 otherwise",
                "gauge",
                "docsight_docsis_online",
                1 if str(docsis_status).lower() == "online" else 0,
            )

        # dynamic numeric metric: uptime
        uptime = device_info.get("uptime_seconds")
        if uptime is not None:
            _metric(
                lines,
                "Device uptime in seconds",
                "gauge",
                "docsight_device_uptime_seconds",
                uptime,
            )

        for key, name, label, help_text in _DEVICE_INFO_LABEL_METRICS:
            value = device_info.get(key)
            if value not in (None, ""):
                _metric(
                    lines,
                    f"{help_text} (label carries the value, metric is always 1)",
                    "gauge",
                    name,
                    1,
                    {label: value},
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
