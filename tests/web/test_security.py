"""Tests for security-related web behavior."""

import os
from datetime import timedelta

import pytest

from app.web import update_state
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
    def test_session_key_file_created(self, tmp_path, make_app):
        data_dir = str(tmp_path / "data_sk")
        mgr = ConfigManager(data_dir)
        make_app(config_manager=mgr)
        import os
        assert os.path.exists(os.path.join(data_dir, ".session_key"))

    def test_session_key_persisted(self, tmp_path, make_app):
        data_dir = str(tmp_path / "data_sk2")
        mgr = ConfigManager(data_dir)
        key1 = make_app(config_manager=mgr).secret_key
        assert make_app(config_manager=mgr).secret_key == key1


class TestSessionLifetime:
    def test_default_is_thirty_days(self, tmp_path, make_app):
        app = make_app(config_manager=ConfigManager(str(tmp_path / "default_lifetime")), environ={})
        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=30)

    def test_operator_override(self, tmp_path, make_app):
        app = make_app(config_manager=ConfigManager(str(tmp_path / "custom_lifetime")), environ={"SESSION_LIFETIME_DAYS": "45"})
        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=45)

    def test_factory_enables_reverse_proxy_secure_cookie(self, tmp_path, make_app):
        app = make_app(config_manager=ConfigManager(str(tmp_path / "secure_cookie")), environ={"REVERSE_PROXY": "1"})
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
        self, tmp_path, make_app, configured, expected_days
    ):
        app = make_app(
            config_manager=ConfigManager(str(tmp_path / f"lifetime_{expected_days}_{configured}")),
            environ={"SESSION_LIFETIME_DAYS": configured},
        )
        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=expected_days)
