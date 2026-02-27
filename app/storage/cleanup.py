"""Cleanup, purge, timezone, and UTC migration mixin."""

import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta

from ..tz import utc_now, utc_cutoff, local_to_utc

log = logging.getLogger("docsis.storage")


class CleanupMixin:

    # ── Timezone ──

    def set_timezone(self, tz_name):
        """Set the timezone name used for local conversions on read."""
        self.tz_name = tz_name

    # ── UTC Migration ──

    _TIMESTAMP_COLUMNS = [
        ("snapshots", "timestamp"),
        ("events", "timestamp"),
        ("journal_entries", "created_at"),
        ("journal_entries", "updated_at"),
        ("journal_attachments", "created_at"),
        ("incidents", "created_at"),
        ("incidents", "updated_at"),
        ("speedtest_results", "timestamp"),
        ("bnetz_measurements", "timestamp"),
        ("api_tokens", "created_at"),
        ("api_tokens", "last_used_at"),
        ("bqm_graphs", "timestamp"),
        ("weather_data", "timestamp"),
    ]

    def migrate_to_utc(self, tz_name):
        """One-time migration: convert all timestamp columns from local time to UTC.

        - Idempotent: checks _docsight_meta for 'tz_migrated' flag
        - Creates a safety backup before migration
        - Runs in a single transaction (automatic rollback on error)
        - Skips NULL, empty, and already-UTC (Z-suffix) values
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM _docsight_meta WHERE key = 'tz_migrated'"
            ).fetchone()
            if row:
                log.debug("UTC migration already completed (%s), skipping", row[0])
                return False

        # Safety backup
        backup_path = self.db_path + ".pre_utc_migration"
        if not os.path.exists(backup_path):
            shutil.copy2(self.db_path, backup_path)
            log.info("UTC migration: backup created at %s", backup_path)

        migrated_count = 0
        with sqlite3.connect(self.db_path) as conn:
            for table, column in self._TIMESTAMP_COLUMNS:
                # Check table and column exist
                try:
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                except Exception:
                    continue
                if column not in cols:
                    continue

                rows = conn.execute(
                    f"SELECT rowid, [{column}] FROM [{table}] "
                    f"WHERE [{column}] IS NOT NULL AND [{column}] != '' AND [{column}] NOT LIKE '%Z'",
                ).fetchall()

                for rowid, ts_val in rows:
                    try:
                        utc_val = local_to_utc(ts_val, tz_name)
                        conn.execute(
                            f"UPDATE [{table}] SET [{column}] = ? WHERE rowid = ?",
                            (utc_val, rowid),
                        )
                        migrated_count += 1
                    except (ValueError, KeyError) as e:
                        log.warning(
                            "UTC migration: skipped %s.%s rowid=%d value=%r: %s",
                            table, column, rowid, ts_val, e,
                        )

            # Mark migration as done
            conn.execute(
                "INSERT INTO _docsight_meta (key, value) VALUES (?, ?)",
                ("tz_migrated", f"{tz_name}|{utc_now()}"),
            )

        log.info(
            "UTC migration complete: %d values converted (timezone: %s)",
            migrated_count, tz_name or "UTC",
        )
        return True

    def purge_demo_data(self):
        """Delete all rows with is_demo=1 from all demo-seeded tables.

        Order matters: delete attachments for demo journal entries first,
        unassign entries from demo incidents, then delete from each table.
        """
        with self._connect() as conn:
            # 1. Delete attachments belonging to demo journal entries
            conn.execute(
                "DELETE FROM journal_attachments WHERE entry_id IN "
                "(SELECT id FROM journal_entries WHERE is_demo = 1)"
            )
            # 2. Unassign entries from demo incidents (so they become orphan-free)
            conn.execute(
                "UPDATE journal_entries SET incident_id = NULL WHERE incident_id IN "
                "(SELECT id FROM incidents WHERE is_demo = 1)"
            )
            # 3. Delete from each demo-seeded table
            tables = ["journal_entries", "incidents", "events", "snapshots",
                       "speedtest_results", "bqm_graphs", "bnetz_measurements",
                       "weather_data"]
            total = 0
            for tbl in tables:
                deleted = conn.execute(
                    f"DELETE FROM {tbl} WHERE is_demo = 1"
                ).rowcount
                if deleted:
                    log.info("Purged %d demo rows from %s", deleted, tbl)
                    total += deleted
        return total

    def _cleanup(self):
        """Delete snapshots, BQM graphs, and events older than max_days. 0 = keep all."""
        if self.max_days <= 0:
            return
        cutoff = utc_cutoff(days=self.max_days)
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM snapshots WHERE timestamp < ?", (cutoff,)
            ).rowcount
        if deleted:
            log.info("Cleaned up %d old snapshots (before %s)", deleted, cutoff)
        from ..tz import local_today
        tz = getattr(self, 'tz_name', '')
        today = local_today(tz)
        cutoff_date = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=self.max_days)).strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            bqm_deleted = conn.execute(
                "DELETE FROM bqm_graphs WHERE date < ?", (cutoff_date,)
            ).rowcount
        if bqm_deleted:
            log.info("Cleaned up %d old BQM graphs (before %s)", bqm_deleted, cutoff_date)
        with sqlite3.connect(self.db_path) as conn:
            weather_deleted = conn.execute(
                "DELETE FROM weather_data WHERE timestamp < ?", (cutoff,)
            ).rowcount
        if weather_deleted:
            log.info("Cleaned up %d old weather records (before %s)", weather_deleted, cutoff)
        events_deleted = self.delete_old_events(self.max_days)
        if events_deleted:
            log.info("Cleaned up %d old events (before %s)", events_deleted, cutoff)
