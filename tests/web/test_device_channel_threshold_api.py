"""Tests for device, channel, speedtest, and threshold endpoints."""

import pytest

from app.web import app, update_state, init_storage, init_config
from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.modules.speedtest.storage import SpeedtestStorage

class TestChannelsAPI:
    def test_channels_includes_summary(self, client, sample_analysis, tmp_path):
        update_state(analysis=sample_analysis)
        db_path = str(tmp_path / "channels_test.db")
        storage = SnapshotStorage(db_path, max_days=7)
        storage.save_snapshot(sample_analysis)
        init_storage(storage)
        resp = client.get("/api/channels")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ds_channels" in data
        assert "us_channels" in data
        assert "summary" in data
        assert data["summary"]["health"] == "good"
        assert data["summary"]["ds_total"] == 33
        assert "health_issues" in data["summary"]
        assert "us_total" in data["summary"]
        assert "us_capacity_mbps" in data["summary"]

    def test_channels_no_storage(self, client):
        from app.web import _state
        _state["analysis"] = None
        init_storage(None)
        resp = client.get("/api/channels")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ds_channels"] == []
        assert data["summary"] is None


class TestDeviceAPI:
    def test_device_returns_info(self, client):
        update_state(device_info={
            "model": "FRITZ!Box 6690 Cable",
            "manufacturer": "AVM",
            "sw_version": "7.57",
            "uptime_seconds": 86400,
        })
        resp = client.get("/api/device")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["model"] == "FRITZ!Box 6690 Cable"
        assert data["uptime_seconds"] == 86400

    def test_device_not_available(self, client):
        from app.web import _state
        _state["device_info"] = None
        resp = client.get("/api/device")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {}


class TestSpeedtestDetailAPI:
    def _reset_speedtest_module(self):
        import app.modules.speedtest.routes as st_routes
        st_routes._storage = None

    @pytest.fixture
    def storage_with_speedtest(self, tmp_path):
        db_path = str(tmp_path / "speed_test.db")
        storage = SnapshotStorage(db_path, max_days=7)
        ss = SpeedtestStorage(db_path)
        ss.save_speedtest_results([{
            "id": 42,
            "timestamp": "2026-02-27T12:00:00Z",
            "download_mbps": 500.0,
            "upload_mbps": 50.0,
            "download_human": "500 Mbps",
            "upload_human": "50 Mbps",
            "ping_ms": 12.0,
            "jitter_ms": 2.0,
            "packet_loss_pct": 0.0,
            "server_id": 1,
            "server_name": "Frankfurt",
        }])
        return storage

    def test_speedtest_by_id(self, client, storage_with_speedtest):
        self._reset_speedtest_module()
        init_storage(storage_with_speedtest)
        resp = client.get("/api/speedtest/42")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == 42
        assert data["download_mbps"] == 500.0

    def test_speedtest_not_found(self, client, storage_with_speedtest):
        self._reset_speedtest_module()
        init_storage(storage_with_speedtest)
        resp = client.get("/api/speedtest/9999")
        assert resp.status_code == 404

    def test_speedtest_detail_includes_quality_fields(self, tmp_path):
        """Issue #113: speedtest responses should include classification fields."""
        self._reset_speedtest_module()
        mgr = ConfigManager(str(tmp_path / "data_sq"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox", "booked_download": 1000, "booked_upload": 50})
        init_config(mgr)
        db_path = str(tmp_path / "sq.db")
        storage = SnapshotStorage(db_path, max_days=7)
        ss = SpeedtestStorage(db_path)
        ss.save_speedtest_results([{
            "id": 1, "timestamp": "2026-02-27T12:00:00Z",
            "download_mbps": 900.0, "upload_mbps": 45.0,
            "download_human": "900 Mbps", "upload_human": "45 Mbps",
            "ping_ms": 10.0, "jitter_ms": 1.0, "packet_loss_pct": 0.0,
            "server_id": 1, "server_name": "Frankfurt",
        }])
        init_storage(storage)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/api/speedtest/1")
            assert resp.status_code == 200
            data = resp.get_json()
            # 900/1000 = 0.9 >= 0.8 -> good
            assert data["speed_health"] == "good"
            assert data["download_class"] == "good"
            # 45/50 = 0.9 >= 0.8 -> good
            assert data["upload_class"] == "good"

    def test_speedtest_quality_warn_and_poor(self, tmp_path):
        self._reset_speedtest_module()
        mgr = ConfigManager(str(tmp_path / "data_sq2"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox", "booked_download": 1000, "booked_upload": 100})
        init_config(mgr)
        db_path = str(tmp_path / "sq2.db")
        storage = SnapshotStorage(db_path, max_days=7)
        ss = SpeedtestStorage(db_path)
        ss.save_speedtest_results([{
            "id": 10, "timestamp": "2026-02-27T12:00:00Z",
            "download_mbps": 600.0, "upload_mbps": 30.0,
            "download_human": "600 Mbps", "upload_human": "30 Mbps",
            "ping_ms": 10.0, "jitter_ms": 1.0, "packet_loss_pct": 0.0,
            "server_id": 1, "server_name": "Frankfurt",
        }])
        init_storage(storage)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/api/speedtest/10")
            data = resp.get_json()
            # 600/1000 = 0.6 -> warn
            assert data["download_class"] == "warn"
            # 30/100 = 0.3 -> poor
            assert data["upload_class"] == "poor"
            # speed_health = worst of dl/ul = poor
            assert data["speed_health"] == "poor"

    def test_speedtest_quality_no_booked_speeds(self, client, storage_with_speedtest):
        """Without booked speeds and no connection_info, quality fields should be null."""
        self._reset_speedtest_module()
        from app.web import _state
        _state["connection_info"] = None
        init_storage(storage_with_speedtest)
        resp = client.get("/api/speedtest/42")
        data = resp.get_json()
        assert data["speed_health"] is None
        assert data["download_class"] is None
        assert data["upload_class"] is None


class TestThresholdsAPI:
    def test_thresholds_returns_data(self, client):
        resp = client.get("/api/thresholds")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "downstream_power" in data
        assert "upstream_power" in data
        assert "snr" in data
        assert "errors" in data

    def test_thresholds_excludes_internal_keys(self, client):
        resp = client.get("/api/thresholds")
        data = resp.get_json()
        assert "_source" not in data
        assert "_note" not in data
        for section in data.values():
            if isinstance(section, dict):
                assert "_comment" not in section
                assert "_default" not in section
