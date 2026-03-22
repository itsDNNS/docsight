"""Tests for Connection Monitor traceroute API routes."""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.modules.connection_monitor.routes import bp
from app.modules.connection_monitor.storage import ConnectionMonitorStorage
from app.modules.connection_monitor.traceroute_probe import TracerouteHop, TracerouteResult


def _make_traceroute_result(hops=None, reached=True, fingerprint="abc123"):
    if hops is None:
        hops = [
            TracerouteHop(hop_index=1, hop_ip="10.0.0.1", hop_host="gw.local", latency_ms=1.2, probes_responded=3),
            TracerouteHop(hop_index=2, hop_ip="192.168.1.1", hop_host=None, latency_ms=5.4, probes_responded=3),
            TracerouteHop(hop_index=3, hop_ip="8.8.8.8", hop_host="dns.google", latency_ms=12.1, probes_responded=3),
        ]
    return TracerouteResult(hops=hops, reached_target=reached, route_fingerprint=fingerprint)


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

    mock_tr_probe = MagicMock()
    mock_tr_probe.run.return_value = _make_traceroute_result()

    import app.modules.connection_monitor.routes as routes_mod
    routes_mod._storage = storage
    routes_mod._traceroute_probe = mock_tr_probe

    with patch("app.modules.connection_monitor.routes._get_probe_engine", return_value=mock_probe), \
         patch("app.modules.connection_monitor.routes._get_tz", return_value="UTC"):
        yield app, storage, mock_tr_probe

    routes_mod._storage = None
    routes_mod._traceroute_probe = None


@pytest.fixture
def client(app):
    flask_app, storage, mock_tr_probe = app
    return flask_app.test_client(), storage, mock_tr_probe


def _auth_session(c):
    """Set authenticated session for protected routes."""
    with c.session_transaction() as sess:
        sess["authenticated"] = True


class TestManualTraceroute:
    def test_manual_traceroute_success(self, client):
        c, storage, mock_tr_probe = client
        _auth_session(c)
        tid = storage.create_target("Test", "8.8.8.8")
        resp = c.post(f"/api/connection-monitor/traceroute/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "trace_id" in data
        assert data["trigger_reason"] == "manual"
        assert data["reached_target"] is True
        assert data["hop_count"] == 3
        assert data["route_fingerprint"] == "abc123"
        assert len(data["hops"]) == 3
        assert data["hops"][0]["hop_ip"] == "10.0.0.1"
        assert data["hops"][0]["hop_host"] == "gw.local"
        assert data["hops"][0]["latency_ms"] == 1.2
        assert data["hops"][0]["probes_responded"] == 3
        assert "timestamp" in data
        mock_tr_probe.run.assert_called_once_with("8.8.8.8")

    def test_manual_traceroute_invalid_target(self, client):
        c, storage, _ = client
        _auth_session(c)
        resp = c.post("/api/connection-monitor/traceroute/9999")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data

    def test_manual_traceroute_requires_auth(self, app):
        flask_app, storage, _ = app
        tid = storage.create_target("Test", "8.8.8.8")
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda key, default=None: {
            "admin_password": "hashed_pw",
        }.get(key, default)
        with patch("app.web._config_manager", mock_cfg):
            c = flask_app.test_client()
            resp = c.post(f"/api/connection-monitor/traceroute/{tid}")
            assert resp.status_code == 401


class TestGetTraces:
    def test_get_traces_for_target(self, client):
        c, storage, _ = client
        _auth_session(c)
        tid = storage.create_target("Test", "8.8.8.8")
        now = time.time()
        storage.save_trace(
            target_id=tid, timestamp=now, trigger_reason="manual",
            hops=[{"hop_index": 1, "hop_ip": "10.0.0.1", "latency_ms": 1.2, "probes_responded": 3}],
            route_fingerprint="fp1", reached_target=True,
        )
        storage.save_trace(
            target_id=tid, timestamp=now - 60, trigger_reason="outage",
            hops=[{"hop_index": 1, "hop_ip": "10.0.0.1", "latency_ms": 2.0, "probes_responded": 3}],
            route_fingerprint="fp2", reached_target=False,
        )
        resp = c.get(f"/api/connection-monitor/traces/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        # Returned newest-first
        assert data[0]["trigger_reason"] == "manual"
        assert data[1]["trigger_reason"] == "outage"
        # Timestamps are ISO strings
        assert data[0]["timestamp"].endswith("Z")

    def test_get_traces_empty(self, client):
        c, storage, _ = client
        _auth_session(c)
        tid = storage.create_target("Test", "8.8.8.8")
        resp = c.get(f"/api/connection-monitor/traces/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []

    def test_traces_time_range_filter(self, client):
        c, storage, _ = client
        _auth_session(c)
        tid = storage.create_target("Test", "8.8.8.8")
        now = time.time()
        storage.save_trace(
            target_id=tid, timestamp=now - 3600, trigger_reason="outage",
            hops=[{"hop_index": 1, "hop_ip": "10.0.0.1", "latency_ms": 1.0, "probes_responded": 3}],
            route_fingerprint="fp_old", reached_target=True,
        )
        storage.save_trace(
            target_id=tid, timestamp=now - 60, trigger_reason="manual",
            hops=[{"hop_index": 1, "hop_ip": "10.0.0.1", "latency_ms": 2.0, "probes_responded": 3}],
            route_fingerprint="fp_new", reached_target=True,
        )
        # Filter to only the recent trace
        resp = c.get(f"/api/connection-monitor/traces/{tid}?start={now - 300}&end={now}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["route_fingerprint"] == "fp_new"


class TestGetTraceDetail:
    def test_get_trace_detail(self, client):
        c, storage, _ = client
        _auth_session(c)
        tid = storage.create_target("Test", "8.8.8.8")
        now = time.time()
        trace_id = storage.save_trace(
            target_id=tid, timestamp=now, trigger_reason="manual",
            hops=[
                {"hop_index": 1, "hop_ip": "10.0.0.1", "hop_host": "gw.local",
                 "latency_ms": 1.2, "probes_responded": 3},
                {"hop_index": 2, "hop_ip": "8.8.8.8", "hop_host": "dns.google",
                 "latency_ms": 12.0, "probes_responded": 3},
            ],
            route_fingerprint="fp123", reached_target=True,
        )
        resp = c.get(f"/api/connection-monitor/trace/{trace_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == trace_id
        assert data["target_id"] == tid
        assert data["trigger_reason"] == "manual"
        assert data["reached_target"] == 1
        assert data["route_fingerprint"] == "fp123"
        assert data["timestamp"].endswith("Z")
        assert len(data["hops"]) == 2
        assert data["hops"][0]["hop_ip"] == "10.0.0.1"
        assert data["hops"][0]["hop_host"] == "gw.local"
        assert data["hops"][1]["hop_ip"] == "8.8.8.8"

    def test_get_trace_detail_not_found(self, client):
        c, _, _ = client
        _auth_session(c)
        resp = c.get("/api/connection-monitor/trace/9999")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
