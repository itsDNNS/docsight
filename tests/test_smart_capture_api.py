"""Tests for Smart Capture API endpoints and data enrichment."""

import json
import pytest

from app.storage import SnapshotStorage
from app.smart_capture.types import ExecutionStatus


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


class TestExecutionsAPI:
    def test_returns_empty_list(self, storage):
        from app.web import app, init_storage
        init_storage(storage)
        with app.test_client() as client:
            resp = client.get("/api/smart-capture/executions")
            data = json.loads(resp.data)
            assert resp.status_code == 200
            assert data["executions"] == []

    def test_returns_executions(self, storage):
        storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        from app.web import app, init_storage
        init_storage(storage)
        with app.test_client() as client:
            resp = client.get("/api/smart-capture/executions")
            data = json.loads(resp.data)
            assert len(data["executions"]) == 1
            assert data["executions"][0]["trigger_type"] == "modulation_change"

    def test_respects_status_filter(self, storage):
        storage.save_execution(
            trigger_type="a", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        storage.save_execution(
            trigger_type="b", action_type="capture",
            status=ExecutionStatus.SUPPRESSED,
            suppression_reason="cooldown",
        )
        from app.web import app, init_storage
        init_storage(storage)
        with app.test_client() as client:
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


class TestCorrelationCaptureSource:
    def test_capture_entries_in_timeline(self, storage):
        # Insert a Smart Capture execution
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
