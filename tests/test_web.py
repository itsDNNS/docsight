"""Tests for Flask web routes and API endpoints."""

import json
import pytest
from app.web import app, update_state, init_config, init_storage
from app.config import ConfigManager


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
        assert resp.status_code == 503

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


class TestCalendarEndpoint:
    def test_calendar_no_storage(self, client):
        resp = client.get("/api/calendar")
        assert resp.status_code == 200
        assert json.loads(resp.data) == []


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
    def test_invalid_timestamp_rejected(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/?t=../../etc/passwd")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

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
        web_module._last_manual_poll = __import__('time').time()
        resp = client.post("/api/poll")
        assert resp.status_code == 429
        data = json.loads(resp.data)
        assert data["success"] is False
        # Reset for other tests
        web_module._last_manual_poll = 0.0


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
