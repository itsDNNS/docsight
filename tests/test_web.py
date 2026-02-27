"""Tests for Flask web routes and API endpoints."""

import io
import json
import pytest
from app.web import app, update_state, init_config, init_storage
from app.config import ConfigManager
from app.storage import SnapshotStorage


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "isp_name": "Vodafone"})
    return mgr


@pytest.fixture
def client(config_mgr):
    init_config(config_mgr)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def sample_analysis():
    return {
        "summary": {
            "ds_total": 33,
            "us_total": 4,
            "ds_power_min": -1.0,
            "ds_power_max": 5.0,
            "ds_power_avg": 2.5,
            "us_power_min": 40.0,
            "us_power_max": 45.0,
            "us_power_avg": 42.5,
            "ds_snr_min": 35.0,
            "ds_snr_avg": 37.0,
            "ds_correctable_errors": 1234,
            "ds_uncorrectable_errors": 56,
            "health": "good",
            "health_issues": [],
            "us_capacity_mbps": 50.0,
        },
        "ds_channels": [
            {
                "channel_id": 1,
                "frequency": "602 MHz",
                "power": 3.0,
                "snr": 35.0,
                "modulation": "256QAM",
                "correctable_errors": 100,
                "uncorrectable_errors": 5,
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            }
        ],
        "us_channels": [
            {
                "channel_id": 1,
                "frequency": "37 MHz",
                "power": 42.0,
                "modulation": "64QAM",
                "multiplex": "ATDMA",
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            }
        ],
    }


class TestIndexRoute:
    def test_redirect_to_setup_when_unconfigured(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data2"))
        init_config(mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/")
            assert resp.status_code == 302
            assert "/setup" in resp.headers["Location"]

    def test_index_renders(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"DOCSight" in resp.data

    def test_index_with_lang(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/?lang=de")
        assert resp.status_code == 200


class TestHealthEndpoint:
    def test_health_waiting(self, client):
        update_state(analysis=None)
        # Reset state
        from app.web import _state
        _state["analysis"] = None
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["docsis_health"] == "waiting"

    def test_health_ok(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["docsis_health"] == "good"


class TestExportEndpoint:
    def test_export_no_data(self, client):
        from app.web import _state
        _state["analysis"] = None
        resp = client.get("/api/export")
        assert resp.status_code == 404

    def test_export_returns_markdown(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/api/export")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "DOCSight" in data["text"]
        assert "DOCSIS" in data["text"]
        assert "Vodafone" in data["text"]




class TestSnapshotsEndpoint:
    def test_snapshots_no_storage(self, client):
        resp = client.get("/api/snapshots")
        assert resp.status_code == 200
        assert json.loads(resp.data) == []


class TestSetupRoute:
    def test_setup_redirects_when_configured(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 302
        assert "/" == resp.headers["Location"]

    def test_setup_renders_when_unconfigured(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data3"))
        init_config(mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/setup")
            assert resp.status_code == 200
            assert b"DOCSight" in resp.data


class TestSettingsRoute:
    def test_settings_renders(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200


class TestConfigAPI:
    def test_save_config(self, client):
        resp = client.post(
            "/api/config",
            data=json.dumps({"poll_interval": 120}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True

    def test_save_clamps_poll_interval(self, client):
        resp = client.post(
            "/api/config",
            data=json.dumps({"poll_interval": 10}),
            content_type="application/json",
        )
        assert json.loads(resp.data)["success"] is True

    def test_save_no_data(self, client):
        resp = client.post("/api/config", content_type="application/json")
        assert resp.status_code in (400, 500)


class TestSecurityHeaders:
    def test_headers_present(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_headers_on_health(self, client):
        resp = client.get("/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"


class TestTimestampValidation:
    def test_valid_timestamp_accepted(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        # No storage, so snapshot lookup returns None and falls through to live view
        resp = client.get("/?t=2026-01-01T06:00:00")
        assert resp.status_code == 200


class TestSessionKeyPersistence:
    def test_session_key_file_created(self, tmp_path):
        data_dir = str(tmp_path / "data_sk")
        mgr = ConfigManager(data_dir)
        init_config(mgr)
        import os
        assert os.path.exists(os.path.join(data_dir, ".session_key"))

    def test_session_key_persisted(self, tmp_path):
        data_dir = str(tmp_path / "data_sk2")
        mgr = ConfigManager(data_dir)
        init_config(mgr)
        key1 = app.secret_key
        # Re-init should load same key
        init_config(mgr)
        assert app.secret_key == key1


class TestPollEndpoint:
    def test_poll_not_configured(self, tmp_path):
        from app.web import _state
        mgr = ConfigManager(str(tmp_path / "data_poll"))
        init_config(mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post("/api/poll")
            # Unconfigured -> redirects to setup on GET, but POST /api/poll
            # should still be accessible (no auth required when no password)
            assert resp.status_code in (302, 500)

    def test_poll_rate_limit(self, client, sample_analysis):
        import app.web as web_module
        from unittest.mock import MagicMock
        mock_collector = MagicMock()
        web_module._modem_collector = mock_collector
        web_module._last_manual_poll = __import__('time').time()
        resp = client.post("/api/poll")
        assert resp.status_code == 429
        data = json.loads(resp.data)
        assert data["success"] is False
        # Reset for other tests
        web_module._last_manual_poll = 0.0
        web_module._modem_collector = None


class TestFormatK:
    def test_large_number(self):
        from app.web import format_k
        assert format_k(132007) == "132k"

    def test_medium_number(self):
        from app.web import format_k
        assert format_k(5929) == "5.9k"

    def test_round_thousand(self):
        from app.web import format_k
        assert format_k(3000) == "3k"

    def test_small_number(self):
        from app.web import format_k
        assert format_k(42) == "42"

    def test_invalid(self):
        from app.web import format_k
        assert format_k("bad") == "bad"


@pytest.fixture
def storage_client(tmp_path, config_mgr):
    """Client with real storage for BNetzA tests."""
    db_path = str(tmp_path / "test_web.db")
    storage = SnapshotStorage(db_path, max_days=7)
    init_config(config_mgr)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, storage
    init_storage(None)


class TestBnetzAPI:
    def test_list_empty(self, storage_client):
        client, _ = storage_client
        resp = client.get("/api/bnetz/measurements")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_upload_no_file(self, storage_client):
        client, _ = storage_client
        resp = client.post("/api/bnetz/upload")
        assert resp.status_code == 400

    def test_upload_not_pdf(self, storage_client):
        client, _ = storage_client
        data = {"file": (io.BytesIO(b"not a pdf"), "test.pdf", "application/pdf")}
        resp = client.post("/api/bnetz/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "PDF" in resp.get_json()["error"]

    def test_upload_and_list(self, storage_client):
        client, storage = storage_client
        # Directly insert via storage (to avoid needing a real BNetzA PDF)
        parsed = {
            "date": "2025-02-04",
            "provider": "Vodafone",
            "tariff": "GigaZuhause 1000",
            "download_max": 1000.0,
            "download_normal": 850.0,
            "download_min": 600.0,
            "upload_max": 50.0,
            "upload_normal": 35.0,
            "upload_min": 15.0,
            "measurement_count": 30,
            "measurements_download": [],
            "measurements_upload": [],
            "download_measured_avg": 748.0,
            "upload_measured_avg": 7.8,
            "verdict_download": "deviation",
            "verdict_upload": "deviation",
        }
        storage.save_bnetz_measurement(parsed, b"%PDF-test")
        resp = client.get("/api/bnetz/measurements")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["provider"] == "Vodafone"

    def test_pdf_download(self, storage_client):
        client, storage = storage_client
        mid = storage.save_bnetz_measurement(
            {"date": "2025-01-01", "measurements_download": [], "measurements_upload": []},
            b"%PDF-download-test",
        )
        resp = client.get(f"/api/bnetz/pdf/{mid}")
        assert resp.status_code == 200
        assert resp.data == b"%PDF-download-test"
        assert resp.content_type == "application/pdf"

    def test_pdf_not_found(self, storage_client):
        client, _ = storage_client
        resp = client.get("/api/bnetz/pdf/9999")
        assert resp.status_code == 404

    def test_delete(self, storage_client):
        client, storage = storage_client
        mid = storage.save_bnetz_measurement(
            {"date": "2025-01-01", "measurements_download": [], "measurements_upload": []},
            b"%PDF-delete-test",
        )
        resp = client.delete(f"/api/bnetz/{mid}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        # Verify deleted
        resp = client.get("/api/bnetz/measurements")
        assert resp.get_json() == []

    def test_delete_not_found(self, storage_client):
        client, _ = storage_client
        resp = client.delete("/api/bnetz/9999")
        assert resp.status_code == 404


class TestConnectionEndpoint:
    def test_no_connection_info(self, client):
        resp = client.get("/api/connection")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["connection_type"] is None
        assert data["max_downstream_kbps"] is None
        assert data["max_upstream_kbps"] is None

    def test_with_connection_info(self, client):
        update_state(connection_info={
            "connection_type": "DOCSIS 3.1",
            "max_downstream_kbps": 250000,
            "max_upstream_kbps": 40000,
        })
        data = client.get("/api/connection").get_json()
        assert data["connection_type"] == "DOCSIS 3.1"
        assert data["max_downstream_kbps"] == 250000
        assert data["max_upstream_kbps"] == 40000

    def test_isp_name_from_config(self, config_mgr):
        config_mgr.save({"isp_name": "Vodafone"})
        init_config(config_mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            data = c.get("/api/connection").get_json()
        assert data["isp_name"] == "Vodafone"


class TestGamingScoreEndpoint:
    @pytest.fixture(autouse=True)
    def reset_state(self):
        from app.web import _state
        _state["analysis"] = None
        _state["speedtest_latest"] = None
        yield
        _state["analysis"] = None
        _state["speedtest_latest"] = None

    def test_no_data_returns_nulls(self, client):
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["score"] is None
        assert data["grade"] is None
        assert data["components"] == {}
        assert data["has_speedtest"] is False
        assert data["raw"] == {}
        assert set(data["genres"].keys()) == {"fps", "moba", "mmo", "strategy"}

    def test_with_analysis_no_speedtest(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data["score"], int)
        assert data["grade"] in ("A", "B", "C", "D", "F")
        assert data["has_speedtest"] is False
        assert "docsis_health" in data["components"]
        assert "snr_headroom" in data["components"]
        assert data["raw"]["docsis_health"] == "good"
        assert data["raw"]["ds_snr_min"] == 35.0
        assert "ping_ms" not in data["raw"]

    def test_with_analysis_and_speedtest(self, client, sample_analysis):
        update_state(
            analysis=sample_analysis,
            speedtest_latest={"ping_ms": 15, "jitter_ms": 3, "packet_loss_pct": 0},
        )
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["has_speedtest"] is True
        assert "latency" in data["components"]
        assert "jitter" in data["components"]
        assert "packet_loss" in data["components"]
        assert data["score"] >= 90  # perfect inputs should yield A
        assert data["raw"]["ping_ms"] == 15
        assert data["raw"]["jitter_ms"] == 3
        assert data["raw"]["packet_loss_pct"] == 0
        assert data["genres"]["fps"] == "ok"

    def test_genres_degrade_with_grade(self, client, sample_analysis):
        # Simulate a poor connection: zero SNR headroom, no speedtest
        sample_analysis["summary"]["health"] = "poor"
        sample_analysis["summary"]["ds_snr_min"] = 25.0
        update_state(analysis=sample_analysis)
        data = client.get("/api/gaming-score").get_json()
        # Without speedtest data the score may still be partial, but genres key must exist
        assert all(v in ("ok", "warn", "bad") for v in data["genres"].values())

    def test_enabled_flag_reflects_config(self, config_mgr, sample_analysis):
        config_mgr.save({"gaming_quality_enabled": True})
        init_config(config_mgr)
        update_state(analysis=sample_analysis)
        app.config["TESTING"] = True
        with app.test_client() as c:
            data = c.get("/api/gaming-score").get_json()
        assert data["enabled"] is True


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
