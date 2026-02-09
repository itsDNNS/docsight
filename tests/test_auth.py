"""Tests for web UI authentication."""

import json
import pytest
from app.web import app, update_state, init_config, init_storage
from app.config import ConfigManager


@pytest.fixture
def auth_config(tmp_path):
    """Config with admin_password set."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"fritz_password": "test", "admin_password": "secret123"})
    return mgr


@pytest.fixture
def noauth_config(tmp_path):
    """Config without admin_password."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"fritz_password": "test"})
    return mgr


@pytest.fixture
def auth_client(auth_config):
    init_config(auth_config)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def noauth_client(noauth_config):
    init_config(noauth_config)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestAuthDisabled:
    def test_index_accessible(self, noauth_client):
        update_state(analysis={"summary": {"ds_total": 1, "us_total": 1, "ds_power_min": 0, "ds_power_max": 0, "ds_power_avg": 0, "us_power_min": 0, "us_power_max": 0, "us_power_avg": 0, "ds_snr_min": 0, "ds_snr_avg": 0, "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0, "health": "good", "health_issues": []}, "ds_channels": [], "us_channels": []})
        resp = noauth_client.get("/")
        assert resp.status_code == 200

    def test_settings_accessible(self, noauth_client):
        resp = noauth_client.get("/settings")
        assert resp.status_code == 200

    def test_login_redirects_to_index(self, noauth_client):
        resp = noauth_client.get("/login")
        assert resp.status_code == 302


class TestAuthEnabled:
    def test_index_redirects_to_login(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_settings_redirects_to_login(self, auth_client):
        resp = auth_client.get("/settings")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_health_always_accessible(self, auth_client):
        update_state(analysis={"summary": {"ds_total": 1, "us_total": 1, "ds_power_min": 0, "ds_power_max": 0, "ds_power_avg": 0, "us_power_min": 0, "us_power_max": 0, "us_power_avg": 0, "ds_snr_min": 0, "ds_snr_avg": 0, "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0, "health": "good", "health_issues": []}, "ds_channels": [], "us_channels": []})
        resp = auth_client.get("/health")
        assert resp.status_code == 200

    def test_login_page_renders(self, auth_client):
        resp = auth_client.get("/login")
        assert resp.status_code == 200
        assert b"DOCSight" in resp.data

    def test_login_wrong_password(self, auth_client):
        resp = auth_client.post("/login", data={"password": "wrong"})
        assert resp.status_code == 200  # stays on login page

    def test_login_correct_password(self, auth_client):
        resp = auth_client.post("/login", data={"password": "secret123"}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_session_persists(self, auth_client):
        auth_client.post("/login", data={"password": "secret123"})
        update_state(analysis={"summary": {"ds_total": 1, "us_total": 1, "ds_power_min": 0, "ds_power_max": 0, "ds_power_avg": 0, "us_power_min": 0, "us_power_max": 0, "us_power_avg": 0, "ds_snr_min": 0, "ds_snr_avg": 0, "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0, "health": "good", "health_issues": []}, "ds_channels": [], "us_channels": []})
        resp = auth_client.get("/")
        assert resp.status_code == 200

    def test_logout(self, auth_client):
        auth_client.post("/login", data={"password": "secret123"})
        auth_client.get("/logout")
        resp = auth_client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_api_config_requires_auth(self, auth_client):
        resp = auth_client.post(
            "/api/config",
            data=json.dumps({"poll_interval": 120}),
            content_type="application/json",
        )
        assert resp.status_code == 302

    def test_api_calendar_requires_auth(self, auth_client):
        resp = auth_client.get("/api/calendar")
        assert resp.status_code == 302

    def test_api_snapshots_requires_auth(self, auth_client):
        resp = auth_client.get("/api/snapshots")
        assert resp.status_code == 302

    def test_api_export_requires_auth(self, auth_client):
        resp = auth_client.get("/api/export")
        assert resp.status_code == 302

    def test_api_trends_requires_auth(self, auth_client):
        resp = auth_client.get("/api/trends")
        assert resp.status_code == 302

    def test_password_hashed_not_plaintext(self, auth_config):
        stored = auth_config.get("admin_password")
        assert stored != "secret123"
        assert stored.startswith(("scrypt:", "pbkdf2:"))
