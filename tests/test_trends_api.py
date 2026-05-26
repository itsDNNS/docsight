"""Tests for Signal Trends range normalization."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage


def _utc_ts(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _analysis(ds_power_avg: float):
    return {
        "summary": {
            "ds_total": 1,
            "us_total": 1,
            "health": "good",
            "health_issues": [],
            "ds_power_avg": ds_power_avg,
            "ds_snr_avg": 38.0,
            "us_power_avg": 42.0,
        },
        "ds_channels": [],
        "us_channels": [],
    }


def _insert_snapshot(storage, analysis, timestamp):
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
            (
                timestamp,
                json.dumps(analysis["summary"]),
                json.dumps(analysis["ds_channels"]),
                json.dumps(analysis["us_channels"]),
            ),
        )


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "api.db")
    storage = SnapshotStorage(db_path, max_days=120)
    data_dir = str(tmp_path / "data")
    manager = ConfigManager(data_dir)
    manager.save({"modem_password": "test", "modem_type": "fritzbox"})
    init_config(manager)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as flask_client:
        yield flask_client, storage


class TestTrendsRangeEndpoint:
    def test_range_param_supports_one_hour_window(self, client):
        flask_client, storage = client
        _insert_snapshot(storage, _analysis(1.0), _utc_ts(timedelta(hours=2)))
        _insert_snapshot(storage, _analysis(2.0), _utc_ts(timedelta(minutes=20)))

        resp = flask_client.get("/api/trends?range=1h")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["ds_power_avg"] == 2.0

    def test_range_param_supports_normalized_day_window(self, client):
        flask_client, storage = client
        _insert_snapshot(storage, _analysis(1.0), _utc_ts(timedelta(days=2)))
        _insert_snapshot(storage, _analysis(2.0), _utc_ts(timedelta(hours=2)))

        resp = flask_client.get("/api/trends?range=1d")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["ds_power_avg"] == 2.0

    def test_legacy_trend_ranges_still_work(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        for range_name in ("day", "week", "month"):
            resp = flask_client.get(f"/api/trends?range={range_name}")
            assert resp.status_code == 200, range_name

    def test_normalized_ranges_ignore_legacy_date_parameter(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        resp = flask_client.get("/api/trends?range=1d&date=not-a-date")

        assert resp.status_code == 200

    def test_legacy_ranges_still_validate_date_parameter(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        resp = flask_client.get("/api/trends?range=week&date=not-a-date")

        assert resp.status_code == 400

    def test_invalid_range_param_is_rejected(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        resp = flask_client.get("/api/trends?range=4h")

        assert resp.status_code == 400
