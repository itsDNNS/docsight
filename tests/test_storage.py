"""Tests for SQLite snapshot storage."""

import json
import sqlite3

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

    def test_intraday_data(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis)
        ts = storage.get_snapshot_list()[0]
        date = ts[:10]
        intraday = storage.get_intraday_data(date)
        assert len(intraday) >= 1
        assert "health" in intraday[0]

    def test_trend_data_normalizes_unsupported_zero_error_counters(self, storage, sample_analysis):
        sample_analysis["summary"].update({
            "errors_supported": False,
            "ds_correctable_errors": 0,
            "ds_uncorrectable_errors": 0,
        })
        storage.save_snapshot(sample_analysis)
        ts = storage.get_snapshot_list()[0]
        date = ts[:10]

        intraday = storage.get_intraday_data(date)
        summary_range = storage.get_summary_range(date, date)

        snapshot = storage.get_snapshot(ts)
        range_data = storage.get_range_data(ts, ts)
        closest = storage.get_closest_snapshot(ts)

        assert intraday[0]["ds_correctable_errors"] is None
        assert intraday[0]["ds_uncorrectable_errors"] is None
        assert summary_range[0]["ds_correctable_errors"] is None
        assert summary_range[0]["ds_uncorrectable_errors"] is None
        assert snapshot["summary"]["ds_correctable_errors"] is None
        assert snapshot["summary"]["ds_uncorrectable_errors"] is None
        assert range_data[0]["summary"]["ds_correctable_errors"] is None
        assert range_data[0]["summary"]["ds_uncorrectable_errors"] is None
        assert closest["summary"]["ds_correctable_errors"] is None
        assert closest["summary"]["ds_uncorrectable_errors"] is None

    def test_trend_data_preserves_supported_zero_error_counters(self, storage, sample_analysis):
        sample_analysis["summary"].update({
            "errors_supported": True,
            "ds_correctable_errors": 0,
            "ds_uncorrectable_errors": 0,
        })
        storage.save_snapshot(sample_analysis)
        ts = storage.get_snapshot_list()[0]
        date = ts[:10]

        intraday = storage.get_intraday_data(date)

        assert intraday[0]["ds_correctable_errors"] == 0
        assert intraday[0]["ds_uncorrectable_errors"] == 0

    def test_summary_trends_unwrap_aggregate_uint32_counter_wrap(self, storage):
        summaries = [
            ("2026-06-01T10:00:00Z", 4_626_495_351),
            ("2026-06-01T10:01:00Z", 332_692_254),
            ("2026-06-01T10:02:00Z", 333_958_096),
        ]
        with sqlite3.connect(storage.db_path) as conn:
            for ts, correctable_errors in summaries:
                conn.execute(
                    "INSERT INTO snapshots "
                    "(timestamp, summary_json, ds_channels_json, us_channels_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        ts,
                        json.dumps({
                            "errors_supported": True,
                            "ds_correctable_errors": correctable_errors,
                            "ds_uncorrectable_errors": 0,
                        }),
                        "[]",
                        "[]",
                    ),
                )

        intraday = storage.get_intraday_data("2026-06-01")
        summary_range = storage.get_summary_range("2026-06-01", "2026-06-01")
        range_data = storage.get_range_data(
            "2026-06-01T10:00:00Z",
            "2026-06-01T10:02:00Z",
        )

        expected = [4_626_495_351, 4_627_659_550, 4_628_925_392]
        assert [row["ds_correctable_errors"] for row in intraday] == expected
        assert [row["ds_uncorrectable_errors"] for row in intraday] == [0, 0, 0]
        assert [row["ds_correctable_errors"] for row in summary_range] == expected
        assert [row["ds_uncorrectable_errors"] for row in summary_range] == [0, 0, 0]
        assert [row["summary"]["ds_correctable_errors"] for row in range_data] == expected
        assert [row["summary"]["ds_uncorrectable_errors"] for row in range_data] == [0, 0, 0]

    def test_range_data_uses_summary_only_for_unwrap_anchor_rows(self, storage):
        """Historical anchor rows initialize unwrap without loading channel payloads."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots "
                "(timestamp, summary_json, ds_channels_json, us_channels_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    "2026-05-31T23:59:00Z",
                    json.dumps({
                        "errors_supported": True,
                        "ds_correctable_errors": 4_200_000_000,
                        "ds_uncorrectable_errors": 0,
                    }),
                    "not-json-anchor-ds",
                    "not-json-anchor-us",
                ),
            )
            conn.execute(
                "INSERT INTO snapshots "
                "(timestamp, summary_json, ds_channels_json, us_channels_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    "2026-06-01T00:00:00Z",
                    json.dumps({
                        "errors_supported": True,
                        "ds_correctable_errors": 500_000_000,
                        "ds_uncorrectable_errors": 0,
                    }),
                    json.dumps([{"channel_id": 1}]),
                    json.dumps([{"channel_id": 2}]),
                ),
            )

        range_data = storage.get_range_data(
            "2026-06-01T00:00:00Z",
            "2026-06-01T00:00:00Z",
        )

        assert len(range_data) == 1
        assert range_data[0]["timestamp"] == "2026-06-01T00:00:00Z"
        assert range_data[0]["summary"]["ds_correctable_errors"] == 4_794_967_296
        assert range_data[0]["ds_channels"] == [{"channel_id": 1}]
        assert range_data[0]["us_channels"] == [{"channel_id": 2}]

    def test_empty_storage(self, storage):
        assert storage.get_snapshot_list() == []

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
