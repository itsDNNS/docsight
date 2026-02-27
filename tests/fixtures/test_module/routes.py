from flask import Blueprint, jsonify

bp = Blueprint("test_integration_bp", __name__)

@bp.route("/api/modules/test.integration/ping")
def ping():
    return jsonify({"pong": True, "module": "test.integration"})
