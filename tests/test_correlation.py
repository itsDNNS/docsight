"""Tests for cross-source correlation features."""

import json
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone

from app.storage import SnapshotStorage
from app.modules.speedtest.storage import SpeedtestStorage
from app.tz import utc_now, utc_cutoff
from app.web import app, update_state, init_config, init_storage
from app.config import ConfigManager


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=7)


@pytest.fixture
def speedtest_storage(storage):
    """SpeedtestStorage sharing the same db_path as core storage."""
    return SpeedtestStorage(storage.db_path)


@pytest.fixture
def sample_analysis():
    return {
        "summary": {
            "ds_total": 33, "us_total": 4,
            "ds_power_min": -1.0, "ds_power_max": 5.0, "ds_power_avg": 2.5,
            "us_power_min": 40.0, "us_power_max": 45.0, "us_power_avg": 42.5,
            "ds_snr_min": 35.0, "ds_snr_avg": 37.0,
            "ds_correctable_errors": 1234, "ds_uncorrectable_errors": 56,
            "health": "good", "health_issues": [],
        },
        "ds_channels": [{"channel_id": 1, "power": 3.0, "snr": 35.0}],
        "us_channels": [{"channel_id": 1, "power": 42.0}],
    }


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({
        "modem_password": "test",
        "speedtest_tracker_url": "http://stt:8080",
        "speedtest_tracker_token": "testtoken",
    })
    return mgr


@pytest.fixture
def client_with_storage(config_mgr, storage, speedtest_storage):
    init_config(config_mgr)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestSpeedtestTimestampIndex:
    def test_index_created(self, speedtest_storage):
        """Verify idx_speedtest_ts index exists."""
        with sqlite3.connect(speedtest_storage.db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_speedtest_ts'"
            ).fetchall()
        assert len(rows) == 1

    def test_speedtest_in_range(self, speedtest_storage):
        """get_speedtest_in_range returns results within time window."""
        now = datetime.now()
        results = [
            {
                "id": 1,
                "timestamp": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
                "download_mbps": 450.0, "upload_mbps": 45.0,
                "download_human": "450 Mbps", "upload_human": "45 Mbps",
                "ping_ms": 12.0, "jitter_ms": 2.0, "packet_loss_pct": 0.0,
            },
            {
                "id": 2,
                "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                "download_mbps": 420.0, "upload_mbps": 40.0,
                "download_human": "420 Mbps", "upload_human": "40 Mbps",
                "ping_ms": 15.0, "jitter_ms": 3.0, "packet_loss_pct": 0.1,
            },
            {
                "id": 3,
                "timestamp": (now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S"),
                "download_mbps": 300.0, "upload_mbps": 30.0,
                "download_human": "300 Mbps", "upload_human": "30 Mbps",
                "ping_ms": 20.0, "jitter_ms": 5.0, "packet_loss_pct": 1.0,
            },
        ]
        speedtest_storage.save_speedtest_results(results)
        start = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        in_range = speedtest_storage.get_speedtest_in_range(start, end)
        assert len(in_range) == 2
        assert in_range[0]["id"] == 1
        assert in_range[1]["id"] == 2

    def test_speedtest_in_range_empty(self, speedtest_storage):
        """get_speedtest_in_range returns empty list when no data."""
        now = datetime.now()
        start = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        assert speedtest_storage.get_speedtest_in_range(start, end) == []


class TestCorrelationTimeline:
    def _seed_data(self, storage, speedtest_storage, sample_analysis):
        """Insert modem snapshots, speedtest results, and events."""
        now = datetime.now()
        # Modem snapshots
        for i in range(3):
            ts = (now - timedelta(hours=3 - i)).strftime("%Y-%m-%dT%H:%M:%S")
            with sqlite3.connect(storage.db_path) as conn:
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?,?,?,?)",
                    (ts, json.dumps(sample_analysis["summary"]),
                     json.dumps(sample_analysis["ds_channels"]),
                     json.dumps(sample_analysis["us_channels"])),
                )
        # Speedtest results
        speedtest_storage.save_speedtest_results([{
            "id": 10,
            "timestamp": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
            "download_mbps": 400.0, "upload_mbps": 40.0,
            "download_human": "400 Mbps", "upload_human": "40 Mbps",
            "ping_ms": 12.0, "jitter_ms": 2.0, "packet_loss_pct": 0.0,
        }])
        # Events
        storage.save_event(
            (now - timedelta(hours=1, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
            "warning", "snr_change", "DS SNR dropped to 28.5 dB",
        )
        return now

    def test_all_sources(self, storage, speedtest_storage, sample_analysis):
        """get_correlation_timeline returns all sources when sources=None."""
        now = self._seed_data(storage, speedtest_storage, sample_analysis)
        start = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        timeline = storage.get_correlation_timeline(start, end)
        sources = set(e["source"] for e in timeline)
        assert "modem" in sources
        assert "speedtest" in sources
        assert "event" in sources
        assert len(timeline) == 5  # 3 modem + 1 speedtest + 1 event

    def test_filtered_sources(self, storage, speedtest_storage, sample_analysis):
        """get_correlation_timeline respects sources filter."""
        now = self._seed_data(storage, speedtest_storage, sample_analysis)
        start = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        timeline = storage.get_correlation_timeline(start, end, sources={"modem"})
        assert all(e["source"] == "modem" for e in timeline)
        assert len(timeline) == 3

    def test_sorted_by_timestamp(self, storage, speedtest_storage, sample_analysis):
        """Timeline entries must be sorted chronologically."""
        now = self._seed_data(storage, speedtest_storage, sample_analysis)
        start = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        timeline = storage.get_correlation_timeline(start, end)
        timestamps = [e["timestamp"] for e in timeline]
        assert timestamps == sorted(timestamps)

    def test_modem_fields_present(self, storage, speedtest_storage, sample_analysis):
        """Modem entries must contain health, SNR, power fields."""
        now = self._seed_data(storage, speedtest_storage, sample_analysis)
        start = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        timeline = storage.get_correlation_timeline(start, end, sources={"modem"})
        m = timeline[0]
        assert m["source"] == "modem"
        assert "health" in m
        assert "ds_snr_min" in m
        assert "ds_power_avg" in m

    def test_speedtest_fields_present(self, storage, speedtest_storage, sample_analysis):
        """Speedtest entries must contain download, upload, ping."""
        now = self._seed_data(storage, speedtest_storage, sample_analysis)
        start = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        timeline = storage.get_correlation_timeline(start, end, sources={"speedtest"})
        s = timeline[0]
        assert s["source"] == "speedtest"
        assert "download_mbps" in s
        assert "upload_mbps" in s
        assert "ping_ms" in s

    def test_event_fields_present(self, storage, speedtest_storage, sample_analysis):
        """Event entries must contain severity, type, message."""
        now = self._seed_data(storage, speedtest_storage, sample_analysis)
        start = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        timeline = storage.get_correlation_timeline(start, end, sources={"events"})
        e = timeline[0]
        assert e["source"] == "event"
        assert e["severity"] == "warning"
        assert e["event_type"] == "snr_change"
        assert "message" in e

    def test_empty_range(self, storage):
        """Empty database returns empty timeline."""
        now = datetime.now()
        start = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        end = now.strftime("%Y-%m-%dT%H:%M:%S")
        assert storage.get_correlation_timeline(start, end) == []


class TestCorrelationAPI:
    def test_correlation_endpoint_no_auth(self, client_with_storage):
        """Correlation endpoint requires no auth when no password is set."""
        resp = client_with_storage.get("/api/correlation?hours=24")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)

    def test_correlation_endpoint_with_data(self, client_with_storage, storage, speedtest_storage, sample_analysis):
        """Correlation endpoint returns data from all sources."""
        ts = utc_now()
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?,?,?,?)",
                (ts, json.dumps(sample_analysis["summary"]),
                 json.dumps(sample_analysis["ds_channels"]),
                 json.dumps(sample_analysis["us_channels"])),
            )
        speedtest_storage.save_speedtest_results([{
            "id": 99,
            "timestamp": ts,
            "download_mbps": 500.0, "upload_mbps": 50.0,
            "download_human": "500 Mbps", "upload_human": "50 Mbps",
            "ping_ms": 10.0, "jitter_ms": 1.0, "packet_loss_pct": 0.0,
        }])
        resp = client_with_storage.get("/api/correlation?hours=1")
        data = json.loads(resp.data)
        sources = set(e["source"] for e in data)
        assert "modem" in sources
        assert "speedtest" in sources

    def test_correlation_source_filter(self, client_with_storage, storage, sample_analysis):
        """Correlation endpoint respects sources filter."""
        ts = utc_now()
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?,?,?,?)",
                (ts, json.dumps(sample_analysis["summary"]),
                 json.dumps(sample_analysis["ds_channels"]),
                 json.dumps(sample_analysis["us_channels"])),
            )
        storage.save_event(ts, "info", "health_change", "Health changed to good")
        resp = client_with_storage.get("/api/correlation?hours=1&sources=events")
        data = json.loads(resp.data)
        assert all(e["source"] == "event" for e in data)

    def test_correlation_speedtest_enrichment(self, client_with_storage, storage, speedtest_storage, sample_analysis):
        """Speedtest entries get enriched with modem_health."""
        ts = utc_now()
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?,?,?,?)",
                (ts, json.dumps(sample_analysis["summary"]),
                 json.dumps(sample_analysis["ds_channels"]),
                 json.dumps(sample_analysis["us_channels"])),
            )
        speedtest_storage.save_speedtest_results([{
            "id": 100,
            "timestamp": ts,
            "download_mbps": 480.0, "upload_mbps": 48.0,
            "download_human": "480 Mbps", "upload_human": "48 Mbps",
            "ping_ms": 11.0, "jitter_ms": 1.5, "packet_loss_pct": 0.0,
        }])
        resp = client_with_storage.get("/api/correlation?hours=1")
        data = json.loads(resp.data)
        speedtest_entries = [e for e in data if e["source"] == "speedtest"]
        assert len(speedtest_entries) == 1
        assert speedtest_entries[0].get("modem_health") == "good"

    def test_correlation_hours_clamped(self, client_with_storage):
        """Hours parameter is clamped to 1-168."""
        resp = client_with_storage.get("/api/correlation?hours=999")
        assert resp.status_code == 200
        resp = client_with_storage.get("/api/correlation?hours=0")
        assert resp.status_code == 200
