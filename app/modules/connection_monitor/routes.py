"""API routes for Connection Monitor."""

import csv
import io
import logging
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

@bp.route("/api/connection-monitor/samples/<int:target_id>")
@require_auth
def api_get_samples(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    limit = request.args.get("limit", 10000, type=int)
    samples = storage.get_samples(target_id, start=start, end=end, limit=limit)
    return jsonify(samples)


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
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    threshold = request.args.get("threshold", 5, type=int)
    outages = storage.get_outages(target_id, threshold=threshold, start=start, end=end)
    return jsonify(outages)


# --- Export ---

@bp.route("/api/connection-monitor/export/<int:target_id>")
@require_auth
def api_export_csv(target_id):
    storage = _get_cm_storage()
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)
    samples = storage.get_samples(target_id, start=start, end=end, limit=0)

    target = storage.get_target(target_id)
    label = target["label"].replace(" ", "_") if target else str(target_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["datetime", "latency_ms", "timeout", "probe_method"])
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
