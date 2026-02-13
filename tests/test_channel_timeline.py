"""Tests for per-channel timeline: storage, /api/channels, /api/channel-history."""

import json
import time
import pytest
from datetime import datetime, timedelta

from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage
from app.config import ConfigManager


# ── Fixtures ──

def _make_analysis(ds_channels=None, us_channels=None):
    if ds_channels is None:
        ds_channels = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "correctable_errors": 10,
             "uncorrectable_errors": 2, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
            {"channel_id": 2, "frequency": "130.0 MHz", "power": 4.8,
             "modulation": "256QAM", "snr": 37.5, "correctable_errors": 20,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
    if us_channels is None:
        us_channels = [
            {"channel_id": 1, "frequency": "37 MHz", "power": 42.0,
             "modulation": "64QAM", "multiplex": "ATDMA",
             "docsis_version": "3.0", "health": "good", "health_detail": ""},
        ]
    return {
        "summary": {"ds_total": len(ds_channels), "us_total": len(us_channels),
                     "health": "good", "health_issues": []},
        "ds_channels": ds_channels,
        "us_channels": us_channels,
    }


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=30)


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "api.db")
    s = SnapshotStorage(db_path, max_days=30)
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test"})
    init_config(mgr)
    init_storage(s)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, s


# ── Storage Tests ──

class TestGetChannelHistory:
    def test_returns_time_series(self, storage):
        storage.save_snapshot(_make_analysis())
        storage.save_snapshot(_make_analysis())
        result = storage.get_channel_history(1, "ds", days=7)
        assert len(result) == 2
        assert result[0]["power"] == 5.2
        assert result[0]["snr"] == 38.1
        assert result[0]["correctable_errors"] == 10
        assert result[0]["uncorrectable_errors"] == 2
        assert result[0]["modulation"] == "256QAM"
        assert result[0]["health"] == "good"
        assert "timestamp" in result[0]

    def test_filters_by_channel_id(self, storage):
        storage.save_snapshot(_make_analysis())
        result_ch1 = storage.get_channel_history(1, "ds", days=7)
        result_ch2 = storage.get_channel_history(2, "ds", days=7)
        assert len(result_ch1) == 1
        assert result_ch1[0]["power"] == 5.2
        assert len(result_ch2) == 1
        assert result_ch2[0]["power"] == 4.8

    def test_upstream_channel(self, storage):
        storage.save_snapshot(_make_analysis())
        result = storage.get_channel_history(1, "us", days=7)
        assert len(result) == 1
        assert result[0]["power"] == 42.0

    def test_nonexistent_channel(self, storage):
        storage.save_snapshot(_make_analysis())
        result = storage.get_channel_history(99, "ds", days=7)
        assert result == []

    def test_empty_storage(self, storage):
        result = storage.get_channel_history(1, "ds", days=7)
        assert result == []

    def test_respects_days_param(self, storage):
        # Save snapshot with a timestamp in the past
        import sqlite3
        old_ts = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        analysis = _make_analysis()
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
                (old_ts, json.dumps(analysis["summary"]),
                 json.dumps(analysis["ds_channels"]),
                 json.dumps(analysis["us_channels"])),
            )
        # Recent snapshot
        storage.save_snapshot(_make_analysis())
        # 7-day window should only get the recent one
        result = storage.get_channel_history(1, "ds", days=7)
        assert len(result) == 1
        # 30-day window should get both
        result_30 = storage.get_channel_history(1, "ds", days=30)
        assert len(result_30) == 2


class TestGetCurrentChannels:
    def test_returns_channels(self, storage):
        storage.save_snapshot(_make_analysis())
        result = storage.get_current_channels()
        assert len(result["ds_channels"]) == 2
        assert len(result["us_channels"]) == 1
        assert result["ds_channels"][0]["channel_id"] == 1

    def test_empty_storage(self, storage):
        result = storage.get_current_channels()
        assert result == {"ds_channels": [], "us_channels": []}


# ── API Tests ──

class TestChannelsEndpoint:
    def test_returns_channels(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        resp = c.get("/api/channels")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data["ds_channels"]) == 2
        assert len(data["us_channels"]) == 1

    def test_empty(self, client):
        c, s = client
        resp = c.get("/api/channels")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ds_channels"] == []
        assert data["us_channels"] == []


class TestChannelHistoryEndpoint:
    def test_returns_history(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        resp = c.get("/api/channel-history?channel_id=1&direction=ds&days=7")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["power"] == 5.2

    def test_missing_channel_id(self, client):
        c, s = client
        resp = c.get("/api/channel-history?direction=ds&days=7")
        assert resp.status_code == 400

    def test_invalid_direction(self, client):
        c, s = client
        resp = c.get("/api/channel-history?channel_id=1&direction=invalid")
        assert resp.status_code == 400

    def test_upstream_channel(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        resp = c.get("/api/channel-history?channel_id=1&direction=us&days=7")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["power"] == 42.0

    def test_no_storage(self, tmp_path):
        data_dir = str(tmp_path / "data2")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test"})
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/api/channel-history?channel_id=1&direction=ds")
            assert resp.status_code == 200
            assert json.loads(resp.data) == []

    def test_days_clamped(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        # days=0 should be clamped to 1
        resp = c.get("/api/channel-history?channel_id=1&direction=ds&days=0")
        assert resp.status_code == 200
        # days=200 should be clamped to 90
        resp2 = c.get("/api/channel-history?channel_id=1&direction=ds&days=200")
        assert resp2.status_code == 200
