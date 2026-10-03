"""View model for the Home line status block.

Turns the analyzed channel lists into one segment per channel and, for each
direction, a callout for the worst deviating channel. Target bands come from the
same threshold resolvers the analyzer uses to rate the channel, so the callout
always explains the rating that is shown.
"""

from __future__ import annotations

from typing import Any

from .analyzer import _get_ds_power_thresholds, _get_snr_thresholds, _get_us_power_thresholds
from .docsis_utils import classify_channel_family

SEVERITY = {"good": 0, "tolerated": 1, "warning": 2, "critical": 3}
FAMILY_LABELS = {"sc_qam": "SC-QAM", "ofdm": "OFDM", "ofdma": "OFDMA"}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _channel_id(channel: dict) -> int:
    try:
        return int(channel.get("channel_id"))
    except (TypeError, ValueError):
        return 0


def _family(direction: str, channel: dict) -> str:
    family = channel.get("channel_family")
    if family in FAMILY_LABELS:
        return family
    return classify_channel_family(direction, channel)


def _health(channel: dict) -> str:
    health = channel.get("health")
    return health if health in SEVERITY else "good"


def _pct(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return round(max(0.0, min(100.0, (value - low) / (high - low) * 100)), 2)


def _power_callout(direction: str, channel: dict) -> dict | None:
    value = _number(channel.get("power"))
    if value is None:
        return None
    family = _family(direction, channel)
    if direction == "ds":
        limits = _get_ds_power_thresholds(channel.get("modulation"), channel_family=family)
    else:
        limits = _get_us_power_thresholds("OFDMA" if family == "ofdma" else channel.get("modulation"))
    good_min, good_max = float(limits["good_min"]), float(limits["good_max"])
    warn_min, warn_max = float(limits["warn_min"]), float(limits["warn_max"])
    low = min(float(limits["crit_min"]), value) - 2.0
    high = max(float(limits["crit_max"]), value) + 2.0
    if value < good_min:
        delta = value - good_min
    elif value > good_max:
        delta = value - good_max
    else:
        delta = 0.0
    return {
        "metric": "power",
        "unit": "dBmV",
        "value": value,
        "delta": round(delta, 1),
        "target_min": good_min,
        "target_max": good_max,
        "ruler": {
            "good": {"left": _pct(good_min, low, high), "width": round(_pct(good_max, low, high) - _pct(good_min, low, high), 2)},
            "tolerated": {"left": _pct(warn_min, low, high), "width": round(_pct(warn_max, low, high) - _pct(warn_min, low, high), 2)},
            "marker": _pct(value, low, high),
        },
    }


def _snr_callout(channel: dict) -> dict | None:
    value = _number(channel.get("snr"))
    if value is None:
        return None
    limits = _get_snr_thresholds(channel.get("modulation"), channel_family=_family("ds", channel))
    good_min, warn_min = float(limits["good_min"]), float(limits["warn_min"])
    low = min(float(limits["crit_min"]), value) - 4.0
    high = max(good_min + 10.0, value + 2.0)
    return {
        "metric": "mer" if _family("ds", channel) == "ofdm" else "snr",
        "unit": "dB",
        "value": value,
        "delta": round(min(0.0, value - good_min), 1),
        "target_min": good_min,
        "target_max": None,
        "ruler": {
            "good": {"left": _pct(good_min, low, high), "width": round(100.0 - _pct(good_min, low, high), 2)},
            "tolerated": {"left": _pct(warn_min, low, high), "width": round(100.0 - _pct(warn_min, low, high), 2)},
            "marker": _pct(value, low, high),
        },
    }


def _callout(direction: str, channel: dict) -> dict:
    detail = channel.get("health_detail") or ""
    measurement = None
    if "power" in detail:
        measurement = _power_callout(direction, channel)
    elif "snr" in detail and direction == "ds":
        measurement = _snr_callout(channel)
    family = _family(direction, channel)
    return {
        "channel_id": _channel_id(channel),
        "direction": direction,
        "family": FAMILY_LABELS.get(family, ""),
        "health": _health(channel),
        "modulation": channel.get("profile_modulation") or channel.get("modulation") or "",
        "measurement": measurement,
        "link": f"#channels?mode=timeline&dir={direction}&channel={_channel_id(channel)}",
    }


def _direction(direction: str, channels: list[dict]) -> dict | None:
    if not channels:
        return None
    ordered = sorted(channels, key=lambda ch: (_family(direction, ch) == "sc_qam", _channel_id(ch)))
    segments = [
        {
            "channel_id": _channel_id(ch),
            "family": FAMILY_LABELS.get(_family(direction, ch), ""),
            "health": _health(ch),
            "power": _number(ch.get("power")),
        }
        for ch in ordered
    ]
    counts = {state: sum(1 for seg in segments if seg["health"] == state) for state in SEVERITY}
    families: dict[str, int] = {}
    for seg in segments:
        families[seg["family"]] = families.get(seg["family"], 0) + 1
    deviating = sorted(
        (ch for ch in ordered if _health(ch) != "good"),
        key=lambda ch: (-SEVERITY[_health(ch)], _channel_id(ch)),
    )
    callouts = [_callout(direction, ch) for ch in deviating]
    return {
        "key": direction,
        "total": len(segments),
        "segments": segments,
        "counts": counts,
        "families": families,
        "callout": callouts[0] if callouts else None,
        "more": [{"channel_id": c["channel_id"], "health": c["health"]} for c in callouts[1:]],
    }


def build_line_status(analysis: dict | None) -> dict | None:
    """Return the line status view model, or None when no DOCSIS channels are known."""
    if not isinstance(analysis, dict):
        return None
    directions = [
        block
        for block in (
            _direction("ds", analysis.get("ds_channels") or []),
            _direction("us", analysis.get("us_channels") or []),
        )
        if block
    ]
    if not directions:
        return None
    callouts = [block["callout"] for block in directions if block["callout"]]
    primary = max(callouts, key=lambda c: SEVERITY[c["health"]], default=None)
    total = sum(block["total"] for block in directions)
    within = sum(block["counts"]["good"] for block in directions)
    summary = analysis.get("summary") or {}
    return {
        "health": summary.get("health") or "good",
        "total": total,
        "within": within,
        "deviating": total - within,
        "directions": directions,
        "primary": primary,
    }
