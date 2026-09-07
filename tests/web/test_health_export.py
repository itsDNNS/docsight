"""Tests for health, export, and state reset endpoints."""

import json
from unittest.mock import Mock, patch

import pytest
from app.runtime import current_runtime

class TestHealthEndpoint:
    def test_health_waiting(self, client):
        current_runtime().update_state(analysis=None)
        # Reset state
        current_runtime().reset_modem_state()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["docsis_health"] == "waiting"

    def test_health_ok(self, client, sample_analysis):
        current_runtime().update_state(analysis=sample_analysis)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["docsis_health"] == "good"

    def test_reset_modem_state_clears_stale_dashboard_data(self, client, sample_analysis):
        current_runtime().update_state(
            analysis=sample_analysis,
            device_info={"model": "Generic Router"},
            connection_info={"connection_type": "generic"},
            speedtest_latest={"download_mbps": 230.5},
        )

        current_runtime().reset_modem_state()
        state = current_runtime().get_state()

        assert state["analysis"] is None
        assert state["device_info"] is None
        assert state["connection_info"] is None
        assert state["last_update"] is None
        assert state["error"] is None
        assert state["speedtest_latest"] == {"download_mbps": 230.5}


class TestExportEndpoint:
    @pytest.mark.parametrize("mode,hours,limit", [("full", 48, 10), ("update", 6, 3)])
    def test_export_keeps_speedtests_without_inferred_modem_health(
        self, client, sample_analysis, mode, hours, limit
    ):
        current_runtime().update_state(analysis=sample_analysis)
        storage = Mock(db_path="unused.db")
        storage.get_recent_events.return_value = []
        # This snapshot is within the old two-hour matching window, but cannot
        # establish modem health at the time of the speedtest.
        storage.get_closest_snapshot.return_value = {
            "timestamp": "2026-09-07T11:30:00Z",
            "summary": {"health": "critical"},
        }
        current_runtime().storage = storage
        with patch("app.modules.speedtest.storage.SpeedtestStorage") as speedtests, patch(
            "app.modules.journal.storage.JournalStorage"
        ) as journal:
            speedtests.return_value.get_recent_speedtests.return_value = [{
                "timestamp": "2026-09-07T10:00:00Z",
                "download_human": "250 Mbps",
                "upload_human": "25 Mbps",
                "ping_ms": 12,
            }]
            journal.return_value.get_active_entries.return_value = []

            response = client.get(f"/api/export?mode={mode}")

            assert response.status_code == 200
            report = response.get_json()["text"]
            assert "2026-09-07T10:00:00Z | 250 Mbps | 25 Mbps | 12 ms" in report
            assert "## Downstream Channels" in report
            assert "## Reference Values" in report
            assert "Cross-Source Correlation" not in report
            assert "2026-09-07T11:30:00Z" not in report
            storage.get_closest_snapshot.assert_not_called()
            storage.get_recent_events.assert_called_once_with(hours=hours)
            speedtests.return_value.get_recent_speedtests.assert_called_once_with(limit=limit)

    def test_export_labels_detected_speed_and_error_counts(self, client, sample_analysis):
        current_runtime().update_state(
            analysis=sample_analysis,
            connection_info={"max_downstream_kbps": 250000, "max_upstream_kbps": 50000},
        )

        report = client.get("/api/export").get_json()["text"]

        assert "**Modem-reported connection speed**: 250/50 Mbit/s" in report
        assert "**Tariff**" not in report
        assert "| DS Uncorrectable Errors | 56 |" in report
        assert "do not infer error rates without a measurement interval and denominator" in report

    def test_export_no_data(self, client):
        current_runtime().reset_modem_state()
        resp = client.get("/api/export")
        assert resp.status_code == 404

    def test_export_returns_markdown(self, client, sample_analysis):
        current_runtime().update_state(analysis=sample_analysis)
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
        current_runtime().update_state(analysis=sample_analysis)

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
