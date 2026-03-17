"""Tests for Connection Monitor traceroute storage layer."""

import time

import pytest

from app.modules.connection_monitor.storage import ConnectionMonitorStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test_cm.db")
    return ConnectionMonitorStorage(db_path)


def _make_hops(count=3):
    """Helper to build a list of hop dicts."""
    return [
        {
            "hop_index": i,
            "hop_ip": f"10.0.0.{i}",
            "hop_host": f"hop-{i}.example.com",
            "latency_ms": 1.5 * (i + 1),
            "probes_responded": 3,
        }
        for i in range(count)
    ]


class TestTracerouteStorage:
    def test_trace_tables_created(self, storage):
        """Traceroute tables should exist after init."""
        with storage._connect() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'traceroute_%'"
            ).fetchall()
            names = {r["name"] for r in tables}
            assert "traceroute_traces" in names
            assert "traceroute_hops" in names

    def test_save_and_get_trace(self, storage):
        """Save a trace with hops and retrieve it by id."""
        tid = storage.create_target("Test", "1.1.1.1")
        hops = _make_hops(3)
        now = time.time()
        trace_id = storage.save_trace(
            target_id=tid,
            timestamp=now,
            trigger_reason="manual",
            hops=hops,
            route_fingerprint="abc123",
            reached_target=True,
        )
        trace = storage.get_trace(trace_id)
        assert trace is not None
        assert trace["target_id"] == tid
        assert trace["trigger_reason"] == "manual"
        assert trace["hop_count"] == 3
        assert trace["route_fingerprint"] == "abc123"
        assert trace["reached_target"] == 1

    def test_get_traces_by_target(self, storage):
        """List traces filtered by target_id and optional time range."""
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_trace(tid, now - 200, "scheduled", _make_hops(2), "fp1", True)
        storage.save_trace(tid, now - 100, "manual", _make_hops(2), "fp2", True)
        storage.save_trace(tid, now, "scheduled", _make_hops(2), "fp3", True)

        # All traces for target
        all_traces = storage.get_traces(tid)
        assert len(all_traces) == 3

        # Filtered by time range
        filtered = storage.get_traces(tid, start=now - 150, end=now - 50)
        assert len(filtered) == 1
        assert filtered[0]["route_fingerprint"] == "fp2"

    def test_get_trace_hops(self, storage):
        """Retrieve hops for a trace, ordered by hop_index."""
        tid = storage.create_target("Test", "1.1.1.1")
        hops = _make_hops(4)
        trace_id = storage.save_trace(tid, time.time(), "manual", hops, "fp", True)
        result = storage.get_trace_hops(trace_id)
        assert len(result) == 4
        for i, hop in enumerate(result):
            assert hop["hop_index"] == i
            assert hop["hop_ip"] == f"10.0.0.{i}"

    def test_save_trace_returns_id(self, storage):
        """save_trace should return a valid integer trace id."""
        tid = storage.create_target("Test", "1.1.1.1")
        trace_id = storage.save_trace(tid, time.time(), "manual", _make_hops(1), "fp", True)
        assert isinstance(trace_id, int)
        assert trace_id > 0

    def test_cleanup_traces_respects_retention(self, storage):
        """Old traces should be deleted; recent ones should be kept."""
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        old_id = storage.save_trace(tid, now - 10 * 86400, "scheduled", _make_hops(2), "old", True)
        new_id = storage.save_trace(tid, now - 60, "scheduled", _make_hops(2), "new", True)

        storage.cleanup_traces(retention_days=7)

        assert storage.get_trace(old_id) is None
        assert storage.get_trace(new_id) is not None

    def test_cleanup_traces_respects_pinned_days(self, storage):
        """Traces on pinned dates should survive cleanup."""
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        old_ts = now - 10 * 86400
        from datetime import datetime, timezone
        old_date = datetime.fromtimestamp(old_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        storage.pin_day(old_date)

        trace_id = storage.save_trace(tid, old_ts, "scheduled", _make_hops(2), "pinned", True)
        storage.cleanup_traces(retention_days=7)

        assert storage.get_trace(trace_id) is not None

    def test_cascade_delete_target(self, storage):
        """Deleting a target should cascade to traces and hops."""
        tid = storage.create_target("Test", "1.1.1.1")
        trace_id = storage.save_trace(tid, time.time(), "manual", _make_hops(3), "fp", True)
        storage.delete_target(tid)

        assert storage.get_trace(trace_id) is None
        assert storage.get_trace_hops(trace_id) == []

    def test_cascade_delete_trace(self, storage):
        """Deleting a trace row should cascade to its hops."""
        tid = storage.create_target("Test", "1.1.1.1")
        trace_id = storage.save_trace(tid, time.time(), "manual", _make_hops(3), "fp", True)
        assert len(storage.get_trace_hops(trace_id)) == 3

        with storage._connect() as conn:
            conn.execute("DELETE FROM traceroute_traces WHERE id = ?", (trace_id,))

        assert storage.get_trace_hops(trace_id) == []

    def test_purge_demo_traces(self, storage):
        """purge_demo_traces should delete is_demo=1 rows, keep is_demo=0."""
        tid = storage.create_target("Test", "1.1.1.1")
        demo_id = storage.save_trace(tid, time.time(), "demo", _make_hops(1), "fp1", True, is_demo=True)
        real_id = storage.save_trace(tid, time.time(), "manual", _make_hops(1), "fp2", True, is_demo=False)

        storage.purge_demo_traces()

        assert storage.get_trace(demo_id) is None
        assert storage.get_trace(real_id) is not None

    def test_empty_trace_list(self, storage):
        """No traces for a target should return an empty list."""
        tid = storage.create_target("Test", "1.1.1.1")
        assert storage.get_traces(tid) == []
