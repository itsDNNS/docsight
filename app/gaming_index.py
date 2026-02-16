"""Gaming Quality Index - rates connection quality for online gaming.

Combines DOCSIS signal health with Speedtest Tracker latency data
to produce a 0-100 score and A-F grade.
"""

from .analyzer import _get_snr_thresholds


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


def _score_docsis_health(health):
    """Score DOCSIS health status."""
    if health == "good":
        return 100
    if health == "marginal":
        return 50
    return 0


def _score_snr_headroom(min_snr, modulation=None):
    """Score SNR headroom above threshold."""
    threshold = _get_snr_thresholds(modulation)["good_min"]
    headroom = min_snr - threshold
    if headroom > 6:
        return 100
    if headroom >= 3:
        return 70
    if headroom >= 1:
        return 40
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


def compute_gaming_index(analysis, speedtest):
    """Compute gaming quality index from DOCSIS analysis and speedtest data.

    Args:
        analysis: dict from analyzer.analyze() or None
        speedtest: dict with ping_ms, jitter_ms, packet_loss_pct or None

    Returns:
        dict with score, grade, components, has_speedtest or None if no data
    """
    if not analysis:
        return None

    summary = analysis.get("summary", {})
    health = summary.get("health", "poor")
    min_snr = summary.get("ds_snr_min", 0)

    components = {}
    total_score = 0
    total_weight = 0

    # DOCSIS components (always available)
    docsis_score = _score_docsis_health(health)
    components["docsis_health"] = {"score": docsis_score, "weight": 25}
    total_score += docsis_score * 25
    total_weight += 25

    snr_score = _score_snr_headroom(min_snr)
    components["snr_headroom"] = {"score": snr_score, "weight": 15}
    total_score += snr_score * 15
    total_weight += 15

    has_speedtest = speedtest is not None and "ping_ms" in (speedtest or {})

    if has_speedtest:
        ping = float(speedtest.get("ping_ms", 0))
        jitter = float(speedtest.get("jitter_ms", 0))
        loss = float(speedtest.get("packet_loss_pct", 0))

        lat_score = _score_latency(ping)
        components["latency"] = {"score": lat_score, "weight": 25}
        total_score += lat_score * 25
        total_weight += 25

        jit_score = _score_jitter(jitter)
        components["jitter"] = {"score": jit_score, "weight": 20}
        total_score += jit_score * 20
        total_weight += 20

        loss_score = _score_packet_loss(loss)
        components["packet_loss"] = {"score": loss_score, "weight": 15}
        total_score += loss_score * 15
        total_weight += 15

    score = round(total_score / total_weight) if total_weight > 0 else 0

    return {
        "score": score,
        "grade": _grade(score),
        "components": components,
        "has_speedtest": has_speedtest,
    }
