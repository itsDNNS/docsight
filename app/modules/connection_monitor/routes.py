"""API routes for Connection Monitor."""

import csv
import io
import logging
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

@bp.route("/api/connection-monitor/samples/<int:target_id>")
@require_auth
def api_get_samples(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    limit = request.args.get("limit", 10000, type=int)
    resolution = request.args.get("resolution", "auto")

    # Determine resolution
    if resolution == "auto":
        time_range = (end - start) if start is not None and end is not None else 0
        if time_range <= 86400:
            res_name, bucket_seconds, blended = "raw", None, False
        elif time_range <= 7 * 86400:
            res_name, bucket_seconds, blended = "raw", None, True
        elif time_range <= 30 * 86400:
            res_name, bucket_seconds, blended = "1min", 60, True
        elif time_range <= 90 * 86400:
            res_name, bucket_seconds, blended = "5min", 300, False
        else:
            res_name, bucket_seconds, blended = "1hr", 3600, False
    else:
        bucket_seconds = _RESOLUTION_MAP.get(resolution)
        res_name = resolution
        blended = False

    # Fetch data
    samples = []

    if bucket_seconds is None or blended:
        raw_start = start
        if blended and bucket_seconds is not None:
            raw_start = max(start, time.time() - 7 * 86400) if start else time.time() - 7 * 86400
        raw = storage.get_samples(target_id, start=raw_start, end=end, limit=limit)
        for s in raw:
            samples.append({
                "timestamp": s["timestamp"],
                "latency_ms": s["latency_ms"],
                "min_latency_ms": None,
                "max_latency_ms": None,
                "p95_latency_ms": None,
                "packet_loss_pct": 100.0 if s["timeout"] else 0.0,
                "sample_count": 1,
            })

    if bucket_seconds is not None:
        agg_end = end
        if blended:
            agg_end = time.time() - 7 * 86400
        agg = storage.get_aggregated_samples(
            target_id, bucket_seconds=bucket_seconds, start=start, end=agg_end,
        )
        for a in agg:
            samples.append({
                "timestamp": a["bucket_start"],
                "latency_ms": a["avg_latency_ms"],
                "min_latency_ms": a["min_latency_ms"],
                "max_latency_ms": a["max_latency_ms"],
                "p95_latency_ms": a["p95_latency_ms"],
                "packet_loss_pct": a["packet_loss_pct"],
                "sample_count": a["sample_count"],
            })

    samples.sort(key=lambda s: s["timestamp"])

    return jsonify({
        "meta": {
            "resolution": res_name,
            "bucket_seconds": bucket_seconds,
            "blended": blended,
        },
        "samples": samples,
    })


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
