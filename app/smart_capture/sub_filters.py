"""Per-trigger sub-filter functions for Smart Capture.

Each function takes (config, event) and returns True if the event
qualifies for triggering. Uses qualifying-subset logic: if ANY
change in the event matches the criteria, the filter passes.
"""

from ..docsis_utils import qam_rank


def modulation_sub_filter(config, event):
    """Filter modulation_change by direction and min QAM level."""
    details = event.get("details") or {}
    changes = details.get("changes", [])
    if not changes:
        return True

    direction = config.get("sc_trigger_modulation_direction", "both")
    min_qam = config.get("sc_trigger_modulation_min_qam", "")
    min_rank = qam_rank(min_qam) if min_qam else 0

    qualifying = []
    for c in changes:
        # Direction filter
        if direction != "both" and c.get("direction", "").upper() != direction.upper():
            continue
        # QAM threshold filter: trigger only if current rank is below min_rank
        if min_rank > 0 and c.get("current_rank", 0) >= min_rank:
            continue
        qualifying.append(c)

    return bool(qualifying)


def snr_sub_filter(config, event):
    """No sub-settings for v1 — always passes."""
    return True


def error_spike_sub_filter(config, event):
    """Filter error_spike by minimum delta."""
    min_delta = int(config.get("sc_trigger_error_spike_min_delta", 0))
    if min_delta <= 0:
        return True
    details = event.get("details") or {}
    return details.get("delta", 0) >= min_delta


def health_sub_filter(config, event):
    """Filter health_change by level (any_degradation or critical_only)."""
    level = config.get("sc_trigger_health_level", "any_degradation")
    if level == "any_degradation":
        return True
    details = event.get("details") or {}
    return details.get("current") == "critical"


def packet_loss_sub_filter(config, event):
    """Filter cm_packet_loss_warning by minimum packet loss percentage."""
    try:
        min_pct = float(config.get("sc_trigger_packet_loss_min_pct", 5.0))
    except (ValueError, TypeError):
        min_pct = 5.0
    details = event.get("details") or {}
    return details.get("packet_loss_pct", 0) >= min_pct
