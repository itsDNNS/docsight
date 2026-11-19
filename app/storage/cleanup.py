"""Cleanup, purge, timezone, and UTC migration mixin."""

import logging
import os
import shutil
from datetime import datetime, timedelta

from ..tz import local_today, utc_now, utc_cutoff, local_to_utc, local_date_to_utc_range
from .migrations import table_columns, table_exists

log = logging.getLogger("docsis.storage")


class CleanupMethods:

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
        ("smart_capture_executions", "created_at"),
        ("smart_capture_executions", "fired_at"),
        ("smart_capture_executions", "completed_at"),
        ("smart_capture_executions", "claimed_at"),
    ]

    def migrate_to_utc(self, tz_name):
        """One-time migration: convert all timestamp columns from local time to UTC.

        - Idempotent: checks _docsight_meta for 'tz_migrated' flag
        - Creates a safety backup before migration
        - Runs in a single transaction (automatic rollback on error)
        - Skips NULL, empty, and already-UTC (Z-suffix) values
        """
        with self._read() as conn:
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
        with self._write() as conn:
            for table, column in self._TIMESTAMP_COLUMNS:
                if column not in table_columns(conn, table):
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

    def _incident_retention_ranges(self, conn):
        """Return UTC timestamp ranges for explicit incident windows."""
        # Without the journal module, or with a preserved pre-journal table, there are no windows.
        if not {"start_date", "end_date"} <= table_columns(conn, "incidents"):
            return []
        rows = conn.execute(
            "SELECT start_date, COALESCE(end_date, '') FROM incidents "
            "WHERE start_date IS NOT NULL AND start_date != ''"
        ).fetchall()

        ranges = []
        tz = self.tz_name
        today = local_today(tz)
        for start_date, end_date in rows:
            try:
                start_ts, _ = local_date_to_utc_range(start_date, tz)
                _, end_ts = local_date_to_utc_range(end_date or today, tz)
            except Exception as exc:
                log.warning("Retention skipped invalid incident window %r..%r: %s", start_date, end_date, exc)
                continue
            ranges.append((start_ts, end_ts))
        return ranges

    def _delete_expired_unprotected_rows(self, conn, table, timestamp_column, cutoff):
        """Delete old rows unless their timestamp lies in an incident window."""
        ranges = self._incident_retention_ranges(conn)
        if not ranges:
            return conn.execute(
                f"DELETE FROM {table} WHERE {timestamp_column} < ?",
                (cutoff,),
            ).rowcount

        protected = " OR ".join(
            f"({timestamp_column} >= ? AND {timestamp_column} <= ?)"
            for _ in ranges
        )
        params = [cutoff]
        for start_ts, end_ts in ranges:
            params.extend([start_ts, end_ts])
        return conn.execute(
            f"DELETE FROM {table} WHERE {timestamp_column} < ? AND NOT ({protected})",
            params,
        ).rowcount

    def purge_demo_data(self):
        """Delete all rows with is_demo=1 from all demo-seeded tables.

        Order matters: delete attachments for demo journal entries first,
        unassign entries from demo incidents, then delete from each table.
        """
        with self._write() as conn:
            # Journal tables are missing without the journal module, and a preserved
            # older schema may lack a column; an unknown inner column would bind to the outer table.
            journal_columns = table_columns(conn, "journal_entries")
            # 1. Delete attachments belonging to demo journal entries
            if {"id", "is_demo"} <= journal_columns and "entry_id" in table_columns(conn, "journal_attachments"):
                conn.execute(
                    "DELETE FROM journal_attachments WHERE entry_id IN "
                    "(SELECT journal_entries.id FROM journal_entries WHERE is_demo = 1)"
                )
            # 2. Unassign entries from demo incidents (so they become orphan-free)
            if "incident_id" in journal_columns and {"id", "is_demo"} <= table_columns(conn, "incidents"):
                conn.execute(
                    "UPDATE journal_entries SET incident_id = NULL WHERE incident_id IN "
                    "(SELECT incidents.id FROM incidents WHERE is_demo = 1)"
                )
            # 3. Delete from each demo-seeded table
            tables = ["journal_entries", "incidents", "events", "snapshots",
                       "speedtest_results", "bqm_graphs", "bnetz_measurements",
                       "weather_data", "de_tkg_claim_drafts", "segment_utilization"]
            total = 0
            for tbl in tables:
                if "is_demo" not in table_columns(conn, tbl):
                    continue  # Module table not created
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
        today = local_today(self.tz_name)
        cutoff_date = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=self.max_days)).strftime("%Y-%m-%d")
        for table, column, bound, label in (
            ("snapshots", "timestamp", cutoff, "snapshots"),
            ("events", "timestamp", cutoff, "events"),
            ("bqm_graphs", "date", cutoff_date, "BQM graphs"),
            ("weather_data", "timestamp", cutoff, "weather records"),
            ("smart_capture_executions", "created_at", cutoff, "Smart Capture executions"),
        ):
            try:  # each step runs on its own, so one broken table does not stop the others
                with self._write() as conn:
                    if table == "bqm_graphs" and not table_exists(conn, table):
                        continue  # BQM module not loaded
                    if table in ("snapshots", "events"):
                        deleted = self._delete_expired_unprotected_rows(conn, table, column, bound)
                    else:
                        deleted = conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (bound,)).rowcount
            except Exception:
                log.exception("Retention cleanup of %s failed", label)
                continue
            if deleted:
                log.info("Cleaned up %d old %s (before %s)", deleted, label, bound)
