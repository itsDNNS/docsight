"""Tests for Smart Capture API endpoints and data enrichment."""

import json
import sqlite3
from unittest.mock import patch
import pytest
from flask import current_app

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.smart_capture.types import ExecutionStatus
from app.runtime import current_runtime


def configured_client(data_dir, storage=None, **config):
    """Point the current test app at a fresh configured modem and return its client."""
    manager = ConfigManager(str(data_dir))
    manager.save({"modem_password": "test", "modem_type": "fritzbox", **config})
    current_runtime().config_manager = manager
    current_runtime().storage = storage
    return current_app.test_client()


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


@pytest.fixture
def client(tmp_path, storage):
    with configured_client(tmp_path / "config", storage) as c:
        yield c


class TestExecutionsAPI:
    def test_returns_empty_list(self, client):
        resp = client.get("/api/smart-capture/executions")
        data = json.loads(resp.data)
        assert resp.status_code == 200
        assert data["executions"] == []

    def test_returns_executions(self, storage, client):
        storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        resp = client.get("/api/smart-capture/executions")
        data = json.loads(resp.data)
        assert len(data["executions"]) == 1
        assert data["executions"][0]["trigger_type"] == "modulation_change"

    def test_respects_status_filter(self, storage, client):
        storage.save_execution(
            trigger_type="a", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        storage.save_execution(
            trigger_type="b", action_type="capture",
            status=ExecutionStatus.SUPPRESSED,
            suppression_reason="cooldown",
        )
        resp = client.get("/api/smart-capture/executions?status=pending")
        data = json.loads(resp.data)
        assert len(data["executions"]) == 1
        assert data["executions"][0]["status"] == "pending"


class TestSpeedtestAnnotation:
    def test_annotates_linked_results(self, storage):
        from app.modules.speedtest.routes import _annotate_smart_capture
        # Create a completed execution linking to speedtest result 42
        storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.COMPLETED,
        )
        storage.update_execution(1, status=ExecutionStatus.COMPLETED,
                                 linked_result_id=42)
        results = [
            {"id": 42, "timestamp": "2026-03-16T10:00:00Z"},
            {"id": 43, "timestamp": "2026-03-16T10:05:00Z"},
        ]
        _annotate_smart_capture(results, storage.db_path)
        assert results[0]["smart_capture"] is True
        assert results[1]["smart_capture"] is False

    def test_handles_no_executions(self, storage):
        from app.modules.speedtest.routes import _annotate_smart_capture
        results = [{"id": 1, "timestamp": "2026-03-16T10:00:00Z"}]
        _annotate_smart_capture(results, storage.db_path)
        assert results[0]["smart_capture"] is False

    def test_unreadable_executions_are_logged_and_leave_results_unmarked(self, storage, caplog):
        from app.modules.speedtest.routes import _annotate_smart_capture
        results = [{"id": 1, "timestamp": "2026-03-16T10:00:00Z"}]
        with patch("app.modules.speedtest.routes.open_read", side_effect=sqlite3.OperationalError("database is locked")):
            _annotate_smart_capture(results, storage.db_path)
        assert results[0]["smart_capture"] is False
        assert [r.getMessage() for r in caplog.records] == ["Smart Capture annotation failed (OperationalError)"]


class TestCorrelationCaptureSource:
    def test_capture_entries_in_timeline(self, storage):
        # Insert a Smart Capture execution. Mock utc_now so created_at falls
        # within the query range (save_execution uses utc_now for created_at).
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.storage.smart_capture.utc_now",
                        lambda: "2026-03-16T10:00:05Z")
            storage.save_execution(
                trigger_type="modulation_change", action_type="capture",
                status=ExecutionStatus.FIRED, fired_at="2026-03-16T10:00:05Z",
            )
        timeline = storage.get_correlation_timeline(
            "2026-03-16T00:00:00Z", "2026-03-16T23:59:59Z",
            sources={"capture"},
        )
        capture_entries = [e for e in timeline if e["source"] == "capture"]
        assert len(capture_entries) == 1
        assert capture_entries[0]["status"] == "fired"

    def test_smart_capture_triggered_filtered_when_capture_active(self, storage):
        # Insert a smart_capture_triggered event
        storage.save_event(
            "2026-03-16T10:00:10Z", "info", "smart_capture_triggered",
            "Speedtest triggered", {"execution_id": 1},
        )
        # With capture source: event should be filtered
        timeline = storage.get_correlation_timeline(
            "2026-03-16T00:00:00Z", "2026-03-16T23:59:59Z",
            sources={"events", "capture"},
        )
        sc_events = [e for e in timeline
                     if e.get("source") == "event"
                     and e.get("event_type") == "smart_capture_triggered"]
        assert len(sc_events) == 0

    def test_smart_capture_triggered_kept_when_capture_not_requested(self, storage):
        # Insert a smart_capture_triggered event
        storage.save_event(
            "2026-03-16T10:00:10Z", "info", "smart_capture_triggered",
            "Speedtest triggered", {"execution_id": 1},
        )
        # Without capture source: event should remain
        timeline = storage.get_correlation_timeline(
            "2026-03-16T00:00:00Z", "2026-03-16T23:59:59Z",
            sources={"events"},
        )
        sc_events = [e for e in timeline
                     if e.get("source") == "event"
                     and e.get("event_type") == "smart_capture_triggered"]
        assert len(sc_events) == 1


class TestSmartCaptureSettingsRender:
    """Verify Smart Capture settings section renders with sub-settings controls."""

    def test_settings_contains_smart_capture_section(self, client):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'id="panel-evidence"' in html
        assert html.index('id="panel-evidence"') < html.index('id="block-smart_capture"')

    def test_settings_contains_trigger_cards(self, client):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'data-trigger="sc_trigger_modulation"' in html
        assert 'data-trigger="sc_trigger_snr"' in html
        assert 'data-trigger="sc_trigger_error_spike"' in html
        assert 'data-trigger="sc_trigger_health"' in html
        assert 'data-trigger="sc_trigger_packet_loss"' in html

    def test_settings_contains_sub_settings_controls(self, client):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'name="sc_trigger_modulation_direction"' in html
        assert 'name="sc_trigger_modulation_min_qam"' in html
        assert 'name="sc_trigger_error_spike_min_delta"' in html
        assert 'name="sc_trigger_health_level"' in html
        assert 'name="sc_trigger_packet_loss_min_pct"' in html
        assert 'name="sc_speedtest_min_interval"' in html
        assert 'name="sc_speedtest_max_actions_per_day"' in html
        assert 'name="sc_speedtest_match_window"' in html
        assert 'Speedtest Tracker already ran recently' in html

    def test_settings_contains_qam_dropdown_options(self, client):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'value="4096QAM"' in html
        assert 'value="2048QAM"' in html
        assert 'value="1024QAM"' in html
        assert 'value="512QAM"' in html
        assert 'value="256QAM"' in html
        assert 'value="128QAM"' in html
        assert 'value="64QAM"' in html
        assert 'value="32QAM"' in html
        assert 'value="16QAM"' in html
        assert 'value="8QAM"' in html

    def test_settings_contains_packet_loss_hint(self, client):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'Connection Monitor' in html
