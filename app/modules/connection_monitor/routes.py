"""API routes for Connection Monitor."""

import csv
import io
import logging
import math
import time
from datetime import datetime

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


def _append_raw_samples(samples: list[dict], raw_rows: list[dict]):
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


def _append_aggregated_samples(samples: list[dict], agg_rows: list[dict]):
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

@bp.route("/api/connection-monitor/samples/<int:target_id>")
@require_auth
def api_get_samples(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    limit = request.args.get("limit", 10000, type=int)
    resolution = request.args.get("resolution", "auto")
    max_points = request.args.get("max_points", type=int)

    time_range = (end - start) if start is not None and end is not None else 0

    # Determine resolution
    if resolution == "auto":
        if time_range <= 86400:
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

    if resolution != "auto":
        if bucket_seconds is None:
            raw = storage.get_samples(target_id, start=start, end=end, limit=limit)
            _append_raw_samples(samples, raw)
        else:
            agg = storage.get_aggregated_samples(
                target_id, bucket_seconds=bucket_seconds, start=start, end=end,
            )
            _append_aggregated_samples(samples, agg)
    else:
        now_ts = time.time()
        range_start = start if start is not None else float("-inf")
        range_end = end if end is not None else now_ts

        if range_start <= range_end:
            raw_start = max(range_start, now_ts - _RAW_MAX_AGE)
            if raw_start <= range_end:
                raw = storage.get_samples(target_id, start=raw_start, end=end, limit=limit)
                _append_raw_samples(samples, raw)

            agg_60_start = max(range_start, now_ts - _AGG_60S_MAX_AGE)
            agg_60_end = min(range_end, now_ts - _RAW_MAX_AGE)
            if agg_60_start <= agg_60_end:
                agg_60 = storage.get_aggregated_samples(
                    target_id, bucket_seconds=60, start=agg_60_start, end=agg_60_end,
                )
                _append_aggregated_samples(samples, agg_60)

            agg_300_start = max(range_start, now_ts - _AGG_300S_MAX_AGE)
            agg_300_end = min(range_end, now_ts - _AGG_60S_MAX_AGE)
            if agg_300_start <= agg_300_end:
                agg_300 = storage.get_aggregated_samples(
                    target_id, bucket_seconds=300, start=agg_300_start, end=agg_300_end,
                )
                _append_aggregated_samples(samples, agg_300)

            agg_3600_end = min(range_end, now_ts - _AGG_300S_MAX_AGE)
            if time_range > _AGG_300S_MAX_AGE and range_start <= agg_3600_end:
                agg_3600 = storage.get_aggregated_samples(
                    target_id, bucket_seconds=3600, start=range_start, end=agg_3600_end,
                )
                _append_aggregated_samples(samples, agg_3600)

    samples.sort(key=lambda s: s["timestamp"])
    samples = _compress_samples(samples, start=start, end=end, max_points=max_points)

    return jsonify({
        "meta": {
            "resolution": res_name,
            "bucket_seconds": bucket_seconds,
            "blended": blended,
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
