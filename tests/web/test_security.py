"""Tests for security-related web behavior."""

import os
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

