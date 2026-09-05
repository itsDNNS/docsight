"""Smart Capture API endpoints."""

from flask import Blueprint, jsonify, request

from ..web import get_storage
from ..web_auth import require_auth

smart_capture_bp = Blueprint("smart_capture", __name__)


@smart_capture_bp.route("/api/smart-capture/executions")
@require_auth
def api_smart_capture_executions():
    """Return Smart Capture execution history."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"executions": []})
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    status = request.args.get("status", None)
    executions = _storage.get_executions(limit=limit, offset=offset, status=status)
    return jsonify({"executions": executions})
