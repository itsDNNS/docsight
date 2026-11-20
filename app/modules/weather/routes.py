"""Weather module routes."""

import logging

from flask import Blueprint, request, jsonify

from app.web_auth import require_auth
from app.runtime import core_derived_storage, current_runtime
from .storage import WeatherStorage

log = logging.getLogger("docsis.web.weather")

bp = Blueprint("weather_module", __name__)

def _get_weather_storage():
    return core_derived_storage(WeatherStorage)


@bp.route("/api/weather")
@require_auth
def api_weather():
    """Return weather (temperature) history, newest first."""
    if not current_runtime().config_manager.is_weather_configured():
        return jsonify([])
    ws = _get_weather_storage()
    if not ws:
        return jsonify([])
    count = request.args.get("count", 2000, type=int)
    return jsonify(ws.get_weather_data(limit=count))


@bp.route("/api/weather/current")
@require_auth
def api_weather_current():
    """Return latest weather reading from state."""
    state = current_runtime().get_state()
    weather = state.get("weather_latest")
    if not weather:
        return jsonify({"error": "No weather data yet"}), 404
    return jsonify(weather)


@bp.route("/api/weather/range")
@require_auth
def api_weather_range():
    """Return weather data within a timestamp range (for correlation)."""
    if not current_runtime().config_manager.is_weather_configured():
        return jsonify([])
    ws = _get_weather_storage()
    if not ws:
        return jsonify([])
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    if not start or not end:
        return jsonify({"error": "start and end parameters required"}), 400
    return jsonify(ws.get_weather_in_range(start, end))
