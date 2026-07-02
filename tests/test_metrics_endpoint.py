"""Integration tests for the GET /metrics HTTP endpoint."""

import pytest
import app.web as _web
from app.web import app, update_state, init_config, init_storage
from app.config import ConfigManager
from app.storage import SnapshotStorage


@pytest.fixture(autouse=True)
def reset_web_state():
    """Reset shared web state before and after each test to prevent state pollution."""
    _web._state["analysis"] = None
    _web._state["last_update"] = None
    _web._state["error"] = None
    _web._state["connection_info"] = None
    _web._state["device_info"] = None
    _web._state["speedtest_latest"] = None
    yield
    _web._state["analysis"] = None
    _web._state["last_update"] = None
    _web._state["error"] = None
    _web._state["connection_info"] = None
    _web._state["device_info"] = None
    _web._state["speedtest_latest"] = None


@pytest.fixture
def noauth_config(tmp_path):
    """Config without admin_password."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
    return mgr


@pytest.fixture
def auth_config(tmp_path):
    """Config with admin_password set."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "admin_password": "secret123"})
    return mgr


@pytest.fixture
def protected_metrics_config(tmp_path):
    """Config with token-protected metrics enabled."""
    mgr = ConfigManager(str(tmp_path / "protected-data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "metrics_require_token": True})
    return mgr


@pytest.fixture
def metrics_client(noauth_config):
    """Flask test client with no authentication configured."""
    init_config(noauth_config)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_client(auth_config):
    """Flask test client with authentication configured."""
    init_config(auth_config)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def protected_metrics_client(protected_metrics_config, tmp_path):
    """Flask test client with token-protected metrics enabled."""
    storage = SnapshotStorage(str(tmp_path / "metrics-tokens.db"), max_days=7)
    init_config(protected_metrics_config)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        client._docsight_storage = storage
        yield client


@pytest.fixture
def metrics_client_with_data(metrics_client):
    """Flask test client with realistic modem analysis state populated."""
    update_state(
        analysis={
            "summary": {
                "ds_total": 2,
                "us_total": 1,
                "ds_power_min": 1.0,
                "ds_power_max": 5.0,
                "ds_power_avg": 3.0,
                "us_power_min": 40.0,
                "us_power_max": 40.0,
                "us_power_avg": 40.0,
                "ds_snr_min": 35.0,
                "ds_snr_avg": 37.0,
                "ds_correctable_errors": 100,
                "ds_uncorrectable_errors": 0,
                "health": "good",
                "health_issues": [],
            },
            "ds_channels": [
                {
                    "channel_id": 1,
                    "power": 1.5,
                    "snr": 35.0,
                    "correctable_errors": 50,
                    "uncorrectable_errors": 0,
                    "modulation": "256QAM",
                },
                {
                    "channel_id": 2,
                    "power": 4.5,
                    "snr": 39.0,
                    "correctable_errors": 50,
                    "uncorrectable_errors": 0,
                    "modulation": "256QAM",
                },
            ],
            "us_channels": [
                {
                    "channel_id": 1,
                    "power": 40.0,
                    "modulation": "64QAM",
                },
            ],
        },
        device_info={"model": "TestModem", "sw_version": "1.0.0", "uptime_seconds": 86400},
        connection_info={"max_downstream_kbps": 500000, "max_upstream_kbps": 50000},
    )
    return metrics_client


class TestMetricsEndpoint:
    def test_returns_200(self, metrics_client):
        """GET /metrics returns HTTP 200."""
        resp = metrics_client.get("/metrics")
        assert resp.status_code == 200

    def test_content_type(self, metrics_client):
        """GET /metrics Content-Type is Prometheus text format."""
        resp = metrics_client.get("/metrics")
        assert resp.content_type == "text/plain; version=0.0.4; charset=utf-8"

    def test_no_data_returns_health_unknown(self, metrics_client):
        """Without analysis data, response contains health_status 3 (unknown)."""
        update_state()  # reset to no analysis
        resp = metrics_client.get("/metrics")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "docsight_health_status 4" in body

    def test_with_data_returns_channel_metrics(self, metrics_client_with_data):
        """With analysis populated, response contains per-channel metrics and health_status 0."""
        resp = metrics_client_with_data.get("/metrics")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "docsight_downstream_power_dbmv" in body
        assert "docsight_upstream_power_dbmv" in body
        assert "docsight_health_status 0" in body

    def test_accessible_without_auth(self, auth_client):
        """GET /metrics works without authentication even when admin_password is set."""
        # Do NOT log in — just request /metrics directly
        resp = auth_client.get("/metrics")
        assert resp.status_code == 200

    def test_post_not_allowed(self, metrics_client):
        """POST /metrics returns 405 Method Not Allowed."""
        resp = metrics_client.post("/metrics")
        assert resp.status_code == 405

    def test_contains_help_and_type_comments(self, metrics_client):
        """Response body contains Prometheus # HELP and # TYPE comment lines."""
        resp = metrics_client.get("/metrics")
        body = resp.data.decode("utf-8")
        assert "# HELP" in body
        assert "# TYPE" in body

    def test_last_poll_timestamp_present(self, metrics_client):
        """Response contains docsight_last_poll_timestamp_seconds metric."""
        resp = metrics_client.get("/metrics")
        body = resp.data.decode("utf-8")
        assert "docsight_last_poll_timestamp_seconds" in body

    def test_token_protection_rejects_missing_token(self, protected_metrics_client):
        resp = protected_metrics_client.get("/metrics")
        assert resp.status_code == 401
        assert b"Authentication required" in resp.data

    def test_token_protection_rejects_invalid_token(self, protected_metrics_client):
        resp = protected_metrics_client.get("/metrics", headers={"Authorization": "Bearer dsk_invalid"})
        assert resp.status_code == 401

    def test_token_protection_allows_valid_token(self, protected_metrics_client):
        _, token = protected_metrics_client._docsight_storage.create_api_token("prometheus")
        resp = protected_metrics_client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.content_type == "text/plain; version=0.0.4; charset=utf-8"
