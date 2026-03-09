"""Tests for fritzbox_cable segment utilization storage."""

import os
import tempfile
import pytest
from app.modules.fritzbox_cable.storage import SegmentUtilizationStorage


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
