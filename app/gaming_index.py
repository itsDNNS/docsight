"""Gaming Quality Index - rates connection quality for online gaming.

A heuristic summary of one complete Speedtest result. It does not measure
performance to game servers or predict compatibility with individual games.
"""

from __future__ import annotations

from math import isfinite

from .types import GamingIndex


def _score_latency(ping_ms):
    """Score latency: lower is better for gaming."""
    if ping_ms < 20:
        return 100
    if ping_ms <= 50:
        return 80
    if ping_ms <= 80:
        return 60
    if ping_ms <= 120:
        return 30
    return 0


def _score_jitter(jitter_ms):
    """Score jitter: lower is better for gaming."""
    if jitter_ms < 5:
        return 100
    if jitter_ms <= 15:
        return 80
    if jitter_ms <= 30:
        return 60
    if jitter_ms <= 50:
        return 30
    return 0


def _score_packet_loss(loss_pct):
    """Score packet loss: lower is better for gaming."""
    if loss_pct == 0:
        return 100
    if loss_pct < 0.5:
        return 80
    if loss_pct < 1:
        return 60
    if loss_pct < 2:
        return 30
    return 0


def _grade(score):
    """Convert numeric score to letter grade."""
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 50:
        return "C"
    if score >= 25:
        return "D"
    return "F"


def compute_gaming_index(speedtest: dict | None) -> GamingIndex | None:
    """Score complete measured latency data; missing values never imply zero."""
    if not speedtest:
        return None

    components = {}
    for name, field, unit, scorer in (
        ("latency", "ping_ms", "ms", _score_latency),
        ("jitter", "jitter_ms", "ms", _score_jitter),
        ("packet_loss", "packet_loss_pct", "%", _score_packet_loss),
    ):
        value = speedtest.get(field)
        if value is None or isinstance(value, bool):
            return None
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not isfinite(value) or value < 0 or (name == "packet_loss" and value > 100):
            return None
        components[name] = {"score": scorer(value), "value": value, "unit": unit}

    # Good latency cannot compensate for packet loss or unstable response times.
    score = min(component["score"] for component in components.values())
    return {
        "score": score,
        "grade": _grade(score),
        "components": components,
        "has_speedtest": True,
    }
