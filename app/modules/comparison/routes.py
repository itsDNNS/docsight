"""Before/After Comparison module routes."""

from flask import Blueprint, request, jsonify
from app.web import require_auth, get_storage

bp = Blueprint("comparison_module", __name__)


@bp.route("/api/comparison/compare")
@require_auth
def api_compare():
    """Compare signal quality between two time periods."""
    return jsonify({"error": "not implemented"}), 501
