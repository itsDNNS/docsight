"""Before/After Comparison module routes."""

from flask import Blueprint, request, jsonify
from app.web import require_auth, get_storage

bp = Blueprint("comparison_module", __name__)


def _get_storage():
    return get_storage()


def _aggregate_period(snapshots):
    """Aggregate a list of snapshots into period summary."""
    if not snapshots:
        return {
            "snapshots": 0,
            "avg": {"ds_power": None, "ds_snr": None, "us_power": None},
            "total": {"corr_errors": 0, "uncorr_errors": 0},
            "health_distribution": {},
            "timeseries": [],
        }

    ds_power = []
    ds_snr = []
    us_power = []
    corr_total = 0
    uncorr_total = 0
    health_counts = {}
    timeseries = []

    for snap in snapshots:
        s = snap.get("summary", {})
        if s.get("ds_power_avg") is not None:
            ds_power.append(s["ds_power_avg"])
        if s.get("ds_snr_avg") is not None:
            ds_snr.append(s["ds_snr_avg"])
        if s.get("us_power_avg") is not None:
            us_power.append(s["us_power_avg"])
        corr_total += s.get("ds_correctable_errors", 0) or 0
        uncorr_total += s.get("ds_uncorrectable_errors", 0) or 0
        h = s.get("health", "unknown")
        health_counts[h] = health_counts.get(h, 0) + 1
        timeseries.append({
            "timestamp": snap.get("timestamp", ""),
            "ds_power_avg": s.get("ds_power_avg"),
            "ds_snr_avg": s.get("ds_snr_avg"),
            "us_power_avg": s.get("us_power_avg"),
            "uncorr_errors": s.get("ds_uncorrectable_errors", 0),
            "health": h,
        })

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else None

    return {
        "snapshots": len(snapshots),
        "avg": {
            "ds_power": avg(ds_power),
            "ds_snr": avg(ds_snr),
            "us_power": avg(us_power),
        },
        "total": {"corr_errors": corr_total, "uncorr_errors": uncorr_total},
        "health_distribution": health_counts,
        "timeseries": timeseries,
    }


def _compute_delta(period_a, period_b):
    """Compute delta between two aggregated periods."""
    a_avg = period_a["avg"]
    b_avg = period_b["avg"]

    def diff(key):
        a_val = a_avg.get(key)
        b_val = b_avg.get(key)
        if a_val is None or b_val is None:
            return None
        return round(b_val - a_val, 2)

    ds_power_d = diff("ds_power")
    ds_snr_d = diff("ds_snr")
    us_power_d = diff("us_power")
    uncorr_d = period_b["total"]["uncorr_errors"] - period_a["total"]["uncorr_errors"]

    # Verdict: improved if SNR went up and errors went down (or stayed)
    # degraded if SNR went down or errors went up significantly
    score = 0
    if ds_snr_d is not None:
        if ds_snr_d > 1:
            score += 1
        elif ds_snr_d < -1:
            score -= 1
    if uncorr_d > 10:
        score -= 1
    elif uncorr_d < 0:
        score += 1

    if score > 0:
        verdict = "improved"
    elif score < 0:
        verdict = "degraded"
    else:
        verdict = "unchanged"

    return {
        "ds_power": ds_power_d,
        "ds_snr": ds_snr_d,
        "us_power": us_power_d,
        "uncorr_errors": uncorr_d,
        "verdict": verdict,
    }


def compare_periods(storage, from_a, to_a, from_b, to_b):
    """Load and compare two periods from snapshot storage."""
    snapshots_a = storage.get_range_data(from_a, to_a)
    snapshots_b = storage.get_range_data(from_b, to_b)

    period_a = _aggregate_period(snapshots_a)
    period_b = _aggregate_period(snapshots_b)
    period_a["from"] = from_a
    period_a["to"] = to_a
    period_b["from"] = from_b
    period_b["to"] = to_b

    return {
        "period_a": period_a,
        "period_b": period_b,
        "delta": _compute_delta(period_a, period_b),
    }


@bp.route("/api/comparison")
@require_auth
def api_compare():
    """Compare signal quality between two time periods."""
    from_a = request.args.get("from_a")
    to_a = request.args.get("to_a")
    from_b = request.args.get("from_b")
    to_b = request.args.get("to_b")

    if not all([from_a, to_a, from_b, to_b]):
        return jsonify({"error": "from_a, to_a, from_b, to_b required"}), 400

    storage = _get_storage()
    if not storage:
        return jsonify({"error": "storage not available"}), 503

    return jsonify(compare_periods(storage, from_a, to_a, from_b, to_b))
