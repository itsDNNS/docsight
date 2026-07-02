"""Flask blueprint for the Prometheus /metrics endpoint."""

from flask import Blueprint, Response, request

from app.web import get_state, get_modem_collector
from app.prometheus import format_metrics

metrics_bp = Blueprint("metrics_bp", __name__)


def _metrics_token_required() -> bool:
    """Return whether /metrics should require a Bearer API token."""
    from app import web as _web

    config = getattr(_web, "_config_manager", None)
    return bool(config and config.get("metrics_require_token", False))


def _has_valid_bearer_token() -> bool:
    """Validate the request's Bearer token through DOCSight token storage."""
    from app import web as _web

    storage = getattr(_web, "_storage", None)
    auth_header = request.headers.get("Authorization", "")
    if not storage or not auth_header.startswith("Bearer "):
        return False
    token_info = storage.validate_api_token(auth_header[7:])
    if token_info:
        request._api_token = token_info
        return True
    return False


@metrics_bp.route("/metrics")
def metrics():
    """Expose DOCSight metrics in Prometheus text exposition format.

    The endpoint remains open by default for Prometheus compatibility. Operators
    can enable token protection for deployments where metrics are exposed beyond
    a trusted scrape network.
    """
    if _metrics_token_required() and not _has_valid_bearer_token():
        return Response("Authentication required\n", status=401, content_type="text/plain; charset=utf-8")

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
