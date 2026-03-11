"""Tests for Connection Monitor storage layer."""

import time
import pytest

from app.modules.connection_monitor.storage import ConnectionMonitorStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test_cm.db")
    return ConnectionMonitorStorage(db_path)


class TestTargetCRUD:
    def test_create_target(self, storage):
        tid = storage.create_target("Cloudflare", "1.1.1.1")
        assert tid == 1
        targets = storage.get_targets()
        assert len(targets) == 1
        assert targets[0]["label"] == "Cloudflare"
        assert targets[0]["host"] == "1.1.1.1"
        assert targets[0]["enabled"] == 1
        assert targets[0]["poll_interval_ms"] == 5000

    def test_create_target_custom_settings(self, storage):
        tid = storage.create_target(
            "Google", "8.8.8.8",
            poll_interval_ms=2500, probe_method="tcp", tcp_port=80,
        )
        target = storage.get_target(tid)
        assert target["poll_interval_ms"] == 2500
        assert target["probe_method"] == "tcp"
        assert target["tcp_port"] == 80

    def test_update_target(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        storage.update_target(tid, label="Updated", enabled=False)
        target = storage.get_target(tid)
        assert target["label"] == "Updated"
        assert target["enabled"] == 0

    def test_delete_target_cascades_samples(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        storage.save_samples([
            {"target_id": tid, "timestamp": time.time(), "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        storage.delete_target(tid)
        assert storage.get_target(tid) is None
        assert storage.get_samples(tid) == []

    def test_get_nonexistent_target(self, storage):
        assert storage.get_target(999) is None


class TestSamples:
    def test_save_and_get_samples(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - 2, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 1, "latency_ms": 15.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        result = storage.get_samples(tid)
        assert len(result) == 3

    def test_get_samples_with_time_range(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - 100, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 50, "latency_ms": 15.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        result = storage.get_samples(tid, start=now - 60, end=now - 10)
        assert len(result) == 1
        assert result[0]["latency_ms"] == 15.0

    def test_get_samples_with_limit(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - i, "latency_ms": float(i), "timeout": False, "probe_method": "tcp"}
            for i in range(20)
        ]
        storage.save_samples(samples)
        result = storage.get_samples(tid, limit=5)
        assert len(result) == 5

    def test_get_samples_no_limit(self, storage):
        """limit=0 should return all samples (no LIMIT clause)."""
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - i, "latency_ms": float(i), "timeout": False, "probe_method": "tcp"}
            for i in range(20)
        ]
        storage.save_samples(samples)
        result = storage.get_samples(tid, limit=0)
        assert len(result) == 20


class TestRetention:
    def test_cleanup_old_samples(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        old_ts = now - (8 * 86400)  # 8 days ago
        new_ts = now - 60  # 1 minute ago
        storage.save_samples([
            {"target_id": tid, "timestamp": old_ts, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": new_ts, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ])
        deleted = storage.cleanup(retention_days=7)
        assert deleted == 1
        result = storage.get_samples(tid)
        assert len(result) == 1
        assert result[0]["latency_ms"] == 20.0

    def test_cleanup_zero_keeps_all(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        old_ts = time.time() - (365 * 86400)
        storage.save_samples([
            {"target_id": tid, "timestamp": old_ts, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        deleted = storage.cleanup(retention_days=0)
        assert deleted == 0
        assert len(storage.get_samples(tid)) == 1


class TestSummary:
    def test_summary_returns_stats(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 30, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 20, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ])
        summary = storage.get_summary(tid, window_seconds=60)
        assert summary["sample_count"] == 3
        assert summary["avg_latency_ms"] == 15.0
        assert abs(summary["packet_loss_pct"] - 33.33) < 1
        assert summary["min_latency_ms"] == 10.0
        assert summary["max_latency_ms"] == 20.0


class TestOutages:
    def test_derive_outages(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        # 5 consecutive timeouts = 1 outage
        samples = [
            {"target_id": tid, "timestamp": now - 50, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ]
        for i in range(5):
            samples.append({
                "target_id": tid, "timestamp": now - 40 + (i * 5),
                "latency_ms": None, "timeout": True, "probe_method": "tcp",
            })
        samples.append(
            {"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        )
        storage.save_samples(samples)
        outages = storage.get_outages(tid, threshold=5)
        assert len(outages) == 1
        assert outages[0]["timeout_count"] == 5

    def test_no_outage_below_threshold(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [
            {"target_id": tid, "timestamp": now - 20, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 15, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        outages = storage.get_outages(tid, threshold=5)
        assert len(outages) == 0
