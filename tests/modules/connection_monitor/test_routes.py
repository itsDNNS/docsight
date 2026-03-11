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

    def test_create_target_without_host(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "New target"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == 1

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
