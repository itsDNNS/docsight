"""Tests for Smart Capture execution engine."""

import pytest
from unittest.mock import MagicMock

from app.storage import SnapshotStorage
from app.smart_capture.engine import SmartCaptureEngine
from app.smart_capture.types import Trigger, ExecutionStatus


def _make_config(**overrides):
    defaults = {
        "sc_enabled": True,
        "sc_global_cooldown": 0,
        "sc_trigger_cooldown": 0,
        "sc_max_actions_per_hour": 999,
        "sc_flapping_window": 3600,
        "sc_flapping_threshold": 999,
    }
    defaults.update(overrides)
    config = MagicMock()
    config.get = lambda key, default=None: defaults.get(key, default)
    return config


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


@pytest.fixture
def engine(storage):
    config = _make_config()
    e = SmartCaptureEngine(storage, config)
    e.register_trigger(Trigger(
        event_type="modulation_change",
        action_type="capture",
        min_severity="warning",
        require_details={"direction": "downgrade"},
    ))
    return e


class TestEvaluate:
    def test_matching_event_creates_pending_execution(self, engine, storage):
        events = [{
            "event_type": "modulation_change",
            "severity": "warning",
            "timestamp": "2026-03-15T10:00:00Z",
            "message": "Modulation dropped on 1 channel(s)",
            "details": {"direction": "downgrade", "changes": []},
        }]
        engine.evaluate(events)
        rows = storage.get_executions()
        assert len(rows) == 1
        assert rows[0]["status"] == "pending"
        assert rows[0]["trigger_type"] == "modulation_change"
        assert rows[0]["action_type"] == "capture"

    def test_non_matching_event_ignored(self, engine, storage):
        events = [{
            "event_type": "power_change",
            "severity": "warning",
            "timestamp": "2026-03-15T10:00:00Z",
            "message": "Power shift",
            "details": {"direction": "upstream"},
        }]
        engine.evaluate(events)
        assert storage.get_executions() == []

    def test_upgrade_event_ignored(self, engine, storage):
        events = [{
            "event_type": "modulation_change",
            "severity": "info",
            "timestamp": "2026-03-15T10:00:00Z",
            "message": "Modulation improved",
            "details": {"direction": "upgrade", "changes": []},
        }]
        engine.evaluate(events)
        assert storage.get_executions() == []

    def test_guardrail_blocked_creates_suppressed(self, storage):
        config = _make_config(sc_global_cooldown=600)
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(
            event_type="modulation_change", action_type="capture",
        ))
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop"}
        engine.evaluate([event])  # first: pending
        engine.evaluate([event])  # second: suppressed
        rows = storage.get_executions()
        assert len(rows) == 2
        suppressed = [r for r in rows if r["status"] == "suppressed"]
        assert len(suppressed) == 1
        assert "global_cooldown" in suppressed[0]["suppression_reason"]

    def test_disabled_engine_does_nothing(self, storage):
        config = _make_config(sc_enabled=False)
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(
            event_type="modulation_change", action_type="capture",
        ))
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop"}
        engine.evaluate([event])
        assert storage.get_executions() == []

    def test_multiple_triggers_can_match(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(event_type="modulation_change",
                                        action_type="capture"))
        engine.register_trigger(Trigger(event_type="modulation_change",
                                        action_type="webhook"))
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop"}
        engine.evaluate([event])
        rows = storage.get_executions()
        assert len(rows) == 2
        action_types = {r["action_type"] for r in rows}
        assert action_types == {"capture", "webhook"}

    def test_empty_events_is_noop(self, engine, storage):
        engine.evaluate([])
        assert storage.get_executions() == []

    def test_event_id_correlation(self, storage):
        """Events with _id set get their trigger_event_id stored."""
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(event_type="modulation_change",
                                        action_type="capture"))
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop",
                 "_id": 42}
        engine.evaluate([event])
        rows = storage.get_executions()
        assert rows[0]["trigger_event_id"] == 42


class TestRegisterTrigger:
    def test_register_adds_trigger(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        assert len(engine.triggers) == 0
        engine.register_trigger(Trigger(event_type="test", action_type="test"))
        assert len(engine.triggers) == 1

    def test_duplicate_trigger_not_added(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        t = Trigger(event_type="test", action_type="test")
        engine.register_trigger(t)
        engine.register_trigger(t)
        assert len(engine.triggers) == 1


class TestEndToEnd:
    """Full flow: event -> trigger match -> guardrail -> execution record."""

    def test_modulation_downgrade_flow(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(
            event_type="modulation_change",
            action_type="capture",
            min_severity="warning",
            require_details={"direction": "downgrade"},
        ))

        events = [{
            "timestamp": "2026-03-15T10:00:00Z",
            "severity": "warning",
            "event_type": "modulation_change",
            "message": "Modulation dropped on 1 channel(s)",
            "details": {
                "direction": "downgrade",
                "changes": [{"channel": 5, "direction": "US",
                             "prev": "64QAM", "current": "8QAM",
                             "rank_drop": 3}],
            },
        }]

        engine.evaluate(events)

        rows = storage.get_executions()
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "pending"
        assert row["trigger_type"] == "modulation_change"
        assert row["action_type"] == "capture"
        assert row["details"]["direction"] == "downgrade"
        assert row["suppression_reason"] is None

    def test_modulation_upgrade_ignored(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(
            event_type="modulation_change",
            action_type="capture",
            min_severity="warning",
            require_details={"direction": "downgrade"},
        ))

        events = [{
            "timestamp": "2026-03-15T10:15:00Z",
            "severity": "info",
            "event_type": "modulation_change",
            "message": "Modulation improved on 1 channel(s)",
            "details": {"direction": "upgrade", "changes": []},
        }]

        engine.evaluate(events)
        assert storage.get_executions() == []

    def test_guardrail_suppression_chain(self, storage):
        """Second matching event within global cooldown gets suppressed."""
        config = _make_config(sc_global_cooldown=300)
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(
            event_type="modulation_change",
            action_type="capture",
            require_details={"direction": "downgrade"},
        ))

        event = {
            "timestamp": "2026-03-15T10:00:00Z",
            "severity": "warning",
            "event_type": "modulation_change",
            "message": "drop",
            "details": {"direction": "downgrade", "changes": []},
        }

        engine.evaluate([event])
        engine.evaluate([event])

        rows = storage.get_executions()
        pending = [r for r in rows if r["status"] == "pending"]
        suppressed = [r for r in rows if r["status"] == "suppressed"]
        assert len(pending) == 1
        assert len(suppressed) == 1
        assert "global_cooldown" in suppressed[0]["suppression_reason"]

    def test_execution_update_lifecycle(self, storage):
        """Verify execution can progress: pending -> fired -> completed."""
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(
            event_type="modulation_change", action_type="capture",
            require_details={"direction": "downgrade"},
        ))

        engine.evaluate([{
            "timestamp": "2026-03-15T10:00:00Z",
            "severity": "warning",
            "event_type": "modulation_change",
            "message": "drop",
            "details": {"direction": "downgrade", "changes": []},
        }])

        rows = storage.get_executions(status="pending")
        assert len(rows) == 1
        eid = rows[0]["id"]

        # Simulate action adapter firing
        storage.update_execution(eid, status=ExecutionStatus.FIRED,
                                 fired_at="2026-03-15T10:00:05Z")
        row = storage.get_execution(eid)
        assert row["status"] == "fired"

        # Simulate result linking
        storage.update_execution(eid, status=ExecutionStatus.COMPLETED,
                                 completed_at="2026-03-15T10:01:00Z",
                                 linked_result_id=42)
        row = storage.get_execution(eid)
        assert row["status"] == "completed"
        assert row["linked_result_id"] == 42
