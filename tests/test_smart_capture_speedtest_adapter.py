"""Regression coverage for Smart Capture's Speedtest Tracker adapter."""

import sqlite3
from unittest.mock import MagicMock

import pytest
import requests

from app.modules.speedtest.storage import SpeedtestStorage
from app.smart_capture.adapters.speedtest import SpeedtestAdapter
from app.smart_capture.types import ExecutionStatus
from app.storage import SnapshotStorage
from app.types import EventDict


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


def _make_config(**overrides):
    defaults = {
        "speedtest_tracker_url": "http://speedtest.local",
        "speedtest_tracker_token": "token",
        "speedtest_tls_insecure": False,
        "sc_speedtest_min_interval": 14400,
        "sc_speedtest_max_actions_per_day": 4,
        "sc_speedtest_match_window": 900,
    }
    defaults.update(overrides)
    config = MagicMock()
    config.get = lambda key, default=None: defaults.get(key, default)
    return config


def _pending_execution(storage, *, trigger_timestamp="2026-03-15T12:00:00Z"):
    return storage.save_execution(
        trigger_type="modulation_change",
        action_type="capture",
        status=ExecutionStatus.PENDING,
        trigger_timestamp=trigger_timestamp,
    )


def _insert_speedtest_result(storage, *, result_id=10, timestamp="2026-03-15T11:30:00Z"):
    SpeedtestStorage(storage.db_path)
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO speedtest_results "
            "(id, timestamp, download_mbps, upload_mbps, download_human, upload_human, "
            " ping_ms, jitter_ms, packet_loss_pct, server_id, server_name) "
            "VALUES (?, ?, 100, 20, '100 Mbps', '20 Mbps', 10, 1, 0, 1, 'test')",
            (result_id, timestamp),
        )


def _event(timestamp="2026-03-15T12:00:00Z") -> EventDict:
    return {
        "event_type": "modulation_change",
        "severity": "warning",
        "timestamp": timestamp,
        "message": "Modulation dropped on 1 channel(s)",
    }


class _Response:
    def __init__(self, status_code=201, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def test_recent_tracker_result_suppresses_smart_capture_before_post(storage):
    _insert_speedtest_result(storage, timestamp="2026-03-15T11:30:00Z")
    execution_id = _pending_execution(storage, trigger_timestamp="2026-03-15T12:00:00Z")
    adapter = SpeedtestAdapter(storage, _make_config())
    adapter._session = MagicMock()
    adapter._session.get.side_effect = requests.RequestException("offline")

    ok, reason = adapter.execute(
        execution_id,
        _event(),
    )

    row = storage.get_execution(execution_id)
    assert ok is False
    assert reason is not None
    assert "recent_speedtest_result" in reason
    assert row["status"] == "suppressed"
    assert "recent_speedtest_result" in row["suppression_reason"]
    adapter._session.post.assert_not_called()


def test_recent_smart_capture_fire_suppresses_after_adapter_restart(storage):
    previous = storage.save_execution(
        trigger_type="modulation_change",
        action_type="capture",
        status=ExecutionStatus.FIRED,
        fired_at="2026-03-15T10:30:00Z",
    )
    assert previous == 1
    execution_id = _pending_execution(storage, trigger_timestamp="2026-03-15T12:00:00Z")
    adapter = SpeedtestAdapter(storage, _make_config())
    adapter._session = MagicMock()
    adapter._session.get.return_value = _Response(200, {"data": []})

    ok, reason = adapter.execute(
        execution_id,
        _event(),
    )

    row = storage.get_execution(execution_id)
    assert ok is False
    assert reason is not None
    assert "speedtest_min_interval" in reason
    assert row["status"] == "suppressed"
    adapter._session.post.assert_not_called()


def test_daily_speedtest_smart_capture_budget_is_persistent(storage):
    for fired_at in ("2026-03-15T01:00:00Z", "2026-03-15T06:00:00Z"):
        storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.FIRED,
            fired_at=fired_at,
        )
    execution_id = _pending_execution(storage, trigger_timestamp="2026-03-15T12:00:00Z")
    adapter = SpeedtestAdapter(storage, _make_config(sc_speedtest_max_actions_per_day=2, sc_speedtest_min_interval=0))
    adapter._session = MagicMock()
    adapter._session.get.return_value = _Response(200, {"data": []})

    ok, reason = adapter.execute(
        execution_id,
        _event(),
    )

    row = storage.get_execution(execution_id)
    assert ok is False
    assert reason is not None
    assert "speedtest_daily_cap" in reason
    assert row["status"] == "suppressed"
    adapter._session.post.assert_not_called()


def test_read_timeout_is_recorded_as_fired_pending_result_link(storage):
    execution_id = _pending_execution(storage)
    adapter = SpeedtestAdapter(storage, _make_config(sc_speedtest_min_interval=0))
    adapter._session = MagicMock()
    adapter._session.get.return_value = _Response(200, {"data": []})
    adapter._session.post.side_effect = requests.exceptions.ReadTimeout("slow run")

    ok, reason = adapter.execute(
        execution_id,
        _event(),
    )

    row = storage.get_execution(execution_id)
    assert ok is True
    assert reason is None
    assert row["status"] == "fired"
    assert row["fired_at"] is not None
    assert "unknown" in row["last_error"]


def test_configurable_match_window_links_long_running_speedtest(storage):
    execution_id = storage.save_execution(
        trigger_type="modulation_change",
        action_type="capture",
        status=ExecutionStatus.FIRED,
        fired_at="2026-03-15T10:00:00Z",
    )
    adapter = SpeedtestAdapter(storage, _make_config(sc_speedtest_match_window=900))

    adapter.on_results_imported([{"id": 42, "timestamp": "2026-03-15T10:12:00Z"}])

    row = storage.get_execution(execution_id)
    assert row["status"] == "completed"
    assert row["linked_result_id"] == 42
