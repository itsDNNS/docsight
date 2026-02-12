"""Tests for extended storage methods: watchdog events, ping, smokeping, event log."""

import json
import time
import pytest
from datetime import datetime
from app.storage import SnapshotStorage


def _now_ts():
    """Return current timestamp in ISO format (matching storage format)."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=7)


# ── Watchdog Events ──

class TestWatchdogEventStorage:
    def test_save_and_retrieve(self, storage):
        ts = _now_ts()
        event = {
            "timestamp": ts,
            "event_type": "modulation_drop",
            "channel_id": 3,
            "direction": "ds",
            "message": "DS CH3 modulation dropped: 256QAM → 64QAM",
            "severity": "warning",
            "details": {"previous": "256QAM", "current": "64QAM"},
        }
        storage.save_watchdog_event(event)
        events = storage.get_watchdog_events(hours=48)
        assert len(events) == 1
        assert events[0]["event_type"] == "modulation_drop"
        assert events[0]["channel_id"] == 3
        assert events[0]["details"]["previous"] == "256QAM"

    def test_multiple_events(self, storage):
        ts = _now_ts()
        for i in range(5):
            storage.save_watchdog_event({
                "timestamp": ts,
                "event_type": "modulation_drop",
                "channel_id": i,
                "direction": "ds",
                "message": f"Event {i}",
                "severity": "warning",
            })
        events = storage.get_watchdog_events(hours=48)
        assert len(events) == 5

    def test_event_counts(self, storage):
        ts = _now_ts()
        storage.save_watchdog_event({
            "timestamp": ts,
            "event_type": "modulation_drop",
            "channel_id": 1, "direction": "ds",
            "message": "drop", "severity": "warning",
        })
        storage.save_watchdog_event({
            "timestamp": ts,
            "event_type": "modulation_drop",
            "channel_id": 2, "direction": "ds",
            "message": "drop 2", "severity": "warning",
        })
        storage.save_watchdog_event({
            "timestamp": ts,
            "event_type": "power_drift",
            "channel_id": None, "direction": "ds",
            "message": "drift", "severity": "warning",
        })
        counts = storage.get_watchdog_event_counts(hours=48)
        assert counts["modulation_drop"] == 2
        assert counts["power_drift"] == 1

    def test_empty_events(self, storage):
        events = storage.get_watchdog_events()
        assert events == []

    def test_event_without_details(self, storage):
        ts = _now_ts()
        storage.save_watchdog_event({
            "timestamp": ts,
            "event_type": "channel_count_drop",
            "channel_id": None, "direction": "us",
            "message": "dropped", "severity": "critical",
        })
        events = storage.get_watchdog_events(hours=48)
        assert events[0]["details"] == {}


# ── Ping Results ──

class TestPingResultStorage:
    def test_save_and_retrieve(self, storage):
        ts = _now_ts()
        storage.save_ping_result({
            "timestamp": ts,
            "target": "8.8.8.8",
            "avg_ms": 12.5,
            "min_ms": 10.0,
            "max_ms": 15.0,
            "jitter_ms": 2.5,
            "loss_pct": 0.0,
            "count": 5,
        })
        results = storage.get_ping_results(hours=48)
        assert len(results) == 1
        assert results[0]["target"] == "8.8.8.8"
        assert results[0]["avg_ms"] == 12.5

    def test_filter_by_target(self, storage):
        ts = _now_ts()
        for target in ["8.8.8.8", "1.1.1.1", "8.8.8.8"]:
            storage.save_ping_result({
                "timestamp": ts,
                "target": target,
                "avg_ms": 10.0, "min_ms": 8.0, "max_ms": 12.0,
                "jitter_ms": 2.0, "loss_pct": 0.0, "count": 5,
            })
        results = storage.get_ping_results(hours=48, target="8.8.8.8")
        assert len(results) == 2

    def test_ping_stats(self, storage):
        ts = _now_ts()
        storage.save_ping_result({
            "timestamp": ts,
            "target": "8.8.8.8",
            "avg_ms": 10.0, "min_ms": 8.0, "max_ms": 12.0,
            "jitter_ms": 2.0, "loss_pct": 0.0, "count": 5,
        })
        storage.save_ping_result({
            "timestamp": ts,
            "target": "8.8.8.8",
            "avg_ms": 20.0, "min_ms": 15.0, "max_ms": 25.0,
            "jitter_ms": 5.0, "loss_pct": 1.0, "count": 5,
        })
        stats = storage.get_ping_stats(hours=48)
        assert stats["avg_ms"] == 15.0  # (10+20)/2
        assert stats["count"] == 2
        assert stats["min_ms"] == 8.0
        assert stats["max_ms"] == 25.0

    def test_empty_stats(self, storage):
        assert storage.get_ping_stats() == {}


# ── Smokeping Data ──

class TestSmokepingStorage:
    def test_save_and_retrieve(self, storage):
        ts = _now_ts()
        data_points = [
            {
                "timestamp": ts,
                "median_ms": 12.0,
                "avg_ms": 13.0,
                "min_ms": 10.0,
                "max_ms": 16.0,
                "loss_pct": 0.0,
            },
            {
                "timestamp": ts + "1",  # slightly different to avoid dedup
                "median_ms": 14.0,
                "avg_ms": 15.0,
                "min_ms": 12.0,
                "max_ms": 18.0,
                "loss_pct": 5.0,
            },
        ]
        storage.save_smokeping_data(data_points, target="ISP.Router")
        results = storage.get_smokeping_data(hours=48)
        assert len(results) == 2
        assert results[0]["median_ms"] == 12.0

    def test_dedup_by_timestamp(self, storage):
        ts = _now_ts()
        dp = [{
            "timestamp": ts,
            "median_ms": 12.0, "avg_ms": 12.0, "min_ms": 10.0,
            "max_ms": 14.0, "loss_pct": 0.0,
        }]
        storage.save_smokeping_data(dp, target="test")
        storage.save_smokeping_data(dp, target="test")  # duplicate
        results = storage.get_smokeping_data(hours=48)
        assert len(results) == 1

    def test_empty_list(self, storage):
        storage.save_smokeping_data([], target="test")
        assert storage.get_smokeping_data() == []


# ── Event Log ──

class TestEventLogStorage:
    def test_save_and_retrieve(self, storage):
        ts = _now_ts()
        events = [
            {
                "timestamp": ts,
                "message": "T3 Timeout",
                "category": "docsis_error",
                "docsis_code": "T3",
            },
        ]
        storage.save_event_log(events)
        log = storage.get_event_log(hours=48)
        assert len(log) == 1
        assert log[0]["message"] == "T3 Timeout"
        assert log[0]["docsis_code"] == "T3"

    def test_dedup_by_timestamp_message(self, storage):
        ts = _now_ts()
        events = [{
            "timestamp": ts,
            "message": "T3 Timeout",
            "category": "docsis_error",
            "docsis_code": "T3",
        }]
        storage.save_event_log(events)
        storage.save_event_log(events)  # duplicate
        log = storage.get_event_log(hours=48)
        assert len(log) == 1

    def test_event_log_counts(self, storage):
        ts = _now_ts()
        events = [
            {"timestamp": ts, "message": "T3 Timeout",
             "category": "docsis_error", "docsis_code": "T3"},
            {"timestamp": ts, "message": "T4 Registration",
             "category": "docsis_error", "docsis_code": "T4"},
            {"timestamp": ts, "message": "Internet connected",
             "category": "connection", "docsis_code": None},
        ]
        storage.save_event_log(events)
        counts = storage.get_event_log_counts(hours=48)
        assert counts["total"] == 3
        assert counts["by_category"]["docsis_error"] == 2
        assert counts["by_category"]["connection"] == 1
        assert counts["by_docsis_code"]["T3"] == 1

    def test_empty_event_log(self, storage):
        assert storage.get_event_log() == []

    def test_save_empty_list(self, storage):
        storage.save_event_log([])
        assert storage.get_event_log() == []
