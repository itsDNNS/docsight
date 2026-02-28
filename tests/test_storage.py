"""Tests for SQLite snapshot storage."""

import pytest
from app.storage import SnapshotStorage
from app.modules.bnetz.storage import BnetzStorage


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


@pytest.fixture
def sample_bnetz_parsed():
    return {
        "date": "2025-02-04",
        "provider": "Vodafone",
        "tariff": "GigaZuhause 1000 Kabel",
        "download_max": 1000.0,
        "download_normal": 850.0,
        "download_min": 600.0,
        "upload_max": 50.0,
        "upload_normal": 35.0,
        "upload_min": 15.0,
        "measurement_count": 30,
        "measurements_download": [{"nr": 1, "mbps": 883.29}],
        "measurements_upload": [{"nr": 1, "mbps": 5.04}],
        "download_measured_avg": 748.04,
        "upload_measured_avg": 7.85,
        "verdict_download": "deviation",
        "verdict_upload": "deviation",
    }


class TestBnetzStorage:
    @pytest.fixture
    def bnetz_storage(self, storage):
        return BnetzStorage(storage.db_path)

    def test_save_and_list(self, bnetz_storage, sample_bnetz_parsed):
        mid = bnetz_storage.save_bnetz_measurement(sample_bnetz_parsed, b"%PDF-fake")
        assert mid > 0
        measurements = bnetz_storage.get_bnetz_measurements()
        assert len(measurements) == 1
        assert measurements[0]["provider"] == "Vodafone"
        assert measurements[0]["verdict_download"] == "deviation"

    def test_get_pdf(self, bnetz_storage, sample_bnetz_parsed):
        mid = bnetz_storage.save_bnetz_measurement(sample_bnetz_parsed, b"%PDF-test-content")
        pdf = bnetz_storage.get_bnetz_pdf(mid)
        assert pdf == b"%PDF-test-content"

    def test_get_pdf_not_found(self, bnetz_storage):
        assert bnetz_storage.get_bnetz_pdf(9999) is None

    def test_delete(self, bnetz_storage, sample_bnetz_parsed):
        mid = bnetz_storage.save_bnetz_measurement(sample_bnetz_parsed, b"%PDF-fake")
        assert bnetz_storage.delete_bnetz_measurement(mid) is True
        assert bnetz_storage.get_bnetz_measurements() == []

    def test_delete_not_found(self, bnetz_storage):
        assert bnetz_storage.delete_bnetz_measurement(9999) is False

    def test_get_latest(self, bnetz_storage, sample_bnetz_parsed):
        bnetz_storage.save_bnetz_measurement(sample_bnetz_parsed, b"%PDF-1")
        latest = bnetz_storage.get_latest_bnetz()
        assert latest is not None
        assert latest["provider"] == "Vodafone"

    def test_get_latest_empty(self, bnetz_storage):
        assert bnetz_storage.get_latest_bnetz() is None

    def test_in_range(self, bnetz_storage, sample_bnetz_parsed):
        bnetz_storage.save_bnetz_measurement(sample_bnetz_parsed, b"%PDF-1")
        results = bnetz_storage.get_bnetz_in_range("2000-01-01T00:00:00", "2099-12-31T23:59:59")
        assert len(results) == 1

    def test_correlation_includes_bnetz(self, storage, bnetz_storage, sample_bnetz_parsed):
        bnetz_storage.save_bnetz_measurement(sample_bnetz_parsed, b"%PDF-1")
        timeline = storage.get_correlation_timeline(
            "2000-01-01T00:00:00", "2099-12-31T23:59:59", sources={"bnetz"}
        )
        assert len(timeline) == 1
        assert timeline[0]["source"] == "bnetz"
