"""Weather module routes."""

import logging

from flask import Blueprint, request, jsonify

from app.web import require_auth, get_config_manager, get_state, get_storage
from .storage import WeatherStorage

log = logging.getLogger("docsis.web.weather")

bp = Blueprint("weather_module", __name__)

# Lazy-initialized module-local storage
_storage = None


def _get_weather_storage():
    global _storage
    if _storage is None:
        core_storage = get_storage()
        if core_storage:
            _storage = WeatherStorage(core_storage.db_path)
    return _storage


@bp.route("/api/weather")
@require_auth
def api_weather():
    """Return weather (temperature) history, newest first."""
    _config_manager = get_config_manager()
    if not _config_manager or not _config_manager.is_weather_configured():
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
    state = get_state()
    weather = state.get("weather_latest")
    if not weather:
        return jsonify({"error": "No weather data yet"}), 404
    return jsonify(weather)


@bp.route("/api/weather/range")
@require_auth
def api_weather_range():
    """Return weather data within a timestamp range (for correlation)."""
    _config_manager = get_config_manager()
    if not _config_manager or not _config_manager.is_weather_configured():
        return jsonify([])
    ws = _get_weather_storage()
    if not ws:
        return jsonify([])
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    if not start or not end:
        return jsonify({"error": "start and end parameters required"}), 400
    return jsonify(ws.get_weather_in_range(start, end))
