"""Tests for web UI authentication."""

import json
import re
import sqlite3
import pytest
from werkzeug.security import generate_password_hash
from app.web import app, update_state, init_config, init_storage, _login_attempts, _LOGIN_MAX_TRACKED_IPS
from app.config import ConfigManager
from app.storage import SnapshotStorage


def _login_csrf(client):
    resp = client.get("/login")
    match = re.search(rb'name="csrf_token" value="([^"]+)"', resp.data)
    assert match, "login form should include a CSRF token"
    return match.group(1).decode("utf-8")


@pytest.fixture
def auth_config(tmp_path):
    """Config with admin_password set."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "admin_password": "secret123"})
    return mgr


@pytest.fixture
def noauth_config(tmp_path):
    """Config without admin_password."""
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
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
        resp = auth_client.post("/login", data={"password": "wrong", "csrf_token": _login_csrf(auth_client)})
        assert resp.status_code == 200  # stays on login page

    def test_login_correct_password(self, auth_client):
        resp = auth_client.post("/login", data={"password": "secret123", "csrf_token": _login_csrf(auth_client)}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_session_persists(self, auth_client):
        auth_client.post("/login", data={"password": "secret123", "csrf_token": _login_csrf(auth_client)})
        update_state(analysis={"summary": {"ds_total": 1, "us_total": 1, "ds_power_min": 0, "ds_power_max": 0, "ds_power_avg": 0, "us_power_min": 0, "us_power_max": 0, "us_power_avg": 0, "ds_snr_min": 0, "ds_snr_avg": 0, "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0, "health": "good", "health_issues": []}, "ds_channels": [], "us_channels": []})
        resp = auth_client.get("/")
        assert resp.status_code == 200

    def test_logout(self, auth_client):
        auth_client.post("/login", data={"password": "secret123", "csrf_token": _login_csrf(auth_client)})
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

    def test_login_rejects_missing_csrf_token(self, auth_client):
        resp = auth_client.post("/login", data={"password": "secret123"})
        assert resp.status_code == 400

    def test_login_rejects_non_ascii_csrf_token_without_crashing(self, auth_client):
        resp = auth_client.post("/login", data={"password": "secret123", "csrf_token": "ü"})
        assert resp.status_code == 400

    def test_login_attempt_tracking_is_bounded(self):
        _login_attempts.clear()
        for idx in range(_LOGIN_MAX_TRACKED_IPS + 25):
            _login_attempts[f"198.51.100.{idx}"] = [idx + 1.0]
        from app.web import _prune_login_attempts
        _prune_login_attempts(now=10_000.0)
        assert len(_login_attempts) <= _LOGIN_MAX_TRACKED_IPS


class TestApiTokenAuth:
    """Tests for API token (Bearer) authentication."""

    def _login(self, client):
        client.post("/login", data={"password": "secret123", "csrf_token": _login_csrf(client)})

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
            headers={"Authorization": "Bearer dsk_nope"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert "error" in data

    def test_token_validation_filters_by_prefix_before_hash_check(self, storage, monkeypatch):
        """Token validation should hash-check only rows with the presented token prefix."""
        bearer = "dsk_match1"
        checked_hashes = []

        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, revoked) VALUES (?, ?, ?, ?, 0)",
                ("wrong-prefix", "wrong-prefix-hash", "dsk_nope", "2026-01-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, revoked) VALUES (?, ?, ?, ?, 0)",
                ("match", "match-hash", bearer[:8], "2026-01-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, revoked) VALUES (?, ?, ?, ?, 1)",
                ("revoked-match", "revoked-hash", bearer[:8], "2026-01-01T00:00:00Z"),
            )

        def fake_check_password_hash(stored_hash, presented_token):
            checked_hashes.append(stored_hash)
            assert presented_token == bearer
            return stored_hash == "match-hash"

        monkeypatch.setattr("app.storage.tokens.check_password_hash", fake_check_password_hash)

        token_info = storage.validate_api_token(bearer)

        assert token_info is not None
        assert token_info["name"] == "match"
        assert checked_hashes == ["match-hash"]

    def test_token_validation_throttles_recent_last_used_writes(self, storage, monkeypatch):
        """A frequently used token remains valid without writing last_used_at every request."""
        bearer = "dsk_throt1"
        previous_last_used = "2026-01-01T00:00:30Z"
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, last_used_at, revoked) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (
                    "recent",
                    generate_password_hash(bearer),
                    bearer[:8],
                    "2026-01-01T00:00:00Z",
                    previous_last_used,
                ),
            )

        monkeypatch.setattr("app.storage.tokens.utc_now", lambda: "2026-01-01T00:01:00Z")

        token_info = storage.validate_api_token(bearer)

        assert token_info is not None
        with sqlite3.connect(storage.db_path) as conn:
            last_used_at = conn.execute(
                "SELECT last_used_at FROM api_tokens WHERE token_prefix = ?", (bearer[:8],)
            ).fetchone()[0]
        assert last_used_at == previous_last_used

    def test_token_validation_updates_stale_last_used(self, storage, monkeypatch):
        """last_used_at still refreshes after the throttle window."""
        bearer = "dsk_stale1"
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, last_used_at, revoked) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (
                    "stale",
                    generate_password_hash(bearer),
                    bearer[:8],
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )

        monkeypatch.setattr("app.storage.tokens.utc_now", lambda: "2026-01-01T00:01:01Z")

        assert storage.validate_api_token(bearer) is not None
        with sqlite3.connect(storage.db_path) as conn:
            last_used_at = conn.execute(
                "SELECT last_used_at FROM api_tokens WHERE token_prefix = ?", (bearer[:8],)
            ).fetchone()[0]
        assert last_used_at == "2026-01-01T00:01:01Z"

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
