"""API routes for Connection Monitor."""

import csv
import io
import logging
import math
import re
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, Response

from app.web import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("connection_monitor_module", __name__)


@bp.after_request
def _no_cache_api(response):
    """Prevent browser from caching API responses."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Lazy-initialized storage
_storage = None


def _get_cm_storage():
    """Get ConnectionMonitorStorage. Uses DATA_DIR like collector."""
    global _storage
    if _storage is None:
        import os
        from app.modules.connection_monitor.storage import ConnectionMonitorStorage
        data_dir = os.environ.get("DATA_DIR", "/data")
        db_path = os.path.join(data_dir, "connection_monitor.db")
        _storage = ConnectionMonitorStorage(db_path)
    return _storage


def _get_probe_engine():
    """Get ProbeEngine for capability info using configured method."""
    from app.modules.connection_monitor.probe import ProbeEngine
    from app.web import get_config_manager
    cfg = get_config_manager()
    method = cfg.get("connection_monitor_probe_method", "auto") if cfg else "auto"
    return ProbeEngine(method=method)


_traceroute_probe = None


def _get_traceroute_probe():
    global _traceroute_probe
    if _traceroute_probe is None:
        from app.modules.connection_monitor.traceroute_probe import TracerouteProbe
        _traceroute_probe = TracerouteProbe()
    return _traceroute_probe


def _epoch_to_iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hop_to_dict(hop):
    return {
        "hop_index": hop.hop_index,
        "hop_ip": hop.hop_ip,
        "hop_host": hop.hop_host,
        "latency_ms": hop.latency_ms,
        "probes_responded": hop.probes_responded,
    }


# --- Targets ---

@bp.route("/api/connection-monitor/targets", methods=["GET"])
@require_auth
def api_get_targets():
    storage = _get_cm_storage()
    return jsonify(storage.get_targets())


@bp.route("/api/connection-monitor/targets", methods=["POST"])
@require_auth
def api_create_target():
    storage = _get_cm_storage()
    data = request.get_json()
    if not data or not data.get("label"):
        return jsonify({"error": "label required"}), 400
    host = data.get("host", "").strip()
    tid = storage.create_target(
        label=data["label"],
        host=host,
        enabled=bool(host),
        poll_interval_ms=data.get("poll_interval_ms", 5000),
        probe_method=data.get("probe_method", "auto"),
        tcp_port=data.get("tcp_port", 443),
    )
    return jsonify({"id": tid}), 201


@bp.route("/api/connection-monitor/targets/<int:target_id>", methods=["PUT"])
@require_auth
def api_update_target(target_id):
    storage = _get_cm_storage()
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    # Auto-enable target when a non-empty host is provided
    host = data.get("host")
    if host is not None and host.strip() and "enabled" not in data:
        data["enabled"] = True
    storage.update_target(target_id, **data)
    return jsonify({"ok": True})


@bp.route("/api/connection-monitor/targets/<int:target_id>", methods=["DELETE"])
@require_auth
def api_delete_target(target_id):
    storage = _get_cm_storage()
    storage.delete_target(target_id)
    return jsonify({"ok": True})


# --- Pinned Days ---

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _get_tz():
    from app.web import _get_tz_name
    return _get_tz_name()


def _date_to_epoch_range(date_str, tz_name):
    """Convert YYYY-MM-DD to (start_epoch, end_epoch) in the configured timezone."""
    from app.tz import local_date_to_utc_range, _parse_utc
    start_utc, end_utc = local_date_to_utc_range(date_str, tz_name)
    return (_parse_utc(start_utc).timestamp(), _parse_utc(end_utc).timestamp())


@bp.route("/api/connection-monitor/pinned-days", methods=["GET"])
@require_auth
def api_get_pinned_days():
    storage = _get_cm_storage()
    tz = _get_tz()
    days = storage.get_pinned_days()
    for day in days:
        start, end = _date_to_epoch_range(day["date"], tz)
        day["utc_start"] = start
        day["utc_end"] = end
    return jsonify(days)


@bp.route("/api/connection-monitor/pinned-days", methods=["POST"])
@require_auth
def api_pin_day():
    storage = _get_cm_storage()
    data = request.get_json()
    if not data:
        return jsonify({"error": "date required"}), 400

    date_str = data.get("date")
    if not date_str:
        # Derive date from timestamp using server timezone
        ts = data.get("timestamp")
        if ts is None:
            return jsonify({"error": "date or timestamp required"}), 400
        try:
            ts = float(ts)
        except (ValueError, TypeError):
            return jsonify({"error": "invalid timestamp"}), 400
        tz = _get_tz()
        from datetime import timezone as _utc_tz
        from app.tz import to_local_display
        utc_str = datetime.fromtimestamp(ts, tz=_utc_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_str = to_local_display(utc_str, tz, fmt="%Y-%m-%d")

    if not _DATE_RE.match(date_str):
        return jsonify({"error": "invalid date format, expected YYYY-MM-DD"}), 400
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "invalid date"}), 400
    from app.tz import local_today
    today = local_today(_get_tz())
    if date_str > today:
        return jsonify({"error": "cannot pin a future date"}), 400
    storage.pin_day(date_str, label=data.get("label"))
    return jsonify({"ok": True}), 201


@bp.route("/api/connection-monitor/pinned-days/<date>", methods=["DELETE"])
@require_auth
def api_unpin_day(date):
    storage = _get_cm_storage()
    if not storage.unpin_day(date):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# --- Samples ---

# Resolution mapping: name -> bucket_seconds
_RESOLUTION_MAP = {
    "raw": None,
    "1min": 60,
    "5min": 300,
    "1hr": 3600,
}

_RAW_MAX_AGE = 7 * 86400
_AGG_60S_MAX_AGE = 30 * 86400
_AGG_300S_MAX_AGE = 90 * 86400


def _compress_samples(samples: list[dict], start: float | None, end: float | None, max_points: int | None) -> list[dict]:
    """Downsample chart samples to keep browser payloads bounded."""
    if not max_points or max_points <= 0 or len(samples) <= max_points:
        return samples

    range_start = start if start is not None else samples[0]["timestamp"]
    range_end = end if end is not None else samples[-1]["timestamp"]
    bucket_seconds = max(1, math.ceil(max(range_end - range_start, 1) / max_points))
    buckets: dict[int, dict] = {}

    for sample in samples:
        bucket_idx = int((sample["timestamp"] - range_start) // bucket_seconds)
        bucket = buckets.setdefault(bucket_idx, {
            "timestamp": range_start + bucket_idx * bucket_seconds,
            "sample_count": 0,
            "loss_weight": 0.0,
            "latency_sum": 0.0,
            "latency_count": 0,
            "min_latency_ms": None,
            "max_latency_ms": None,
            "p95_values": [],
        })

        sample_count = sample.get("sample_count") or 1
        loss_pct = sample.get("packet_loss_pct")
        if loss_pct is None:
            timeout_count = sample.get("timeout_count")
            if timeout_count is None:
                timeout_count = sample_count if sample.get("timeout") else 0
            loss_pct = (timeout_count / sample_count * 100.0) if sample_count > 0 else 0.0

        bucket["sample_count"] += sample_count
        bucket["loss_weight"] += loss_pct * sample_count

        latency = sample.get("latency_ms")
        if latency is not None:
            bucket["latency_sum"] += latency * sample_count
            bucket["latency_count"] += sample_count

        min_latency = sample.get("min_latency_ms")
        if min_latency is None:
            min_latency = latency
        if min_latency is not None:
            current = bucket["min_latency_ms"]
            bucket["min_latency_ms"] = min_latency if current is None else min(current, min_latency)

        max_latency = sample.get("max_latency_ms")
        if max_latency is None:
            max_latency = latency
        if max_latency is not None:
            current = bucket["max_latency_ms"]
            bucket["max_latency_ms"] = max_latency if current is None else max(current, max_latency)

        p95_latency = sample.get("p95_latency_ms")
        if p95_latency is None:
            p95_latency = latency
        if p95_latency is not None:
            bucket["p95_values"].append(p95_latency)

    compressed = []
    for bucket in [buckets[idx] for idx in sorted(buckets)]:
        latency_count = bucket["latency_count"]
        avg_latency = None
        if latency_count > 0:
            avg_latency = bucket["latency_sum"] / latency_count

        p95_latency = None
        if bucket["p95_values"]:
            bucket["p95_values"].sort()
            p95_latency = bucket["p95_values"][math.floor(len(bucket["p95_values"]) * 0.95)]

        compressed.append({
            "timestamp": bucket["timestamp"],
            "latency_ms": avg_latency,
            "min_latency_ms": bucket["min_latency_ms"],
            "max_latency_ms": bucket["max_latency_ms"],
            "p95_latency_ms": p95_latency,
            "packet_loss_pct": round(bucket["loss_weight"] / bucket["sample_count"], 2) if bucket["sample_count"] else 0.0,
            "sample_count": bucket["sample_count"],
        })

    return compressed


def _exclusive_upper_bound(value: float) -> float:
    """Turn an inclusive tier boundary into an exclusive upper limit."""
    return math.nextafter(value, float("-inf"))


def _append_raw_samples(samples: list[dict], raw_rows: list[dict]) -> int:
    count = 0
    for s in raw_rows:
        samples.append({
            "timestamp": s["timestamp"],
            "latency_ms": s["latency_ms"],
            "min_latency_ms": None,
            "max_latency_ms": None,
            "p95_latency_ms": None,
            "packet_loss_pct": 100.0 if s["timeout"] else 0.0,
            "sample_count": 1,
        })
        count += 1
    return count


def _append_aggregated_samples(samples: list[dict], agg_rows: list[dict]) -> int:
    count = 0
    for a in agg_rows:
        samples.append({
            "timestamp": a["bucket_start"],
            "latency_ms": a["avg_latency_ms"],
            "min_latency_ms": a["min_latency_ms"],
            "max_latency_ms": a["max_latency_ms"],
            "p95_latency_ms": a["p95_latency_ms"],
            "packet_loss_pct": a["packet_loss_pct"],
            "sample_count": a["sample_count"],
        })
        count += 1
    return count

@bp.route("/api/connection-monitor/samples/<int:target_id>")
@require_auth
def api_get_samples(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    limit = request.args.get("limit", 10000, type=int)
    resolution = request.args.get("resolution", "auto")
    max_points = request.args.get("max_points", type=int)
    has_explicit_range = start is not None and end is not None

    time_range = (end - start) if has_explicit_range else 0

    # Determine resolution
    if resolution == "auto":
        if not has_explicit_range or time_range <= 86400:
            res_name, bucket_seconds, blended = "raw", None, False
        elif time_range <= _RAW_MAX_AGE:
            res_name, bucket_seconds, blended = "raw", None, True
        elif time_range <= _AGG_60S_MAX_AGE:
            res_name, bucket_seconds, blended = "1min", 60, True
        elif time_range <= _AGG_300S_MAX_AGE:
            res_name, bucket_seconds, blended = "5min", 300, True
        else:
            res_name, bucket_seconds, blended = "1hr", 3600, True
    else:
        bucket_seconds = _RESOLUTION_MAP.get(resolution)
        res_name = resolution
        blended = False

    # Fetch data
    samples = []
    tiers_used: list[str] = []

    if resolution != "auto" or not has_explicit_range:
        if bucket_seconds is None:
            raw = storage.get_samples(target_id, start=start, end=end, limit=limit)
            if _append_raw_samples(samples, raw):
                tiers_used.append("raw")
        else:
            agg = storage.get_aggregated_samples(
                target_id, bucket_seconds=bucket_seconds, start=start, end=end,
            )
            if _append_aggregated_samples(samples, agg):
                tiers_used.append(res_name)
    else:
        now_ts = time.time()
        range_start = start if start is not None else float("-inf")
        range_end = end if end is not None else now_ts

        if range_start <= range_end:
            raw_start = max(range_start, now_ts - _RAW_MAX_AGE)
            if raw_start <= range_end:
                raw = storage.get_samples(target_id, start=raw_start, end=end, limit=limit)
                if _append_raw_samples(samples, raw):
                    tiers_used.append("raw")

            agg_60_start = max(range_start, now_ts - _AGG_60S_MAX_AGE)
            agg_60_end = _exclusive_upper_bound(min(range_end, now_ts - _RAW_MAX_AGE))
            if agg_60_start <= agg_60_end:
                agg_60 = storage.get_aggregated_samples(
                    target_id, bucket_seconds=60, start=agg_60_start, end=agg_60_end,
                )
                if _append_aggregated_samples(samples, agg_60):
                    tiers_used.append("1min")

            agg_300_start = max(range_start, now_ts - _AGG_300S_MAX_AGE)
            agg_300_end = _exclusive_upper_bound(min(range_end, now_ts - _AGG_60S_MAX_AGE))
            if agg_300_start <= agg_300_end:
                agg_300 = storage.get_aggregated_samples(
                    target_id, bucket_seconds=300, start=agg_300_start, end=agg_300_end,
                )
                if _append_aggregated_samples(samples, agg_300):
                    tiers_used.append("5min")

            agg_3600_end = _exclusive_upper_bound(min(range_end, now_ts - _AGG_300S_MAX_AGE))
            if time_range > _AGG_300S_MAX_AGE and range_start <= agg_3600_end:
                agg_3600 = storage.get_aggregated_samples(
                    target_id, bucket_seconds=3600, start=range_start, end=agg_3600_end,
                )
                if _append_aggregated_samples(samples, agg_3600):
                    tiers_used.append("1hr")

    samples.sort(key=lambda s: s["timestamp"])
    samples = _compress_samples(samples, start=start, end=end, max_points=max_points)

    return jsonify({
        "meta": {
            "resolution": res_name,
            "bucket_seconds": bucket_seconds,
            "blended": blended,
            "mixed": len(tiers_used) > 1,
            "tiers_used": tiers_used,
        },
        "samples": samples,
    })


# --- Range Stats ---

@bp.route("/api/connection-monitor/stats")
@require_auth
def api_get_range_stats():
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    targets = storage.get_targets()
    stats = {}
    for t in targets:
        stats[t["id"]] = storage.get_range_stats(
            t["id"],
            start=start,
            end=end,
        )
    return jsonify(stats)


# --- Summary ---

@bp.route("/api/connection-monitor/summary")
@require_auth
def api_get_summary():
    storage = _get_cm_storage()
    targets = storage.get_targets()
    summaries = {}
    for t in targets:
        summaries[t["id"]] = {
            "label": t["label"],
            "host": t["host"],
            "enabled": t["enabled"],
            **storage.get_summary(t["id"], window_seconds=60),
        }
    return jsonify(summaries)


# --- Outages ---

@bp.route("/api/connection-monitor/outages/<int:target_id>")
@require_auth
def api_get_outages(target_id):
    from app.web import get_config_manager
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    cfg = get_config_manager()
    default_threshold = int(cfg.get("connection_monitor_outage_threshold", 5)) if cfg else 5
    threshold = request.args.get("threshold", default_threshold, type=int)
    outages = storage.get_outages(target_id, threshold=threshold, start=start, end=end)
    return jsonify(outages)


# --- Export ---

@bp.route("/api/connection-monitor/export/<int:target_id>")
@require_auth
def api_export_csv(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    resolution = request.args.get("resolution", "raw")

    target = storage.get_target(target_id)
    label = target["label"].replace(" ", "_") if target else str(target_id)

    output = io.StringIO()
    writer = csv.writer(output)

    bucket_seconds = _RESOLUTION_MAP.get(resolution)

    if bucket_seconds is not None:
        # Aggregated export
        writer.writerow(["datetime", "avg_latency_ms", "min_latency_ms",
                         "max_latency_ms", "p95_latency_ms", "packet_loss_pct", "sample_count"])
        agg = storage.get_aggregated_samples(
            target_id, bucket_seconds=bucket_seconds, start=start, end=end,
        )
        for a in agg:
            dt = datetime.fromtimestamp(a["bucket_start"]).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([dt, a["avg_latency_ms"], a["min_latency_ms"],
                             a["max_latency_ms"], a["p95_latency_ms"],
                             a["packet_loss_pct"], a["sample_count"]])
    else:
        # Raw export (backward compatible)
        writer.writerow(["datetime", "latency_ms", "timeout", "probe_method"])
        samples = storage.get_samples(target_id, start=start, end=end, limit=0)
        for s in samples:
            dt = datetime.fromtimestamp(s["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([dt, s["latency_ms"], s["timeout"], s["probe_method"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=connection_monitor_{label}.csv"},
    )


# --- Capability ---

@bp.route("/api/connection-monitor/capability")
@require_auth
def api_capability():
    probe = _get_probe_engine()
    return jsonify(probe.capability_info())


# --- Traceroute ---

@bp.route("/api/connection-monitor/traceroute/<int:target_id>", methods=["POST"])
@require_auth
def api_run_traceroute(target_id):
    storage = _get_cm_storage()
    target = storage.get_target(target_id)
    if not target:
        return jsonify({"error": "Target not found"}), 404

    probe = _get_traceroute_probe()
    result = probe.run(target["host"])

    trace_id = storage.save_trace(
        target_id=target_id,
        timestamp=time.time(),
        trigger_reason="manual",
        hops=[{
            "hop_index": h.hop_index, "hop_ip": h.hop_ip,
            "hop_host": h.hop_host, "latency_ms": h.latency_ms,
            "probes_responded": h.probes_responded,
        } for h in result.hops],
        route_fingerprint=result.route_fingerprint,
        reached_target=result.reached_target,
    )

    return jsonify({
        "trace_id": trace_id,
        "timestamp": _epoch_to_iso(time.time()),
        "trigger_reason": "manual",
        "reached_target": result.reached_target,
        "hop_count": len(result.hops),
        "route_fingerprint": result.route_fingerprint,
        "hops": [_hop_to_dict(h) for h in result.hops],
    })


@bp.route("/api/connection-monitor/traces/<int:target_id>")
@require_auth
def api_get_traces(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    limit = request.args.get("limit", 100, type=int)
    limit = max(1, min(limit, 1000))
    traces = storage.get_traces(target_id, start=start, end=end, limit=limit)
    for t in traces:
        t["timestamp"] = _epoch_to_iso(t["timestamp"])
    return jsonify(traces)


@bp.route("/api/connection-monitor/trace/<int:trace_id>")
@require_auth
def api_get_trace_detail(trace_id):
    storage = _get_cm_storage()
    trace = storage.get_trace(trace_id)
    if not trace:
        return jsonify({"error": "Trace not found"}), 404
    hops = storage.get_trace_hops(trace_id)
    trace["timestamp"] = _epoch_to_iso(trace["timestamp"])
    trace["hops"] = hops
    return jsonify(trace)
