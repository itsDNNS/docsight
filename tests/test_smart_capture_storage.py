"""Tests for Smart Capture storage mixin."""

import pytest

from app.storage import SnapshotStorage
from app.smart_capture.types import ExecutionStatus


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


class TestSaveExecution:
    def test_save_returns_id(self, storage):
        eid = storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        assert isinstance(eid, int)
        assert eid > 0

    def test_save_suppressed_with_reason(self, storage):
        eid = storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.SUPPRESSED,
            suppression_reason="global_cooldown: 120s remaining",
        )
        row = storage.get_execution(eid)
        assert row["status"] == "suppressed"
        assert row["suppression_reason"] == "global_cooldown: 120s remaining"

    def test_save_with_details(self, storage):
        eid = storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.PENDING,
            details={"channel": 5, "direction": "downgrade"},
        )
        row = storage.get_execution(eid)
        assert row["details"]["channel"] == 5

    def test_save_with_trigger_timestamp(self, storage):
        eid = storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.PENDING,
            trigger_timestamp="2026-03-15T10:00:00Z",
        )
        row = storage.get_execution(eid)
        assert row["trigger_timestamp"] == "2026-03-15T10:00:00Z"

    def test_trigger_event_id_round_trips(self, storage):
        eid = storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.PENDING,
            trigger_event_id=42,
        )
        row = storage.get_execution(eid)
        assert row["trigger_event_id"] == 42


class TestGetExecution:
    def test_get_by_id(self, storage):
        eid = storage.save_execution(
            trigger_type="error_spike",
            action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        row = storage.get_execution(eid)
        assert row["id"] == eid
        assert row["trigger_type"] == "error_spike"
        assert row["action_type"] == "capture"
        assert row["status"] == "pending"
        assert row["created_at"] is not None

    def test_get_nonexistent_returns_none(self, storage):
        assert storage.get_execution(9999) is None


class TestUpdateExecution:
    def test_update_status(self, storage):
        eid = storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        storage.update_execution(eid, status=ExecutionStatus.FIRED,
                                 fired_at="2026-03-15T10:01:00Z")
        row = storage.get_execution(eid)
        assert row["status"] == "fired"
        assert row["fired_at"] == "2026-03-15T10:01:00Z"

    def test_update_completed_with_result(self, storage):
        eid = storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.FIRED,
        )
        storage.update_execution(eid, status=ExecutionStatus.COMPLETED,
                                 completed_at="2026-03-15T10:05:00Z",
                                 linked_result_id=42)
        row = storage.get_execution(eid)
        assert row["status"] == "completed"
        assert row["linked_result_id"] == 42


class TestGetExecutions:
    def test_list_ordered_newest_first(self, storage):
        storage.save_execution(trigger_type="a",
                               action_type="capture", status=ExecutionStatus.PENDING)
        storage.save_execution(trigger_type="b",
                               action_type="capture", status=ExecutionStatus.SUPPRESSED,
                               suppression_reason="cooldown")
        rows = storage.get_executions(limit=10)
        assert len(rows) == 2
        assert rows[0]["trigger_type"] == "b"  # newest first

    def test_filter_by_status(self, storage):
        storage.save_execution(trigger_type="a",
                               action_type="capture", status=ExecutionStatus.PENDING)
        storage.save_execution(trigger_type="b",
                               action_type="capture", status=ExecutionStatus.SUPPRESSED,
                               suppression_reason="cooldown")
        rows = storage.get_executions(status="suppressed")
        assert len(rows) == 1
        assert rows[0]["status"] == "suppressed"


class TestCountExecutionsSince:
    def test_counts_in_window(self, storage):
        storage.save_execution(trigger_type="modulation_change",
                               action_type="capture", status=ExecutionStatus.PENDING)
        storage.save_execution(trigger_type="modulation_change",
                               action_type="capture", status=ExecutionStatus.SUPPRESSED,
                               suppression_reason="test")
        count = storage.count_executions_since("2020-01-01T00:00:00Z",
                                               status="pending")
        assert count == 1

    def test_counts_all_statuses(self, storage):
        storage.save_execution(trigger_type="a",
                               action_type="capture", status=ExecutionStatus.PENDING)
        storage.save_execution(trigger_type="b",
                               action_type="capture", status=ExecutionStatus.SUPPRESSED,
                               suppression_reason="test")
        count = storage.count_executions_since("2020-01-01T00:00:00Z")
        assert count == 2
