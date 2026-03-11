"""Tests for Connection Monitor API routes."""

import csv
import io
import time
from unittest.mock import MagicMock, patch
import pytest

from app.modules.connection_monitor.routes import bp
from app.modules.connection_monitor.storage import ConnectionMonitorStorage


@pytest.fixture
def app(tmp_path):
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(bp)

    db_path = str(tmp_path / "test_cm.db")
    storage = ConnectionMonitorStorage(db_path)

    mock_probe = MagicMock()
    mock_probe.capability_info.return_value = {"method": "tcp", "reason": "no ICMP permission"}

    # Set the module-level lazy storage directly
    import app.modules.connection_monitor.routes as routes_mod
    routes_mod._storage = storage

    with patch("app.modules.connection_monitor.routes._get_probe_engine", return_value=mock_probe):
        yield app, storage

    # Clean up
    routes_mod._storage = None


@pytest.fixture
def client(app):
    flask_app, storage = app
    return flask_app.test_client(), storage


def _auth_session(c):
    """Set authenticated session for protected routes."""
    with c.session_transaction() as sess:
        sess["authenticated"] = True


class TestTargetsAPI:
    def test_get_empty_targets(self, client):
        c, _ = client
        resp = c.get("/api/connection-monitor/targets")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_create_target(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "Test", "host": "1.1.1.1"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == 1

    def test_create_target_without_host_is_disabled(self, client):
        c, storage = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "New target"},
        )
        assert resp.status_code == 201
        target = storage.get_target(resp.get_json()["id"])
        assert not target["enabled"]

    def test_create_target_with_host_is_enabled(self, client):
        c, storage = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "Test", "host": "1.1.1.1"},
        )
        assert resp.status_code == 201
        target = storage.get_target(resp.get_json()["id"])
        assert target["enabled"]

    def test_update_host_auto_enables_target(self, client):
        c, storage = client
        _auth_session(c)
        # Create disabled target (no host)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "New target"},
        )
        tid = resp.get_json()["id"]
        assert not storage.get_target(tid)["enabled"]
        # Update with host - should auto-enable
        resp = c.put(
            f"/api/connection-monitor/targets/{tid}",
            json={"host": "8.8.8.8"},
        )
        assert resp.status_code == 200
        assert storage.get_target(tid)["enabled"]

    def test_update_target(self, client):
        c, storage = client
        storage.create_target("Test", "1.1.1.1")
        _auth_session(c)
        resp = c.put(
            "/api/connection-monitor/targets/1",
            json={"label": "Updated"},
        )
        assert resp.status_code == 200

    def test_delete_target(self, client):
        c, storage = client
        storage.create_target("Test", "1.1.1.1")
        _auth_session(c)
        resp = c.delete("/api/connection-monitor/targets/1")
        assert resp.status_code == 200


class TestSamplesAPI:
    def test_get_samples(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        storage.save_samples([
            {"target_id": tid, "timestamp": time.time(), "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

    def test_get_samples_with_time_range(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 200, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 50, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 100}")
        data = resp.get_json()
        assert len(data) == 1


class TestSummaryAPI:
    def test_get_summary(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get("/api/connection-monitor/summary")
        assert resp.status_code == 200


class TestOutagesAPI:
    def test_get_outages(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [{"target_id": tid, "timestamp": now - 10, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"}]
        for i in range(6):
            samples.append({"target_id": tid, "timestamp": now - 9 + i, "latency_ms": None, "timeout": True, "probe_method": "tcp"})
        samples.append({"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"})
        storage.save_samples(samples)
        resp = c.get(f"/api/connection-monitor/outages/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1


class TestExportAPI:
    def test_csv_export(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/export/{tid}")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = resp.data.decode()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 2  # header + 1 data row


class TestCapabilityAPI:
    def test_capability(self, client):
        c, _ = client
        resp = c.get("/api/connection-monitor/capability")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["method"] == "tcp"


class TestAuthProtection:
    """Verify all endpoints return 401 when auth is enabled but not provided."""

    @pytest.fixture
    def auth_client(self, app):
        """Client with auth enforcement enabled via a mock config manager."""
        flask_app, storage = app
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda key, default=None: {
            "admin_password": "hashed_pw",
        }.get(key, default)
        with patch("app.web._config_manager", mock_cfg):
            yield flask_app.test_client(), storage

    def test_targets_get_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/targets").status_code == 401

    def test_targets_post_requires_auth(self, auth_client):
        c, _ = auth_client
        resp = c.post("/api/connection-monitor/targets", json={"label": "X", "host": "1.1.1.1"})
        assert resp.status_code == 401

    def test_samples_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/samples/1").status_code == 401

    def test_summary_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/summary").status_code == 401

    def test_outages_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/outages/1").status_code == 401

    def test_export_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/export/1").status_code == 401

    def test_capability_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/capability").status_code == 401

    def test_authenticated_request_passes(self, auth_client):
        c, _ = auth_client
        _auth_session(c)
        assert c.get("/api/connection-monitor/targets").status_code == 200
