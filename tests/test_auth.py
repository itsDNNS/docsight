"""Tests for web UI authentication."""

import json
import pytest
from app.web import app, update_state, init_config, init_storage
from app.config import ConfigManager
from app.storage import SnapshotStorage


@pytest.fixture
def auth_config(tmp_path):
    """Config with admin_password set."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "admin_password": "secret123"})
    return mgr


@pytest.fixture
def noauth_config(tmp_path):
    """Config without admin_password."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test"})
    return mgr


@pytest.fixture
def storage(tmp_path):
    """Provide a real SnapshotStorage for token tests."""
    return SnapshotStorage(str(tmp_path / "test_auth.db"), max_days=7)


@pytest.fixture
def auth_client(auth_config):
    init_config(auth_config)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_client_with_storage(auth_config, storage):
    init_config(auth_config)
    init_storage(storage)
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
        assert resp.status_code == 401

    def test_api_snapshots_requires_auth(self, auth_client):
        resp = auth_client.get("/api/snapshots")
        assert resp.status_code == 401

    def test_api_export_requires_auth(self, auth_client):
        resp = auth_client.get("/api/export")
        assert resp.status_code == 401

    def test_api_trends_requires_auth(self, auth_client):
        resp = auth_client.get("/api/trends")
        assert resp.status_code == 401

    def test_password_hashed_not_plaintext(self, auth_config):
        stored = auth_config.get("admin_password")
        assert stored != "secret123"
        assert stored.startswith(("scrypt:", "pbkdf2:"))


class TestApiTokenAuth:
    """Tests for API token (Bearer) authentication."""

    def _login(self, client):
        client.post("/login", data={"password": "secret123"})

    def test_create_token_requires_session(self, auth_client_with_storage):
        """Token creation without session returns 401."""
        resp = auth_client_with_storage.post(
            "/api/tokens",
            data=json.dumps({"name": "test"}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_create_and_use_bearer_token(self, auth_client_with_storage):
        """Create a token via session, then use it for Bearer auth."""
        self._login(auth_client_with_storage)
        resp = auth_client_with_storage.post(
            "/api/tokens",
            data=json.dumps({"name": "ci-test"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["token"].startswith("dsk_")
        token = data["token"]

        # Use the token for an API request
        resp = auth_client_with_storage.get(
            "/api/snapshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_invalid_token_returns_401(self, auth_client_with_storage):
        """An invalid Bearer token returns 401 JSON."""
        resp = auth_client_with_storage.get(
            "/api/snapshots",
            headers={"Authorization": "Bearer dsk_invalid_garbage"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert "error" in data

    def test_revoked_token_rejected(self, auth_client_with_storage):
        """A revoked token is no longer accepted."""
        self._login(auth_client_with_storage)
        resp = auth_client_with_storage.post(
            "/api/tokens",
            data=json.dumps({"name": "to-revoke"}),
            content_type="application/json",
        )
        token = resp.get_json()["token"]
        token_id = resp.get_json()["id"]

        # Revoke it
        resp = auth_client_with_storage.delete(f"/api/tokens/{token_id}")
        assert resp.status_code == 200

        # Log out so session doesn't mask the token check
        auth_client_with_storage.get("/logout")

        # Try to use the revoked token
        resp = auth_client_with_storage.get(
            "/api/snapshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_token_list_shows_prefix_not_hash(self, auth_client_with_storage):
        """Token list returns prefix, not the hash."""
        self._login(auth_client_with_storage)
        auth_client_with_storage.post(
            "/api/tokens",
            data=json.dumps({"name": "list-test"}),
            content_type="application/json",
        )
        resp = auth_client_with_storage.get("/api/tokens")
        assert resp.status_code == 200
        tokens = resp.get_json()["tokens"]
        assert len(tokens) >= 1
        for tk in tokens:
            assert "token_hash" not in tk
            assert tk["token_prefix"].startswith("dsk_")

    def test_token_cannot_create_tokens(self, auth_client_with_storage):
        """A Bearer token cannot create new tokens (session-only)."""
        self._login(auth_client_with_storage)
        resp = auth_client_with_storage.post(
            "/api/tokens",
            data=json.dumps({"name": "parent"}),
            content_type="application/json",
        )
        token = resp.get_json()["token"]

        # Log out, then try to create a token with Bearer auth
        auth_client_with_storage.get("/logout")
        resp = auth_client_with_storage.post(
            "/api/tokens",
            data=json.dumps({"name": "child"}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_api_routes_return_401_not_302(self, auth_client_with_storage):
        """API paths return 401 JSON, not 302 redirect."""
        resp = auth_client_with_storage.get("/api/snapshots")
        assert resp.status_code == 401
        data = resp.get_json()
        assert "error" in data

    def test_health_stays_public(self, auth_client_with_storage):
        """/health remains accessible without any auth."""
        update_state(analysis={
            "summary": {"ds_total": 1, "us_total": 1, "ds_power_min": 0,
                        "ds_power_max": 0, "ds_power_avg": 0, "us_power_min": 0,
                        "us_power_max": 0, "us_power_avg": 0, "ds_snr_min": 0,
                        "ds_snr_avg": 0, "ds_correctable_errors": 0,
                        "ds_uncorrectable_errors": 0, "health": "good",
                        "health_issues": []},
            "ds_channels": [], "us_channels": [],
        })
        resp = auth_client_with_storage.get("/health")
        assert resp.status_code == 200
