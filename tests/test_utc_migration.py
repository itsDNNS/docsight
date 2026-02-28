"""Tests for UTC migration in SnapshotStorage."""

import os
import sqlite3
import pytest

from app.storage import SnapshotStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=7)


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

    def test_snapshot_timestamps_converted(self, storage):
        """Local snapshot timestamps should get Z-suffix after migration."""
        # Insert pre-migration local timestamp
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) "
                "VALUES (?, ?, ?, ?)",
                ("2026-06-15T14:00:00", '{"health":"good"}', "[]", "[]"),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT timestamp FROM snapshots").fetchone()
        # 14:00 CEST (UTC+2) → 12:00 UTC
        assert row[0] == "2026-06-15T12:00:00Z"

    def test_event_timestamps_converted(self, storage):
        """Event timestamps should be converted to UTC."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO events (timestamp, severity, event_type, message) "
                "VALUES (?, ?, ?, ?)",
                ("2026-01-15T13:00:00", "info", "test", "test event"),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT timestamp FROM events").fetchone()
        # 13:00 CET (UTC+1) → 12:00 UTC
        assert row[0] == "2026-01-15T12:00:00Z"

    def test_null_values_skipped(self, storage):
        """NULL timestamp values should not be touched."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "hash", "dsk_", "2026-01-15T13:00:00", None),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT last_used_at FROM api_tokens").fetchone()
        assert row[0] is None

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

    def test_empty_values_skipped(self, storage):
        """Empty string timestamps should not be touched."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "hash", "dsk_", "2026-01-15T13:00:00", ""),
            )

        storage.migrate_to_utc("Europe/Berlin")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT last_used_at FROM api_tokens").fetchone()
        assert row[0] == ""

    def test_utc_timezone(self, storage):
        """With UTC timezone, values should just get Z-suffix."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) "
                "VALUES (?, ?, ?, ?)",
                ("2026-01-15T12:00:00", '{"health":"good"}', "[]", "[]"),
            )

        storage.migrate_to_utc("UTC")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT timestamp FROM snapshots").fetchone()
        assert row[0] == "2026-01-15T12:00:00Z"

    def test_empty_tz_treats_as_utc(self, storage):
        """Empty timezone string (Docker without TZ) should just append Z."""
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) "
                "VALUES (?, ?, ?, ?)",
                ("2026-01-15T12:00:00", '{"health":"good"}', "[]", "[]"),
            )

        storage.migrate_to_utc("")

        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute("SELECT timestamp FROM snapshots").fetchone()
        assert row[0] == "2026-01-15T12:00:00Z"

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
