"""Tests for UTC migration in SnapshotStorage."""

import os
import sqlite3
import pytest

from app.storage import SnapshotStorage
from app.modules.journal.storage import JournalStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SnapshotStorage(db_path, max_days=7)
    # Ensure journal tables exist (created by journal module)
    JournalStorage(db_path)
    return s


_SNAPSHOT = {"summary_json": '{"health":"good"}', "ds_channels_json": "[]", "us_channels_json": "[]"}


class TestUtcMigration:
    def test_fresh_db_no_error(self, storage):
        """Migration on empty DB should succeed without errors."""
        result = storage.migrate_to_utc("Europe/Berlin")
        assert result is True

    def test_idempotent(self, storage):
        """Second migration call should be skipped."""
        storage.migrate_to_utc("Europe/Berlin")
        result = storage.migrate_to_utc("Europe/Berlin")
        assert result is False

    def test_meta_flag_set(self, storage):
        """Migration should set tz_migrated flag in _docsight_meta."""
        storage.migrate_to_utc("Europe/Berlin")
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM _docsight_meta WHERE key = 'tz_migrated'"
            ).fetchone()
        assert row is not None
        assert "Europe/Berlin" in row[0]

    def test_backup_created(self, storage):
        """Migration should create a .pre_utc_migration backup."""
        storage.migrate_to_utc("Europe/Berlin")
        assert os.path.exists(storage.db_path + ".pre_utc_migration")

    @pytest.mark.parametrize("table,row,tz,expected", [
        # 14:00 CEST (UTC+2) → 12:00 UTC
        ("snapshots", {**_SNAPSHOT, "timestamp": "2026-06-15T14:00:00"}, "Europe/Berlin", "2026-06-15T12:00:00Z"),
        # 13:00 CET (UTC+1) → 12:00 UTC
        ("events", {"timestamp": "2026-01-15T13:00:00", "severity": "info", "event_type": "test", "message": "test event"},
         "Europe/Berlin", "2026-01-15T12:00:00Z"),
        ("snapshots", {**_SNAPSHOT, "timestamp": "2026-01-15T12:00:00"}, "UTC", "2026-01-15T12:00:00Z"),
        # Docker without TZ
        ("snapshots", {**_SNAPSHOT, "timestamp": "2026-01-15T12:00:00"}, "", "2026-01-15T12:00:00Z"),
    ], ids=["snapshot-local", "event-local", "utc", "empty-tz-as-utc"])
    def test_timestamp_converted(self, storage, table, row, tz, expected):
        """Local timestamps are converted to UTC with a Z suffix; UTC or an empty timezone only append Z."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))

        storage.migrate_to_utc(tz)

        with sqlite3.connect(storage.db_path) as conn:
            assert conn.execute(f"SELECT timestamp FROM {table}").fetchone()[0] == expected

    @pytest.mark.parametrize("last_used_at", [None, ""], ids=["null", "empty"])
    def test_missing_values_skipped(self, storage, last_used_at):
        """NULL and empty timestamp values should not be touched."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "hash", "dsk_", "2026-01-15T13:00:00", last_used_at),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT last_used_at FROM api_tokens").fetchone()
        assert row[0] == last_used_at

    def test_already_utc_skipped(self, storage):
        """Timestamps with Z-suffix should not be double-converted."""
        from app.modules.speedtest.storage import SpeedtestStorage
        SpeedtestStorage(storage.db_path)  # ensure table exists
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO speedtest_results (id, timestamp, download_mbps, upload_mbps, "
                "download_human, upload_human, ping_ms, jitter_ms, packet_loss_pct) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "2026-01-15T12:00:00Z", 250.0, 40.0, "250 Mbps", "40 Mbps", 10.0, 1.0, 0.0),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT timestamp FROM speedtest_results").fetchone()
        assert row[0] == "2026-01-15T12:00:00Z"  # unchanged

    def test_journal_timestamps_converted(self, storage):
        """Journal created_at and updated_at should be converted."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO journal_entries (date, title, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("2026-06-15", "Test", "desc", "2026-06-15T14:00:00", "2026-06-15T16:00:00"),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT created_at, updated_at FROM journal_entries").fetchone()
        assert row[0] == "2026-06-15T12:00:00Z"
        assert row[1] == "2026-06-15T14:00:00Z"

    def test_incidents_converted(self, storage):
        """Incident created_at/updated_at should be converted, start_date/end_date untouched."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO incidents (name, status, start_date, end_date, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Test", "open", "2026-06-01", "2026-06-30", "2026-06-15T14:00:00", "2026-06-15T16:00:00"),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT start_date, end_date, created_at, updated_at FROM incidents"
            ).fetchone()
        # Date columns untouched
        assert row[0] == "2026-06-01"
        assert row[1] == "2026-06-30"
        # Timestamp columns converted
        assert row[2] == "2026-06-15T12:00:00Z"
        assert row[3] == "2026-06-15T14:00:00Z"
