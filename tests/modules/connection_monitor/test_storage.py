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

    def test_cleanup_deletes_old_aggregated_data(self, storage):
        """cleanup() should also delete old aggregated samples."""
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        old_ts = now - 200 * 86400  # 200 days ago

        # Insert an aggregated bucket
        with storage._connect() as conn:
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 3600, 10.0, 5.0, 20.0, 18.0, 0.0, 100)""",
                (tid, old_ts),
            )

        deleted = storage.cleanup(retention_days=180)
        assert deleted == 1  # exactly one aggregated row

        agg = storage.get_aggregated_samples(tid, bucket_seconds=3600)
        assert len(agg) == 0


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

    def test_range_stats_returns_exact_metrics(self, storage):
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 40, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 30, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 20, "latency_ms": 30.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ])
        stats = storage.get_range_stats(tid, start=now - 60, end=now)
        assert stats["sample_count"] == 4
        assert stats["latency_count"] == 3
        assert stats["avg_latency_ms"] == 20.0
        assert stats["min_latency_ms"] == 10.0
        assert stats["max_latency_ms"] == 30.0
        assert stats["p95_latency_ms"] == 30.0
        assert abs(stats["packet_loss_pct"] - 25.0) < 0.01


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


class TestAggregation:
    def test_aggregated_table_exists(self, storage):
        """The aggregated table should be created on init."""
        with storage._connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='connection_samples_aggregated'"
            ).fetchone()
            assert row is not None

    def test_aggregate_raw_to_60s(self, storage):
        """Raw samples older than cutoff should be aggregated into 60s buckets."""
        tid = storage.create_target("Test", "1.1.1.1")
        base = 1700000000.0
        samples = [
            {"target_id": tid, "timestamp": base + 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": base + 10, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": base + 15, "latency_ms": 30.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": base + 20, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        storage.aggregate_raw_to_buckets(tid, cutoff=base + 100, bucket_seconds=60)
        raw = storage.get_samples(tid)
        assert len(raw) == 0
        agg = storage.get_aggregated_samples(tid, bucket_seconds=60)
        assert len(agg) == 1
        bucket = agg[0]
        assert bucket["sample_count"] == 4
        assert abs(bucket["avg_latency_ms"] - 20.0) < 0.01
        assert bucket["min_latency_ms"] == 10.0
        assert bucket["max_latency_ms"] == 30.0
        assert abs(bucket["packet_loss_pct"] - 25.0) < 0.01
        assert bucket["p95_latency_ms"] is not None

    def test_aggregate_all_timeout_bucket(self, storage):
        """A bucket with only timeouts should have null latencies and 100% loss."""
        tid = storage.create_target("Test", "1.1.1.1")
        base = 1700000000.0
        samples = [
            {"target_id": tid, "timestamp": base + 5, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": base + 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        storage.aggregate_raw_to_buckets(tid, cutoff=base + 100, bucket_seconds=60)
        agg = storage.get_aggregated_samples(tid, bucket_seconds=60)
        assert len(agg) == 1
        bucket = agg[0]
        assert bucket["avg_latency_ms"] is None
        assert bucket["min_latency_ms"] is None
        assert bucket["max_latency_ms"] is None
        assert bucket["p95_latency_ms"] is None
        assert bucket["packet_loss_pct"] == 100.0
        assert bucket["sample_count"] == 2

    def test_aggregate_creates_multiple_buckets(self, storage):
        """Samples spanning multiple 60s windows should create separate buckets."""
        tid = storage.create_target("Test", "1.1.1.1")
        base = 1700000000.0
        samples = [
            {"target_id": tid, "timestamp": base + 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": base + 65, "latency_ms": 50.0, "timeout": False, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        created = storage.aggregate_raw_to_buckets(tid, cutoff=base + 200, bucket_seconds=60)
        assert created == 2
        agg = storage.get_aggregated_samples(tid, bucket_seconds=60)
        assert len(agg) == 2
        assert agg[0]["avg_latency_ms"] == 10.0
        assert agg[1]["avg_latency_ms"] == 50.0

    def test_aggregate_preserves_recent_samples(self, storage):
        """Samples newer than cutoff should not be aggregated."""
        tid = storage.create_target("Test", "1.1.1.1")
        base = 1700000000.0
        samples = [
            {"target_id": tid, "timestamp": base + 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": base + 100, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ]
        storage.save_samples(samples)
        storage.aggregate_raw_to_buckets(tid, cutoff=base + 50, bucket_seconds=60)
        raw = storage.get_samples(tid)
        assert len(raw) == 1
        assert raw[0]["latency_ms"] == 20.0
        agg = storage.get_aggregated_samples(tid, bucket_seconds=60)
        assert len(agg) == 1

    def test_aggregate_single_sample_bucket(self, storage):
        """A bucket with exactly one sample should produce correct aggregates."""
        tid = storage.create_target("Test", "1.1.1.1")
        base = 1700000000.0
        storage.save_samples([
            {"target_id": tid, "timestamp": base + 5, "latency_ms": 42.0, "timeout": False, "probe_method": "tcp"},
        ])
        storage.aggregate_raw_to_buckets(tid, cutoff=base + 100, bucket_seconds=60)
        agg = storage.get_aggregated_samples(tid, bucket_seconds=60)
        assert len(agg) == 1
        bucket = agg[0]
        assert bucket["sample_count"] == 1
        assert bucket["avg_latency_ms"] == 42.0
        assert bucket["min_latency_ms"] == 42.0
        assert bucket["max_latency_ms"] == 42.0
        assert bucket["p95_latency_ms"] == 42.0
        assert bucket["packet_loss_pct"] == 0.0

    def test_aggregate_empty_range_is_noop(self, storage):
        """Aggregation with no old-enough samples should be a no-op."""
        tid = storage.create_target("Test", "1.1.1.1")
        base = 1700000000.0
        storage.save_samples([
            {"target_id": tid, "timestamp": base + 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        created = storage.aggregate_raw_to_buckets(tid, cutoff=base, bucket_seconds=60)
        assert created == 0
        assert len(storage.get_samples(tid)) == 1
        assert len(storage.get_aggregated_samples(tid, bucket_seconds=60)) == 0

    def test_get_aggregated_samples_empty(self, storage):
        """Querying aggregated samples with no data returns empty list."""
        tid = storage.create_target("Test", "1.1.1.1")
        assert storage.get_aggregated_samples(tid, bucket_seconds=60) == []

    def test_reaggregate_60s_to_300s(self, storage):
        """60s buckets older than cutoff should be re-aggregated into 300s buckets."""
        tid = storage.create_target("Test", "1.1.1.1")
        # Align base to a 300s boundary so all 5 x 60s buckets land in one window
        base = (1700000000 // 300) * 300  # 1699999800.0
        # Insert 5 x 60s buckets (covering one 300s window)
        for i in range(5):
            with storage._connect() as conn:
                conn.execute(
                    """INSERT INTO connection_samples_aggregated
                       (target_id, bucket_start, bucket_seconds,
                        avg_latency_ms, min_latency_ms, max_latency_ms,
                        p95_latency_ms, packet_loss_pct, sample_count)
                       VALUES (?, ?, 60, ?, ?, ?, ?, ?, ?)""",
                    (tid, base + i * 60, (i + 1) * 10.0, (i + 1) * 5.0,
                     (i + 1) * 20.0, (i + 1) * 18.0, 0.0, 12),
                )

        storage.reaggregate_buckets(tid, cutoff=base + 400,
                                     source_seconds=60, target_seconds=300)

        # 60s buckets should be deleted
        agg_60 = storage.get_aggregated_samples(tid, bucket_seconds=60)
        assert len(agg_60) == 0

        # 300s bucket should exist
        agg_300 = storage.get_aggregated_samples(tid, bucket_seconds=300)
        assert len(agg_300) == 1
        bucket = agg_300[0]
        assert bucket["sample_count"] == 60  # 5 * 12
        assert bucket["min_latency_ms"] == 5.0   # min of all min values
        assert bucket["max_latency_ms"] == 100.0  # max of all max values
        assert bucket["p95_latency_ms"] == 90.0   # max of all p95 values

    def test_reaggregate_all_timeout_sources(self, storage):
        """Re-aggregation of all-timeout buckets should produce null latencies."""
        tid = storage.create_target("Test", "1.1.1.1")
        # Align base to a 300s boundary so all 3 x 60s buckets land in one window
        base = (1700000000 // 300) * 300  # 1699999800.0
        with storage._connect() as conn:
            for i in range(3):
                conn.execute(
                    """INSERT INTO connection_samples_aggregated
                       (target_id, bucket_start, bucket_seconds,
                        avg_latency_ms, min_latency_ms, max_latency_ms,
                        p95_latency_ms, packet_loss_pct, sample_count)
                       VALUES (?, ?, 60, NULL, NULL, NULL, NULL, 100.0, 10)""",
                    (tid, base + i * 60),
                )

        storage.reaggregate_buckets(tid, cutoff=base + 300,
                                     source_seconds=60, target_seconds=300)
        agg = storage.get_aggregated_samples(tid, bucket_seconds=300)
        assert len(agg) == 1
        assert agg[0]["avg_latency_ms"] is None
        assert agg[0]["packet_loss_pct"] == 100.0
        assert agg[0]["sample_count"] == 30

    def test_aggregate_full_cascade(self, storage):
        """aggregate() should cascade: raw -> 60s -> 300s -> 3600s."""
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()

        # Insert raw samples at different ages
        samples = []
        # 8 days ago (should become 60s buckets)
        for i in range(10):
            samples.append({
                "target_id": tid,
                "timestamp": now - 8 * 86400 + i * 5,
                "latency_ms": 10.0 + i,
                "timeout": False,
                "probe_method": "tcp",
            })
        # 35 days ago (should cascade to 300s)
        for i in range(10):
            samples.append({
                "target_id": tid,
                "timestamp": now - 35 * 86400 + i * 5,
                "latency_ms": 20.0 + i,
                "timeout": False,
                "probe_method": "tcp",
            })
        # 100 days ago (should cascade to 3600s)
        for i in range(10):
            samples.append({
                "target_id": tid,
                "timestamp": now - 100 * 86400 + i * 5,
                "latency_ms": 30.0 + i,
                "timeout": False,
                "probe_method": "tcp",
            })
        # Recent (should stay raw)
        samples.append({
            "target_id": tid,
            "timestamp": now - 60,
            "latency_ms": 5.0,
            "timeout": False,
            "probe_method": "tcp",
        })
        storage.save_samples(samples)

        storage.aggregate()

        # Recent raw sample preserved
        raw = storage.get_samples(tid)
        assert len(raw) == 1
        assert raw[0]["latency_ms"] == 5.0

        # 8-day-old data: should be in 60s buckets
        agg_60 = storage.get_aggregated_samples(
            tid, bucket_seconds=60,
            start=now - 9 * 86400, end=now - 7 * 86400,
        )
        assert len(agg_60) >= 1

        # 35-day-old data: should have cascaded through 60s to 300s
        agg_300 = storage.get_aggregated_samples(
            tid, bucket_seconds=300,
            start=now - 36 * 86400, end=now - 30 * 86400,
        )
        assert len(agg_300) >= 1

        # 100-day-old data: should have cascaded through 60s -> 300s -> 3600s
        agg_3600 = storage.get_aggregated_samples(
            tid, bucket_seconds=3600,
            start=now - 101 * 86400, end=now - 90 * 86400,
        )
        assert len(agg_3600) >= 1
