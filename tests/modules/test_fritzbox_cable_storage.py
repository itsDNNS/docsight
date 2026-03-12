"""Tests for fritzbox_cable segment utilization storage."""

import os
import tempfile
import pytest
from app.storage.segment_utilization import SegmentUtilizationStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SegmentUtilizationStorage(db_path)


class TestSave:
    def test_save_stores_record(self, storage):
        storage.save(6.2, 11.4, 0.05, 0.17)
        rows = storage.get_latest(1)
        assert len(rows) == 1
        assert rows[0]["ds_total"] == pytest.approx(6.2)
        assert rows[0]["us_total"] == pytest.approx(11.4)
        assert rows[0]["ds_own"] == pytest.approx(0.05)
        assert rows[0]["us_own"] == pytest.approx(0.17)
        assert "timestamp" in rows[0]

    def test_save_allows_nulls(self, storage):
        storage.save(None, None, None, None)
        rows = storage.get_latest(1)
        assert len(rows) == 1
        assert rows[0]["ds_total"] is None


class TestGetRange:
    def test_get_range_filters_by_time(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 1.0, 2.0, 0.1, 0.2)
        storage.save_at("2026-03-09T10:01:00Z", 3.0, 4.0, 0.3, 0.4)
        rows = storage.get_latest(10)
        assert len(rows) == 2
        start = "2000-01-01T00:00:00Z"
        end = "2099-01-01T00:00:00Z"
        ranged = storage.get_range(start, end)
        assert len(ranged) == 2

    def test_get_range_accepts_legacy_space_separated_query_timestamps(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 1.0, 2.0, 0.1, 0.2)
        storage.save_at("2026-03-09T10:01:00Z", 3.0, 4.0, 0.3, 0.4)
        ranged = storage.get_range("2026-03-09 09:59:00Z", "2026-03-09 10:00:30Z")
        assert len(ranged) == 1
        assert ranged[0]["ds_total"] == pytest.approx(1.0)

    def test_get_range_empty(self, storage):
        assert storage.get_range("2000-01-01T00:00:00Z", "2000-01-02T00:00:00Z") == []


class TestGetLatest:
    def test_get_latest_returns_most_recent_first(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 1.0, 2.0, 0.1, 0.2)
        storage.save_at("2026-03-09T10:01:00Z", 3.0, 4.0, 0.3, 0.4)
        rows = storage.get_latest(1)
        assert rows[0]["ds_total"] == pytest.approx(3.0)

    def test_get_latest_default_one(self, storage):
        storage.save(1.0, 2.0, 0.1, 0.2)
        rows = storage.get_latest()
        assert len(rows) == 1


class TestGetStats:
    def test_get_stats_computes_aggregates(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 5.0, 10.0, 0.1, 0.5)
        storage.save_at("2026-03-09T10:01:00Z", 15.0, 30.0, 0.3, 1.5)
        stats = storage.get_stats("2000-01-01T00:00:00Z", "2099-01-01T00:00:00Z")
        assert stats["ds_total_avg"] == pytest.approx(10.0)
        assert stats["ds_total_min"] == pytest.approx(5.0)
        assert stats["ds_total_max"] == pytest.approx(15.0)
        assert stats["us_total_avg"] == pytest.approx(20.0)
        assert stats["count"] == 2

    def test_get_stats_empty(self, storage):
        stats = storage.get_stats("2000-01-01T00:00:00Z", "2000-01-02T00:00:00Z")
        assert stats["count"] == 0


class TestDownsample:
    def test_downsample_aggregates_old_samples(self, storage):
        """Samples older than fine_after_days get aggregated into buckets."""
        # Insert 5 samples within the same 5-min bucket (14:00-14:04)
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 12.0, 22.0, 1.2, 2.2)
        storage.save_at("2020-01-01T14:02:00Z", 14.0, 24.0, 1.4, 2.4)
        storage.save_at("2020-01-01T14:03:00Z", 16.0, 26.0, 1.6, 2.6)
        storage.save_at("2020-01-01T14:04:00Z", 18.0, 28.0, 1.8, 2.8)
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 5

        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 4  # 5 rows -> 1 averaged row

        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 1
        assert rows[0]["timestamp"] == "2020-01-01T14:00:00Z"
        assert rows[0]["ds_total"] == pytest.approx(14.0)  # avg(10,12,14,16,18)
        assert rows[0]["us_total"] == pytest.approx(24.0)

    def test_downsample_leaves_single_sample_buckets(self, storage):
        """Buckets with only 1 sample are not touched."""
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:05:00Z", 12.0, 22.0, 1.2, 2.2)

        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 0
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 2

    def test_downsample_preserves_recent_data(self, storage):
        """Samples newer than fine_after_days are not downsampled."""
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 12.0, 22.0, 1.2, 2.2)
        # Use a cutoff in the past so both samples are "recent"
        removed = storage.downsample(fine_after_days=9999, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 0
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 2

    def test_downsample_coarse_tier(self, storage):
        """Coarse tier aggregates into 15-min buckets."""
        for m in range(15):
            storage.save_at(f"2020-01-01T14:{m:02d}:00Z", float(m), float(m * 2), 0.1, 0.2)
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 15

        removed = storage.downsample(fine_after_days=9999, fine_bucket_min=5,
                                     coarse_after_days=0, coarse_bucket_min=15)
        assert removed == 14  # 15 -> 1
        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 1
        assert rows[0]["timestamp"] == "2020-01-01T14:00:00Z"

    def test_downsample_multiple_buckets(self, storage):
        """Multiple buckets are each aggregated independently."""
        # Bucket 14:00
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 20.0, 30.0, 2.0, 3.0)
        # Bucket 14:05
        storage.save_at("2020-01-01T14:05:00Z", 30.0, 40.0, 3.0, 4.0)
        storage.save_at("2020-01-01T14:06:00Z", 40.0, 50.0, 4.0, 5.0)

        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 2  # 2 rows removed (4 -> 2)
        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 2
        assert rows[0]["ds_total"] == pytest.approx(15.0)  # avg(10,20)
        assert rows[1]["ds_total"] == pytest.approx(35.0)  # avg(30,40)

    def test_downsample_empty_db(self, storage):
        assert storage.downsample() == 0

    def test_downsample_idempotent(self, storage):
        """Running downsample twice produces the same result."""
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 20.0, 30.0, 2.0, 3.0)

        storage.downsample(fine_after_days=0, fine_bucket_min=5,
                           coarse_after_days=9999, coarse_bucket_min=15)
        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 0
        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 1


class TestCleanup:
    def test_cleanup_removes_old_records(self, storage):
        import sqlite3
        conn = sqlite3.connect(storage.db_path)
        conn.execute(
            "INSERT INTO segment_utilization (timestamp, ds_total, us_total, ds_own, us_own) VALUES (?, ?, ?, ?, ?)",
            ("2020-01-01T00:00:00Z", 1.0, 2.0, 0.1, 0.2),
        )
        conn.commit()
        conn.close()
        storage.save(5.0, 10.0, 0.1, 0.5)
        deleted = storage.cleanup(days=365)
        assert deleted >= 1
        assert len(storage.get_latest(10)) == 1
