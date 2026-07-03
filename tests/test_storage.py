"""Tests for SQLite snapshot storage."""

import json
import sqlite3

import pytest
from app import analyzer
from app.storage import snapshot as snapshot_module
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

    def test_new_snapshot_stores_analysis_metadata(self, storage, sample_analysis, monkeypatch):
        monkeypatch.setattr(snapshot_module, "get_available_app_version", lambda: "2026.7-test")
        orig_thresholds = analyzer._thresholds.copy()
        orig_profile = analyzer._threshold_profile.copy()
        try:
            analyzer.set_thresholds(
                {"downstream_power": {}, "upstream_power": {}, "snr": {}},
                profile_id="test.thresholds_alpha",
                profile_version="1.2.3",
            )

            storage.save_snapshot(sample_analysis)
            ts = storage.get_snapshot_list()[0]
            snap = storage.get_snapshot(ts)
            latest = storage.get_latest_snapshot()
        finally:
            analyzer._thresholds = orig_thresholds
            analyzer._threshold_profile = orig_profile

        assert snap is not None
        assert latest is not None
        assert snap["analysis_meta"] == latest["analysis_meta"]
        assert snap["analysis_meta"] == {
            "analyzer_schema": analyzer.ANALYZER_SCHEMA_VERSION,
            "app_version": "2026.7-test",
            "threshold_profile": {
                "id": "test.thresholds_alpha",
                "version": "1.2.3",
            },
        }

    def test_unavailable_app_version_is_recorded_as_null(self, storage, sample_analysis, monkeypatch):
        monkeypatch.setattr(snapshot_module, "get_available_app_version", lambda: None)

        storage.save_snapshot(sample_analysis)
        ts = storage.get_snapshot_list()[0]
        snap = storage.get_snapshot(ts)

        assert snap is not None
        assert snap["analysis_meta"]["app_version"] is None

    def test_new_snapshot_can_store_raw_payload(self, storage, sample_analysis):
        raw_payload = {
            "docsis": "3.1",
            "downstream": [{"channelID": 1, "powerLevel": "3.0"}],
            "upstream": [{"channelID": 1, "powerLevel": "42.0"}],
        }

        storage.save_snapshot(sample_analysis, raw_data=raw_payload)
        ts = storage.get_snapshot_list()[0]
        snap = storage.get_snapshot(ts)
        latest = storage.get_latest_snapshot()

        assert snap is not None
        assert latest is not None
        assert snap["raw_data"] == raw_payload
        assert latest["raw_data"] == raw_payload
        assert storage.get_snapshot_raw_data(ts) == raw_payload

    def test_raw_payload_redacts_sensitive_keys(self, storage, sample_analysis):
        raw_payload = {
            "docsis": "3.1",
            "password": "secret-value",
            "nested": {"sessionToken": "token-value"},
            "downstream": [],
            "upstream": [],
        }

        storage.save_snapshot(sample_analysis, raw_data=raw_payload)
        ts = storage.get_snapshot_list()[0]
        raw = storage.get_snapshot_raw_data(ts)

        assert raw is not None
        assert raw["password"] == "[REDACTED]"
        assert raw["nested"]["sessionToken"] == "[REDACTED]"

    def test_oversized_raw_payload_is_not_stored(self, storage, sample_analysis, monkeypatch):
        monkeypatch.setattr(snapshot_module, "MAX_RAW_SNAPSHOT_BYTES", 16)

        storage.save_snapshot(sample_analysis, raw_data={"downstream": [{"frequency": "x" * 100}], "upstream": []})
        ts = storage.get_snapshot_list()[0]
        snap = storage.get_snapshot(ts)

        assert snap is not None
        assert snap["raw_data"] is None

    def test_old_snapshot_rows_read_with_null_analysis_metadata(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE snapshots ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "timestamp TEXT NOT NULL, "
                "summary_json TEXT NOT NULL, "
                "ds_channels_json TEXT NOT NULL, "
                "us_channels_json TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "INSERT INTO snapshots "
                "(timestamp, summary_json, ds_channels_json, us_channels_json) "
                "VALUES (?, ?, ?, ?)",
                ("2026-07-02T00:00:00Z", json.dumps({"ds_total": 1}), "[]", "[]"),
            )

        storage = SnapshotStorage(db_path, max_days=7)
        snap = storage.get_snapshot("2026-07-02T00:00:00Z")

        assert snap is not None
        assert snap["analysis_meta"] is None
        assert snap["raw_data"] is None
        with sqlite3.connect(storage.db_path) as conn:
            snapshot_cols = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
            meta = conn.execute(
                "SELECT value FROM _docsight_meta WHERE key = 'schema_version'"
            ).fetchone()

        assert {"is_demo", "raw_json", "analysis_meta_json"}.issubset(snapshot_cols)
        assert meta == ("2",)

    def test_storage_schema_creates_query_indexes(self, storage):
        with sqlite3.connect(storage.db_path) as conn:
            event_indexes = {row[1] for row in conn.execute("PRAGMA index_list(events)")}
            snapshot_indexes = {row[1] for row in conn.execute("PRAGMA index_list(snapshots)")}
            meta = conn.execute(
                "SELECT value FROM _docsight_meta WHERE key = 'schema_version'"
            ).fetchone()

        assert "idx_events_type_ts" in event_indexes
        assert "idx_snapshots_ts_id" in snapshot_indexes
        assert meta == ("2",)

    def test_save_snapshot_surfaces_storage_errors(self, tmp_path, storage, sample_analysis):
        storage.db_path = str(tmp_path)

        with pytest.raises(sqlite3.Error):
            storage.save_snapshot(sample_analysis)

    def test_threshold_profile_change_applies_to_subsequent_snapshots(self, storage, sample_analysis, monkeypatch):
        monkeypatch.setattr(snapshot_module, "get_available_app_version", lambda: "2026.7-test")
        orig_thresholds = analyzer._thresholds.copy()
        orig_profile = analyzer._threshold_profile.copy()
        try:
            analyzer.set_thresholds({}, profile_id="test.thresholds_alpha", profile_version="1.0.0")
            storage.save_snapshot(sample_analysis)
            analyzer.set_thresholds({}, profile_id="test.thresholds_beta", profile_version="2.0.0")
            storage.save_snapshot(sample_analysis)
        finally:
            analyzer._thresholds = orig_thresholds
            analyzer._threshold_profile = orig_profile

        with sqlite3.connect(storage.db_path) as conn:
            rows = conn.execute(
                "SELECT analysis_meta_json FROM snapshots ORDER BY id"
            ).fetchall()

        first = json.loads(rows[0][0])
        second = json.loads(rows[1][0])
        assert first["threshold_profile"] == {
            "id": "test.thresholds_alpha",
            "version": "1.0.0",
        }
        assert second["threshold_profile"] == {
            "id": "test.thresholds_beta",
            "version": "2.0.0",
        }

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

    def test_cleanup_preserves_snapshots_and_events_inside_incident_windows(self, tmp_path):
        db_path = str(tmp_path / "retention.db")
        storage = SnapshotStorage(db_path, max_days=1)
        summary = json.dumps({"health": "good", "errors_supported": False})
        channels = json.dumps([])
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE incidents ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'open', "
                "start_date TEXT, "
                "end_date TEXT, "
                "created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, "
                "is_demo INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            conn.execute(
                "INSERT INTO incidents (name, start_date, end_date, created_at, updated_at) "
                "VALUES ('Protected incident', '2020-01-01', '2020-01-02', '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')"
            )
            for ts in ("2019-12-31T12:00:00Z", "2020-01-01T12:00:00Z"):
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) "
                    "VALUES (?, ?, ?, ?)",
                    (ts, summary, channels, channels),
                )
                conn.execute(
                    "INSERT INTO events (timestamp, severity, event_type, message, details) "
                    "VALUES (?, 'warning', 'error_spike', 'test', NULL)",
                    (ts,),
                )

        storage._cleanup()

        with sqlite3.connect(db_path) as conn:
            snapshots = [row[0] for row in conn.execute("SELECT timestamp FROM snapshots ORDER BY timestamp")]
            events = [row[0] for row in conn.execute("SELECT timestamp FROM events ORDER BY timestamp")]

        assert snapshots == ["2020-01-01T12:00:00Z"]
        assert events == ["2020-01-01T12:00:00Z"]


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
