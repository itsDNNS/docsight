"""Tests for SQLite snapshot storage."""

import pytest
from app.storage import SnapshotStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=7)


@pytest.fixture
def sample_analysis():
    return {
        "summary": {"ds_total": 33, "health": "good", "health_issues": []},
        "ds_channels": [{"channel_id": 1, "power": 3.0}],
        "us_channels": [{"channel_id": 1, "power": 42.0}],
    }


class TestSnapshotStorage:
    def test_save_and_list(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis)
        snapshots = storage.get_snapshot_list()
        assert len(snapshots) == 1

    def test_save_multiple(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis)
        storage.save_snapshot(sample_analysis)
        assert len(storage.get_snapshot_list()) == 2

    def test_get_snapshot(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis)
        ts = storage.get_snapshot_list()[0]
        snap = storage.get_snapshot(ts)
        assert snap is not None
        assert snap["summary"]["ds_total"] == 33

    def test_get_nonexistent_snapshot(self, storage):
        assert storage.get_snapshot("2099-01-01T00:00:00") is None

    def test_dates_with_data(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis)
        dates = storage.get_dates_with_data()
        assert len(dates) == 1

    def test_intraday_data(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis)
        ts = storage.get_snapshot_list()[0]
        date = ts[:10]
        intraday = storage.get_intraday_data(date)
        assert len(intraday) >= 1
        assert "health" in intraday[0]

    def test_empty_storage(self, storage):
        assert storage.get_snapshot_list() == []
        assert storage.get_dates_with_data() == []

    def test_unlimited_retention(self, tmp_path, sample_analysis):
        """max_days=0 should keep all snapshots (no cleanup)."""
        db_path = str(tmp_path / "unlimited.db")
        s = SnapshotStorage(db_path, max_days=0)
        s.save_snapshot(sample_analysis)
        s.save_snapshot(sample_analysis)
        assert len(s.get_snapshot_list()) == 2
