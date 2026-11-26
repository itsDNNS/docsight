"""Tests for Smart Capture execution engine."""

import itertools

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
            event_type="modulation_change",
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
            event_type="modulation_change",
        ))
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop"}
        engine.evaluate([event])
        assert storage.get_executions() == []

    def test_duplicate_trigger_not_dispatched_twice(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        trigger = Trigger(event_type="modulation_change")
        engine.register_trigger(trigger)
        engine.register_trigger(trigger)
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop"}
        engine.evaluate([event])
        rows = storage.get_executions()
        assert len(rows) == 1
        assert rows[0]["action_type"] == "capture"

    def test_empty_events_is_noop(self, engine, storage):
        engine.evaluate([])
        assert storage.get_executions() == []


class TestRegisterTrigger:
    def test_register_adds_trigger(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        assert len(engine.triggers) == 0
        engine.register_trigger(Trigger(event_type="test"))
        assert len(engine.triggers) == 1

    def test_duplicate_trigger_not_added(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        t = Trigger(event_type="test")
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
            event_type="modulation_change",
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


class TestAdapterDispatch:
    def test_adapter_called_on_pending_execution(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(event_type="modulation_change"))

        mock_adapter = MagicMock()
        mock_adapter.action_type = "capture"
        mock_adapter.execute.return_value = (True, None)
        engine.register_speedtest_adapter(mock_adapter)

        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop", "_id": 1}
        engine.evaluate([event])

        mock_adapter.execute.assert_called_once()
        call_args = mock_adapter.execute.call_args
        assert isinstance(call_args[0][0], int)  # execution_id
        assert call_args[0][1] == event  # event dict

    def test_no_adapter_registered_stays_pending(self, storage):
        config = _make_config()
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(event_type="modulation_change"))
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop"}
        engine.evaluate([event])
        rows = storage.get_executions()
        assert rows[0]["status"] == "pending"

    def test_suppressed_execution_does_not_call_adapter(self, storage):
        config = _make_config(sc_global_cooldown=600)
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(event_type="modulation_change"))
        mock_adapter = MagicMock()
        mock_adapter.execute.return_value = (True, None)
        engine.register_speedtest_adapter(mock_adapter)

        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "drop"}
        engine.evaluate([event])  # first: allowed, adapter called
        engine.evaluate([event])  # second: suppressed, adapter NOT called
        assert mock_adapter.execute.call_count == 1


def _target_fires(severity, trigger_enabled, sub_filter_result):
    return severity == "warning" and trigger_enabled is not False and sub_filter_result is not False


class TestConfigDrivenTriggerGating:
    @pytest.mark.parametrize("severity,trigger_enabled,sub_filter_result,limited", [
        (*case, limited)
        for case in itertools.product(["warning", "info"], [None, True, False], [None, True, False])
        for limited in ([False, True] if _target_fires(*case) else [False])
    ])
    def test_poll_writes_and_dispatches_in_order(self, storage, monkeypatch, severity,
                                                 trigger_enabled, sub_filter_result, limited):
        """A matching event of an enabled trigger whose sub-filter passes is recorded;
        guardrails pick pending or suppressed. Each write is followed by its dispatch,
        in event order and in trigger registration order."""
        config = _make_config(sc_max_actions_per_hour=1 if limited else 999,
                              sc_trigger_modulation=trigger_enabled)
        engine = SmartCaptureEngine(storage, config)
        sub_filter = None if sub_filter_result is None else MagicMock(return_value=sub_filter_result)
        engine.register_trigger(Trigger(
            event_type="modulation_change", min_severity="warning",
            config_key=None if trigger_enabled is None else "sc_trigger_modulation",
            sub_filter=sub_filter,
        ))
        engine.register_trigger(Trigger(event_type="modulation_change"))
        engine.register_trigger(Trigger(event_type="other"))
        trace = []
        save = storage.save_execution

        def record_save(**kwargs):
            trace.append(("save", {"suppression_reason": None, **kwargs}))
            return save(**kwargs)

        monkeypatch.setattr(storage, "save_execution", record_save)
        adapter = MagicMock()
        adapter.execute.side_effect = lambda execution_id, ev: trace.append(("adapter", execution_id, ev))
        engine.register_speedtest_adapter(adapter)
        event = {"event_type": "modulation_change", "severity": severity, "_id": 7,
                 "timestamp": "2026-03-16T10:00:00Z", "details": {"direction": "downgrade"}}
        other = {"event_type": "other", "_id": 8, "timestamp": "2026-03-16T10:00:01Z", "details": None}
        engine.evaluate([event, other])

        fires = _target_fires(severity, trigger_enabled, sub_filter_result)
        expected = []
        for execution_id, ev in enumerate(([event] if fires else []) + [event, other], start=1):
            allowed = not limited or execution_id == 1  # the hourly limit of 1 admits the first
            expected.append(("save", {
                "trigger_type": ev["event_type"], "action_type": "capture",
                "status": "pending" if allowed else "suppressed",
                "trigger_event_id": ev["_id"], "trigger_timestamp": ev["timestamp"],
                "suppression_reason": None if allowed else "max_actions_per_hour: 1/1 used",
                "details": ev["details"],
            }))
            expected += [("adapter", execution_id, ev)] if allowed else []
        assert trace == expected
        if sub_filter is not None:
            reaches_sub_filter = severity == "warning" and trigger_enabled is not False
            assert sub_filter.call_args_list == ([((config, event),)] if reaches_sub_filter else [])

    def test_master_switch_overrides_trigger_config(self, storage):
        """sc_enabled=False should block even if trigger config_key is True."""
        config = _make_config(sc_enabled=False, sc_trigger_modulation=True)
        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(event_type="modulation_change",
                                        config_key="sc_trigger_modulation"))
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-16T10:00:00Z", "message": "drop"}
        engine.evaluate([event])
        assert storage.get_executions() == []
