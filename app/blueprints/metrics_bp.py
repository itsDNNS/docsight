"""Flask blueprint for the Prometheus /metrics endpoint."""

from flask import Blueprint, Response

from app.web import get_state, get_modem_collector
from app.prometheus import format_metrics

metrics_bp = Blueprint("metrics_bp", __name__)


@metrics_bp.route("/metrics")
def metrics():
    """Expose DOCSight metrics in Prometheus text exposition format.

    This endpoint is always accessible without authentication — same pattern as /health.
    It reads only from existing in-memory state and never triggers modem queries.
    """
    state = get_state()
    analysis = state.get("analysis")
    device_info = state.get("device_info")
    connection_info = state.get("connection_info")

    collector = get_modem_collector()
    if collector is not None:
        last_poll_timestamp = collector.get_status().get("last_poll", 0.0)
    else:
        last_poll_timestamp = 0.0

    output = format_metrics(analysis, device_info, connection_info, last_poll_timestamp)
    return Response(output, status=200, content_type="text/plain; version=0.0.4; charset=utf-8")
