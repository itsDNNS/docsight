"""Tests for health, export, and state reset endpoints."""

import json
from app.web import update_state, reset_modem_state, get_state

class TestHealthEndpoint:
    def test_health_waiting(self, client):
        update_state(analysis=None)
        # Reset state
        from app.web import _state
        _state["analysis"] = None
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["docsis_health"] == "waiting"

    def test_health_ok(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["docsis_health"] == "good"

    def test_reset_modem_state_clears_stale_dashboard_data(self, client, sample_analysis):
        update_state(
            analysis=sample_analysis,
            device_info={"model": "Generic Router"},
            connection_info={"connection_type": "generic"},
            speedtest_latest={"download_mbps": 230.5},
        )

        reset_modem_state()
        state = get_state()

        assert state["analysis"] is None
        assert state["device_info"] is None
        assert state["connection_info"] is None
        assert state["last_update"] is None
        assert state["error"] is None
        assert state["speedtest_latest"] == {"download_mbps": 230.5}


class TestExportEndpoint:
    def test_export_no_data(self, client):
        from app.web import _state
        _state["analysis"] = None
        resp = client.get("/api/export")
        assert resp.status_code == 404

    def test_export_returns_markdown(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/api/export")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "DOCSight" in data["text"]
        assert "DOCSIS" in data["text"]
        assert "Vodafone" in data["text"]
