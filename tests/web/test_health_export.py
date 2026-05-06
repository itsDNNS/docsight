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

    def test_export_handles_unsupported_error_counters(self, client, sample_analysis):
        sample_analysis["summary"].update({
            "errors_supported": False,
            "ds_correctable_errors": None,
            "ds_uncorrectable_errors": None,
        })
        update_state(analysis=sample_analysis)

        resp = client.get("/api/export")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "| DS Correctable Errors | N/A |" in data["text"]
        assert "| DS Uncorrectable Errors | N/A |" in data["text"]
        assert "DOCSight" in data["text"]
        assert "DOCSIS" in data["text"]
        assert "Vodafone" in data["text"]


class TestExportUnsupportedLegacyCounters:
    def test_export_treats_legacy_unsupported_zero_error_counters_as_unavailable(self):
        from app.blueprints.data_bp import _format_error_count, _summary_error_count

        summary = {
            "errors_supported": False,
            "ds_correctable_errors": 0,
            "ds_uncorrectable_errors": 0,
        }

        assert _format_error_count(_summary_error_count(summary, "ds_correctable_errors")) == "N/A"
        assert _format_error_count(_summary_error_count(summary, "ds_uncorrectable_errors")) == "N/A"
