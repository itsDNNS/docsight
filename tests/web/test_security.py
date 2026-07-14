"""Tests for security-related web behavior."""

import os
from datetime import timedelta

import pytest

from app.web import app, update_state, init_config
from app.config import ConfigManager

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


class TestSessionLifetime:
    def test_default_is_thirty_days(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SESSION_LIFETIME_DAYS", raising=False)
        init_config(ConfigManager(str(tmp_path / "default_lifetime")))
        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=30)

    def test_operator_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_LIFETIME_DAYS", "45")
        init_config(ConfigManager(str(tmp_path / "custom_lifetime")))
        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=45)

    def test_init_config_preserves_reverse_proxy_secure_cookie(self, tmp_path, monkeypatch):
        monkeypatch.setitem(app.config, "SESSION_COOKIE_SECURE", True)

        init_config(ConfigManager(str(tmp_path / "secure_cookie")))

        assert app.config["SESSION_COOKIE_SECURE"] is True

    @pytest.mark.parametrize(
        ("configured", "expected_days"),
        [
            ("not-a-number", 30),
            ("", 30),
            ("0", 1),
            ("-10", 1),
            ("999999999999999999999999", 365),
        ],
    )
    def test_invalid_and_unsafe_values_are_defaulted_or_clamped(
        self, tmp_path, monkeypatch, configured, expected_days
    ):
        monkeypatch.setenv("SESSION_LIFETIME_DAYS", configured)
        init_config(ConfigManager(str(tmp_path / f"lifetime_{expected_days}_{configured}")))
        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=expected_days)
