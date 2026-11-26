"""Tests for weather integration (Open-Meteo client, collector, storage, API)."""

import sys
import os

import pytest
from datetime import date, timedelta
from unittest.mock import DEFAULT, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.modules.weather.client import OpenMeteoClient
from app.modules.weather.collector import WeatherCollector
from app.modules.weather.storage import WeatherStorage
from app.config import ConfigManager
from app.runtime import current_runtime
from app.storage.sqlite import DEFAULT_SQLITE_BUSY_TIMEOUT_MS

HISTORY = [
    {"timestamp": "2025-12-01 00:00:00Z", "temperature": -2.0},
    {"timestamp": "2025-12-01 01:00:00Z", "temperature": -1.5},
]
CURRENT = [{"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0}]


def archive_down(client, *_):
    return patch.object(client, "get_historical", side_effect=Exception("archive down"))


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

    @patch("app.modules.weather.client.requests.Session")
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

    @patch("app.modules.weather.client.requests.Session")
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
        storage = WeatherStorage(str(tmp_path / "test.db"))
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
        storage = WeatherStorage(str(tmp_path / "test.db"))
        records = [{"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.3}]
        storage.save_weather_data(records)
        storage.save_weather_data(records)  # duplicate
        assert storage.get_weather_count() == 1

    def test_get_weather_in_range(self, tmp_path):
        storage = WeatherStorage(str(tmp_path / "test.db"))
        records = [
            {"timestamp": "2026-02-25 10:00:00Z", "temperature": 3.0},
            {"timestamp": "2026-02-26 10:00:00Z", "temperature": 4.0},
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ]
        storage.save_weather_data(records)
        results = storage.get_weather_in_range("2026-02-26 00:00:00Z", "2026-02-27 00:00:00Z")
        assert len(results) == 1
        assert results[0]["temperature"] == 4.0

    def test_get_weather_in_range_accepts_iso_t_query_timestamps(self, tmp_path):
        storage = WeatherStorage(str(tmp_path / "test.db"))
        records = [
            {"timestamp": "2026-02-25 10:00:00Z", "temperature": 3.0},
            {"timestamp": "2026-02-26 10:00:00Z", "temperature": 4.0},
            {"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0},
        ]
        storage.save_weather_data(records)
        results = storage.get_weather_in_range("2026-02-26T00:00:00Z", "2026-02-27T00:00:00Z")
        assert len(results) == 1
        assert results[0]["temperature"] == 4.0

    def test_get_weather_count(self, tmp_path):
        storage = WeatherStorage(str(tmp_path / "test.db"))
        assert storage.get_weather_count() == 0
        storage.save_weather_data([{"timestamp": "2026-02-27 10:00:00Z", "temperature": 5.0}])
        assert storage.get_weather_count() == 1

    def test_wal_mode_enabled(self, tmp_path):
        """WeatherStorage connections use WAL journal mode."""
        storage = WeatherStorage(str(tmp_path / "test.db"))
        with storage._write() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_busy_timeout_set(self, tmp_path):
        """WeatherStorage connections have busy_timeout configured."""
        storage = WeatherStorage(str(tmp_path / "test.db"))
        with storage._write() as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == DEFAULT_SQLITE_BUSY_TIMEOUT_MS

    def test_concurrent_write_no_lock_error(self, tmp_path, caplog):
        """Two WeatherStorage instances writing to the same DB should not raise lock errors."""
        import logging
        import threading
        db_path = str(tmp_path / "concurrent.db")
        errors = []

        def writer(writer_id):
            try:
                s = WeatherStorage(db_path)
                for i in range(50):
                    s.save_weather_data([{
                        "timestamp": f"2026-01-{writer_id:02d} {i:02d}:00:00Z",
                        "temperature": float(i),
                    }])
            except Exception as e:
                errors.append(e)

        with caplog.at_level(logging.ERROR, logger="docsis.storage.weather"):
            t1 = threading.Thread(target=writer, args=(1,))
            t2 = threading.Thread(target=writer, args=(2,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        assert errors == [], f"Concurrent writes failed: {errors}"
        assert "database is locked" not in caplog.text
        storage = WeatherStorage(db_path)
        assert storage.get_weather_count() == 100



# ── WeatherCollector Tests ──


class TestWeatherCollector:
    def _make_collector(self, tmp_path):
        config_mgr = MagicMock()
        config_mgr.is_weather_configured.return_value = True
        config_mgr.get.side_effect = lambda key, default=None: {
            "weather_latitude": "52.52",
            "weather_longitude": "13.41",
        }.get(key, default)
        storage = MagicMock()
        storage.db_path = str(tmp_path / "test.db")
        web = MagicMock()
        collector = WeatherCollector(config_mgr, storage, web)
        return collector, collector._weather_storage, web

    def test_is_enabled(self, tmp_path):
        collector, _, _ = self._make_collector(tmp_path)
        assert collector.is_enabled() is True
        collector._config_mgr.is_weather_configured.return_value = False
        assert collector.is_enabled() is False

    @patch("app.modules.weather.collector.OpenMeteoClient")
    def test_collect_success(self, mock_client_cls, tmp_path):
        collector, storage, web = self._make_collector(tmp_path)
        mock_client = MagicMock()
        mock_client.get_current.return_value = CURRENT
        mock_client_cls.return_value = mock_client

        result = collector.collect()
        assert result.success
        assert storage.get_weather_count() == 1
        web.update_state.assert_called_once()

    @pytest.mark.parametrize("target, published", [("get_current", False), ("save_weather_data", True)],
                             ids=["forecast-error", "current-write-error"])
    @patch("app.modules.weather.collector.OpenMeteoClient")
    def test_collect_failure(self, mock_client_cls, tmp_path, target, published):
        collector, storage, web = self._make_collector(tmp_path)
        client = mock_client_cls.return_value
        client.get_current.return_value = CURRENT

        with patch.object(client if target == "get_current" else storage, target, side_effect=Exception("API error")):
            result = collector.collect()
        assert not result.success
        assert "API error" in result.error
        # The fresh reading is published before the write, so a failed write does not leave it stale.
        assert web.update_state.call_count == published

    @pytest.mark.parametrize("first_current, emptied", [
        (CURRENT, False), (Exception("forecast down"), False), (CURRENT, True),
    ], ids=["complete", "current-failed", "retention-emptied"])
    @patch("app.modules.weather.collector.OpenMeteoClient")
    def test_backfill_runs_only_while_pending(self, mock_client_cls, tmp_path, first_current, emptied):
        collector, storage, _ = self._make_collector(tmp_path)
        client = mock_client_cls.return_value
        client.get_historical.return_value = HISTORY
        client.get_current.side_effect = [first_current, CURRENT]

        assert collector.collect().success is (first_current is CURRENT)
        client.get_historical.assert_called_once()  # also when the forecast request failed
        if emptied:  # retention cleanup removed every row
            with storage._write() as conn:
                conn.execute("DELETE FROM weather_data")
        else:  # restart: the pending mark must be cleared
            collector, storage, _ = self._make_collector(tmp_path)
        assert collector.collect().success
        assert client.get_historical.call_count == 1 + emptied
        assert storage.get_weather_count() == len(HISTORY) + len(CURRENT)

    @pytest.mark.parametrize("restart", [False, True], ids=["same-process", "restart"])
    @pytest.mark.parametrize("failing, first_ok", [
        (archive_down, True),
        # Only the history write fails; the current write goes through.
        (lambda _, storage: patch.object(storage, "save_weather_data", wraps=storage.save_weather_data,
                                         side_effect=[Exception("disk I/O error"), DEFAULT]), True),
        # The pending check fails before anything is written, which fails the poll.
        (lambda *_: patch.object(WeatherStorage, "backfill_pending", side_effect=Exception("database is locked")),
         False),
    ], ids=["archive-error", "history-write-error", "marker-error"])
    @patch("app.modules.weather.collector.OpenMeteoClient")
    def test_failed_backfill_retried_on_next_poll(self, mock_client_cls, tmp_path, failing, first_ok, restart):
        collector, storage, web = self._make_collector(tmp_path)
        client = mock_client_cls.return_value
        client.get_historical.return_value = HISTORY
        client.get_current.return_value = CURRENT

        with failing(client, storage):
            assert collector.collect().success is first_ok
        assert web.update_state.call_count == first_ok
        assert storage.get_weather_count() == (len(CURRENT) if first_ok else 0)

        if restart:
            collector, storage, _ = self._make_collector(tmp_path)
        assert collector.collect().success
        start, end = client.get_historical.call_args.args
        assert date.fromisoformat(end) - date.fromisoformat(start) == timedelta(days=90)
        assert storage.get_weather_count() == len(HISTORY) + len(CURRENT)

    @patch("app.modules.weather.collector.OpenMeteoClient")
    def test_archive_value_wins_on_overlap(self, mock_client_cls, tmp_path):
        collector, storage, _ = self._make_collector(tmp_path)
        client = mock_client_cls.return_value
        client.get_historical.return_value = [{**CURRENT[0], "temperature": -1.0}]
        client.get_current.return_value = CURRENT

        assert collector.collect().success
        assert storage.get_weather_data() == [{"timestamp": CURRENT[0]["timestamp"], "temperature": -1.0}]

    @patch("app.modules.weather.collector.OpenMeteoClient")
    def test_no_backfill_when_data_exists(self, mock_client_cls, tmp_path):
        collector, storage, web = self._make_collector(tmp_path)
        # Pre-populate some data
        storage.save_weather_data([{"timestamp": "2026-02-26 10:00:00Z", "temperature": 4.0}])
        mock_client = MagicMock()
        mock_client.get_current.return_value = CURRENT
        mock_client_cls.return_value = mock_client

        result = collector.collect()
        assert result.success
        # Should NOT call get_historical since data already exists
        mock_client.get_historical.assert_not_called()


# ── Config Tests ──


class TestWeatherConfig:
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
    def weather_client(self, tmp_path, route_app):
        # Reset module-local storage

        data_dir = str(tmp_path / "data_w")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test", "modem_type": "fritzbox", "weather_enabled": True,
                   "weather_latitude": "52.52", "weather_longitude": "13.41"})
        current_runtime().config_manager = mgr
        from app.storage import SnapshotStorage
        storage = SnapshotStorage(str(tmp_path / "weather.db"))
        current_runtime().storage = storage

        with route_app.test_client() as client:
            yield client, WeatherStorage(str(tmp_path / "weather.db"))

        # Cleanup module-local storage

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
        current_runtime().state.reset_modem()
        resp = client.get("/api/weather/current")
        assert resp.status_code == 404

    def test_api_weather_current_with_state(self, weather_client):
        client, _ = weather_client
        current_runtime().update_state(weather_latest={"timestamp": "2026-02-27 12:00:00Z", "temperature": 7.5})
        resp = client.get("/api/weather/current")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["temperature"] == 7.5

    @patch("app.modules.weather.collector.OpenMeteoClient")
    def test_api_weather_current_during_archive_outage(self, mock_client_cls, weather_client):
        client, _ = weather_client
        runtime = current_runtime()
        runtime.state.reset_modem()
        mock_client_cls.return_value.get_current.return_value = CURRENT
        with archive_down(mock_client_cls.return_value):
            assert WeatherCollector(runtime.config_manager, runtime.storage, runtime).collect().success
        assert client.get("/api/weather/current").get_json() == CURRENT[-1]

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

    def test_api_weather_not_configured(self, tmp_path, route_app):
        mgr = ConfigManager(str(tmp_path / "data_nc"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        current_runtime().config_manager = mgr
        current_runtime().storage = None
        with route_app.test_client() as client:
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
