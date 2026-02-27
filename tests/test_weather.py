"""Tests for weather integration (Open-Meteo client, collector, storage, API)."""

import sys
import os
import json

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.weather import OpenMeteoClient
from app.collectors.weather import WeatherCollector
from app.storage import SnapshotStorage
from app.config import ConfigManager
from app.web import app, init_config, init_storage, update_state


# ── OpenMeteoClient Tests ──


class TestOpenMeteoClient:
    def test_parse_hourly(self):
        data = {
            "hourly": {
                "time": ["2026-02-27T10:00", "2026-02-27T11:00", "2026-02-27T12:00"],
                "temperature_2m": [5.3, 6.1, None],
            }
        }
        results = OpenMeteoClient._parse_hourly(data)
        assert len(results) == 2  # None filtered out
        assert results[0]["timestamp"] == "2026-02-27 10:00:00Z"
        assert results[0]["temperature"] == 5.3
        assert results[1]["temperature"] == 6.1

    def test_parse_hourly_empty(self):
        results = OpenMeteoClient._parse_hourly({})
        assert results == []

    def test_parse_hourly_all_none(self):
        data = {
            "hourly": {
                "time": ["2026-02-27T10:00"],
                "temperature_2m": [None],
            }
        }
        results = OpenMeteoClient._parse_hourly(data)
        assert results == []

    @patch("app.weather.requests.Session")
    def test_get_current(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hourly": {
                "time": ["2026-02-27T10:00", "2026-02-27T11:00"],
                "temperature_2m": [5.0, 6.0],
            }
        }
        mock_session.get.return_value = mock_resp

        client = OpenMeteoClient(52.52, 13.41)
        results = client.get_current()
        assert len(results) == 2
        mock_session.get.assert_called_once()
        args, kwargs = mock_session.get.call_args
        assert "forecast" in args[0]
        assert kwargs["params"]["latitude"] == 52.52

    @patch("app.weather.requests.Session")
    def test_get_historical(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hourly": {
                "time": ["2025-12-01T00:00"],
                "temperature_2m": [-2.5],
            }
        }
        mock_session.get.return_value = mock_resp

        client = OpenMeteoClient(52.52, 13.41)
        results = client.get_historical("2025-12-01", "2025-12-01")
        assert len(results) == 1
        assert results[0]["temperature"] == -2.5
        args, kwargs = mock_session.get.call_args
        assert "archive" in args[0]


# ── Storage Tests ──


class TestWeatherStorage:
    def test_save_and_get_weather_data(self, tmp_path):
        storage = SnapshotStorage(str(tmp_path / "test.db"))
        records = [
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.3},
            {"timestamp": "2026-02-27 11:00:00Z", "temperature": 6.1},
        ]
        storage.save_weather_data(records)
        results = storage.get_weather_data()
        assert len(results) == 2
        # Newest first
        assert results[0]["temperature"] == 6.1
        assert results[1]["temperature"] == 5.3

    def test_save_ignores_duplicates(self, tmp_path):
        storage = SnapshotStorage(str(tmp_path / "test.db"))
        records = [{"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.3}]
        storage.save_weather_data(records)
        storage.save_weather_data(records)  # duplicate
        assert storage.get_weather_count() == 1

    def test_get_weather_in_range(self, tmp_path):
        storage = SnapshotStorage(str(tmp_path / "test.db"))
        records = [
            {"timestamp": "2026-02-25 10:00:00Z", "temperature": 3.0},
            {"timestamp": "2026-02-26 10:00:00Z", "temperature": 4.0},
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ]
        storage.save_weather_data(records)
        results = storage.get_weather_in_range("2026-02-26 00:00:00Z", "2026-02-27 00:00:00Z")
        assert len(results) == 1
        assert results[0]["temperature"] == 4.0

    def test_get_weather_count(self, tmp_path):
        storage = SnapshotStorage(str(tmp_path / "test.db"))
        assert storage.get_weather_count() == 0
        storage.save_weather_data([{"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0}])
        assert storage.get_weather_count() == 1

    def test_get_latest_weather_timestamp(self, tmp_path):
        storage = SnapshotStorage(str(tmp_path / "test.db"))
        assert storage.get_latest_weather_timestamp() is None
        storage.save_weather_data([
            {"timestamp": "2026-02-26 10:00:00Z", "temperature": 4.0},
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ])
        assert storage.get_latest_weather_timestamp() == "2026-02-27 10:00:00Z"

    def test_save_weather_data_demo_flag(self, tmp_path):
        storage = SnapshotStorage(str(tmp_path / "test.db"))
        records = [{"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0}]
        storage.save_weather_data(records, is_demo=True)
        # Should be purged with purge_demo_data
        purged = storage.purge_demo_data()
        assert purged >= 1
        assert storage.get_weather_count() == 0


# ── WeatherCollector Tests ──


class TestWeatherCollector:
    def _make_collector(self, tmp_path):
        config_mgr = MagicMock()
        config_mgr.is_weather_configured.return_value = True
        config_mgr.get.side_effect = lambda key, default=None: {
            "weather_latitude": "52.52",
            "weather_longitude": "13.41",
        }.get(key, default)
        storage = SnapshotStorage(str(tmp_path / "test.db"))
        web = MagicMock()
        return WeatherCollector(config_mgr, storage, web), storage, web

    def test_is_enabled(self, tmp_path):
        collector, _, _ = self._make_collector(tmp_path)
        assert collector.is_enabled() is True
        collector._config_mgr.is_weather_configured.return_value = False
        assert collector.is_enabled() is False

    @patch("app.collectors.weather.OpenMeteoClient")
    def test_collect_success(self, mock_client_cls, tmp_path):
        collector, storage, web = self._make_collector(tmp_path)
        mock_client = MagicMock()
        mock_client.get_current.return_value = [
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ]
        mock_client_cls.return_value = mock_client

        result = collector.collect()
        assert result.success
        assert storage.get_weather_count() == 1
        web.update_state.assert_called_once()

    @patch("app.collectors.weather.OpenMeteoClient")
    def test_collect_failure(self, mock_client_cls, tmp_path):
        collector, storage, web = self._make_collector(tmp_path)
        mock_client = MagicMock()
        mock_client.get_current.side_effect = Exception("API error")
        mock_client_cls.return_value = mock_client

        # Mark backfill done so it doesn't interfere
        collector._backfilled = True
        result = collector.collect()
        assert not result.success
        assert "API error" in result.error

    @patch("app.collectors.weather.OpenMeteoClient")
    def test_backfill_on_first_run(self, mock_client_cls, tmp_path):
        collector, storage, web = self._make_collector(tmp_path)
        mock_client = MagicMock()
        mock_client.get_current.return_value = [
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ]
        mock_client.get_historical.return_value = [
            {"timestamp": "2025-12-01 00:00:00Z", "temperature": -2.0},
            {"timestamp": "2025-12-01 01:00:00Z", "temperature": -1.5},
        ]
        mock_client_cls.return_value = mock_client

        result = collector.collect()
        assert result.success
        # Backfill + current = 3 records
        assert storage.get_weather_count() == 3
        assert collector._backfilled is True

    @patch("app.collectors.weather.OpenMeteoClient")
    def test_no_backfill_when_data_exists(self, mock_client_cls, tmp_path):
        collector, storage, web = self._make_collector(tmp_path)
        # Pre-populate some data
        storage.save_weather_data([{"timestamp": "2026-02-26 10:00:00Z", "temperature": 4.0}])
        mock_client = MagicMock()
        mock_client.get_current.return_value = [
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ]
        mock_client_cls.return_value = mock_client

        result = collector.collect()
        assert result.success
        # Should NOT call get_historical since data already exists
        mock_client.get_historical.assert_not_called()


# ── Config Tests ──


class TestWeatherConfig:
    def test_weather_config_defaults(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        assert mgr.get("weather_enabled") is False
        assert mgr.get("weather_latitude") == ""
        assert mgr.get("weather_longitude") == ""

    def test_is_weather_configured_false_by_default(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        assert mgr.is_weather_configured() is False

    def test_is_weather_configured_true(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"weather_enabled": True, "weather_latitude": "52.52", "weather_longitude": "13.41"})
        assert mgr.is_weather_configured() is True

    def test_is_weather_configured_needs_both_coords(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"weather_enabled": True, "weather_latitude": "52.52"})
        assert mgr.is_weather_configured() is False

    def test_is_weather_configured_demo_mode(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"demo_mode": True})
        assert mgr.is_weather_configured() is True


# ── API Endpoint Tests ──


class TestWeatherAPI:
    @pytest.fixture
    def weather_client(self, tmp_path):
        data_dir = str(tmp_path / "data_w")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test", "weather_enabled": True,
                   "weather_latitude": "52.52", "weather_longitude": "13.41"})
        init_config(mgr)
        storage = SnapshotStorage(str(tmp_path / "weather.db"))
        init_storage(storage)
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client, storage

    def test_api_weather_empty(self, weather_client):
        client, _ = weather_client
        resp = client.get("/api/weather")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_api_weather_with_data(self, weather_client):
        client, storage = weather_client
        storage.save_weather_data([
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.3},
            {"timestamp": "2026-02-27 11:00:00Z", "temperature": 6.1},
        ])
        resp = client.get("/api/weather")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["temperature"] == 6.1  # newest first

    def test_api_weather_current_no_data(self, weather_client):
        client, _ = weather_client
        from app.web import _state
        _state["weather_latest"] = None
        resp = client.get("/api/weather/current")
        assert resp.status_code == 404

    def test_api_weather_current_with_state(self, weather_client):
        client, _ = weather_client
        update_state(weather_latest={"timestamp": "2026-02-27 12:00:00Z", "temperature": 7.5})
        resp = client.get("/api/weather/current")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["temperature"] == 7.5

    def test_api_weather_range(self, weather_client):
        client, storage = weather_client
        storage.save_weather_data([
            {"timestamp": "2026-02-25 10:00:00Z", "temperature": 3.0},
            {"timestamp": "2026-02-26 10:00:00Z", "temperature": 4.0},
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ])
        resp = client.get("/api/weather/range?start=2026-02-26 00:00:00Z&end=2026-02-27 00:00:00Z")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["temperature"] == 4.0

    def test_api_weather_range_missing_params(self, weather_client):
        client, _ = weather_client
        resp = client.get("/api/weather/range")
        assert resp.status_code == 400

    def test_api_weather_not_configured(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data_nc"))
        mgr.save({"modem_password": "test"})
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/weather")
            assert resp.status_code == 200
            assert resp.get_json() == []

    def test_api_weather_count_param(self, weather_client):
        client, storage = weather_client
        storage.save_weather_data([
            {"timestamp": f"2026-02-27 {h:02d}:00:00Z", "temperature": float(h)}
            for h in range(10)
        ])
        resp = client.get("/api/weather?count=3")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3
