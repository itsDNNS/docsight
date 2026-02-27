"""SQLite snapshot storage for DOCSIS timeline."""

import json
import logging
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from .tz import utc_now, utc_cutoff, local_to_utc

ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf", "text/plain",
}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_ENTRY = 10

log = logging.getLogger("docsis.storage")


class SnapshotStorage:
    """Persist DOCSIS analysis snapshots to SQLite."""

    def __init__(self, db_path, max_days=7):
        self.db_path = db_path
        self.max_days = max_days
        self.tz_name = ""
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")

            # ── Migration: rename incidents → journal_entries ──
            # Detect old schema: incidents table has a 'title' column
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(incidents)").fetchall()]
                if "title" in cols:
                    log.info("Migrating: incidents → journal_entries")
                    conn.execute("ALTER TABLE incidents RENAME TO journal_entries")
                    # Recreate attachments table with entry_id
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS journal_attachments (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            entry_id INTEGER NOT NULL,
                            filename TEXT NOT NULL,
                            mime_type TEXT NOT NULL,
                            data BLOB NOT NULL,
                            created_at TEXT NOT NULL,
                            FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE
                        )
                    """)
                    # Copy data from old table
                    try:
                        conn.execute("""
                            INSERT INTO journal_attachments (id, entry_id, filename, mime_type, data, created_at)
                            SELECT id, incident_id, filename, mime_type, data, created_at
                            FROM incident_attachments
                        """)
                        conn.execute("DROP TABLE incident_attachments")
                    except Exception:
                        pass  # incident_attachments may not exist
                    # Add incident_id column for grouping
                    try:
                        conn.execute("ALTER TABLE journal_entries ADD COLUMN incident_id INTEGER")
                    except Exception:
                        pass  # column already exists
                    # Add icon column if missing
                    try:
                        conn.execute("ALTER TABLE journal_entries ADD COLUMN icon TEXT")
                    except Exception:
                        pass
                    log.info("Migration complete: journal_entries + journal_attachments")
            except Exception:
                pass  # incidents table doesn't exist yet, fresh install

            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    ds_channels_json TEXT NOT NULL,
                    us_channels_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_ts
                ON snapshots(timestamp)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bqm_graphs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    image_blob BLOB NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speedtest_results (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    download_mbps REAL,
                    upload_mbps REAL,
                    download_human TEXT,
                    upload_human TEXT,
                    ping_ms REAL,
                    jitter_ms REAL,
                    packet_loss_pct REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_speedtest_ts
                ON speedtest_results(timestamp)
            """)
            # Migration: add server_id/server_name columns if missing
            try:
                conn.execute("ALTER TABLE speedtest_results ADD COLUMN server_id INTEGER")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE speedtest_results ADD COLUMN server_name TEXT")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    icon TEXT,
                    incident_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # Migration: add icon column if missing (pre-icon installs)
            try:
                conn.execute("ALTER TABLE journal_entries ADD COLUMN icon TEXT")
            except Exception:
                pass
            # Migration: add incident_id column if missing
            try:
                conn.execute("ALTER TABLE journal_entries ADD COLUMN incident_id INTEGER")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    data BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE
                )
            """)
            # ── Incident containers (NEW) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    start_date TEXT,
                    end_date TEXT,
                    icon TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    acknowledged INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_ts
                ON events(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_ack
                ON events(acknowledged)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bnetz_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    provider TEXT,
                    tariff TEXT,
                    download_max_tariff REAL,
                    download_normal_tariff REAL,
                    download_min_tariff REAL,
                    upload_max_tariff REAL,
                    upload_normal_tariff REAL,
                    upload_min_tariff REAL,
                    download_measured_avg REAL,
                    upload_measured_avg REAL,
                    measurement_count INTEGER,
                    verdict_download TEXT,
                    verdict_upload TEXT,
                    measurements_json TEXT,
                    pdf_blob BLOB,
                    source TEXT DEFAULT 'upload'
                )
            """)

            # ── Migration: add source column to bnetz_measurements ──
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(bnetz_measurements)").fetchall()]
                if "source" not in cols:
                    conn.execute("ALTER TABLE bnetz_measurements ADD COLUMN source TEXT DEFAULT 'upload'")
                    log.info("Migration: added source column to bnetz_measurements")
            except Exception as e:
                log.warning("Failed to migrate bnetz_measurements: %s", e)

            # ── Migration: remove NOT NULL from pdf_blob (allows NULL for demo/CSV) ──
            try:
                schema = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name='bnetz_measurements'"
                ).fetchone()
                if schema and "NOT NULL" in schema[0] and "pdf_blob BLOB NOT NULL" in schema[0]:
                    conn.execute("ALTER TABLE bnetz_measurements RENAME TO _bnetz_old")
                    conn.execute("""
                        CREATE TABLE bnetz_measurements (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            date TEXT NOT NULL,
                            timestamp TEXT NOT NULL,
                            provider TEXT,
                            tariff TEXT,
                            download_max_tariff REAL,
                            download_normal_tariff REAL,
                            download_min_tariff REAL,
                            upload_max_tariff REAL,
                            upload_normal_tariff REAL,
                            upload_min_tariff REAL,
                            download_measured_avg REAL,
                            upload_measured_avg REAL,
                            measurement_count INTEGER,
                            verdict_download TEXT,
                            verdict_upload TEXT,
                            measurements_json TEXT,
                            pdf_blob BLOB,
                            source TEXT DEFAULT 'upload',
                            is_demo INTEGER NOT NULL DEFAULT 0
                        )
                    """)
                    conn.execute("""
                        INSERT INTO bnetz_measurements
                        SELECT id, date, timestamp, provider, tariff,
                               download_max_tariff, download_normal_tariff, download_min_tariff,
                               upload_max_tariff, upload_normal_tariff, upload_min_tariff,
                               download_measured_avg, upload_measured_avg, measurement_count,
                               verdict_download, verdict_upload, measurements_json, pdf_blob,
                               source, is_demo
                        FROM _bnetz_old
                    """)
                    conn.execute("DROP TABLE _bnetz_old")
                    log.info("Migration: removed NOT NULL from bnetz_measurements.pdf_blob")
            except Exception as e:
                log.warning("Failed to migrate bnetz_measurements pdf_blob: %s", e)

            # ── Migration: add is_demo column to demo-seeded tables ──
            _demo_tables = ["snapshots", "events", "journal_entries", "incidents", "speedtest_results", "bqm_graphs", "bnetz_measurements", "weather_data"]
            for tbl in _demo_tables:
                try:
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                    if "is_demo" not in cols:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
                        log.info("Migration: added is_demo column to %s", tbl)
                except Exception as e:
                    log.warning("Failed to add is_demo to %s: %s", tbl, e)

            # ── Weather data table ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weather_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL UNIQUE,
                    temperature REAL NOT NULL,
                    is_demo INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weather_ts
                ON weather_data(timestamp)
            """)

            # ── API tokens table ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    token_prefix TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked INTEGER NOT NULL DEFAULT 0
                )
            """)

            # ── Schema metadata (UTC migration tracking etc.) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _docsight_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

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

    # ── API Token Management ──

    def create_api_token(self, name):
        """Create a new API token. Returns (token_id, plaintext_token)."""
        raw = secrets.token_urlsafe(48)
        plaintext = "dsk_" + raw
        prefix = plaintext[:8]
        token_hash = generate_password_hash(plaintext)
        created_at = utc_now()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at) VALUES (?, ?, ?, ?)",
                (name, token_hash, prefix, created_at),
            )
            return cur.lastrowid, plaintext

    def validate_api_token(self, token):
        """Validate a Bearer token. Returns token info dict or None."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, token_hash, token_prefix, created_at, last_used_at FROM api_tokens WHERE revoked = 0"
            ).fetchall()
            for row in rows:
                if check_password_hash(row["token_hash"], token):
                    now = utc_now()
                    conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (now, row["id"]))
                    return {
                        "id": row["id"],
                        "name": row["name"],
                        "token_prefix": row["token_prefix"],
                        "created_at": row["created_at"],
                    }
        return None

    def get_api_tokens(self):
        """Return list of all tokens (without hashes) for UI display."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, token_prefix, created_at, last_used_at, revoked FROM api_tokens ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def revoke_api_token(self, token_id):
        """Soft-revoke a token. Returns True if a token was revoked."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE api_tokens SET revoked = 1 WHERE id = ? AND revoked = 0",
                (token_id,),
            )
            return cur.rowcount > 0

    def save_snapshot(self, analysis):
        """Save current analysis as a snapshot. Runs cleanup afterwards."""
        ts = utc_now()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
                    (
                        ts,
                        json.dumps(analysis["summary"]),
                        json.dumps(analysis["ds_channels"]),
                        json.dumps(analysis["us_channels"]),
                    ),
                )
            log.debug("Snapshot saved: %s", ts)
        except Exception as e:
            log.error("Failed to save snapshot: %s", e)
            return
        self._cleanup()

    def get_snapshot_list(self):
        """Return list of available snapshot timestamps (newest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_snapshot(self, timestamp):
        """Load a single snapshot by timestamp. Returns analysis dict or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT summary_json, ds_channels_json, us_channels_json FROM snapshots WHERE timestamp = ?",
                (timestamp,),
            ).fetchone()
        if not row:
            return None
        return {
            "summary": json.loads(row[0]),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
        }

    def get_dates_with_data(self):
        """Return list of dates (YYYY-MM-DD) that have at least one snapshot.

        Converts UTC timestamps to local dates using the configured timezone,
        so the returned dates match the user's calendar.
        """
        from .tz import to_local
        tz = self.tz_name
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT timestamp FROM snapshots ORDER BY timestamp"
            ).fetchall()
        # Convert each UTC timestamp to local date and deduplicate
        dates = sorted({to_local(r[0], tz)[:10] for r in rows if r[0]})
        return dates

    def get_daily_snapshot(self, date, target_time="06:00"):
        """Get the snapshot closest to target_time on the given date.

        date and target_time are local concepts — converted to UTC for querying.
        """
        from .tz import local_date_to_utc_range, local_to_utc as _l2u
        tz = self.tz_name
        start_utc, end_utc = local_date_to_utc_range(date, tz)
        target_utc = _l2u(f"{date}T{target_time}:00", tz)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT timestamp, summary_json, ds_channels_json, us_channels_json
                   FROM snapshots
                   WHERE timestamp >= ? AND timestamp <= ?
                   ORDER BY ABS(julianday(timestamp) - julianday(?))
                   LIMIT 1""",
                (start_utc, end_utc, target_utc),
            ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "summary": json.loads(row[1]),
            "ds_channels": json.loads(row[2]),
            "us_channels": json.loads(row[3]),
        }

    def get_trend_data(self, start_date, end_date, target_time="06:00"):
        """Get summary data points for a date range, one per day (closest to target_time).
        Returns list of {date, timestamp, ...summary_fields}.

        start_date and end_date are local calendar dates (YYYY-MM-DD).
        """
        from .tz import to_local, local_date_to_utc_range
        tz = self.tz_name
        # Get the full UTC range covering both local date boundaries
        range_start, _ = local_date_to_utc_range(start_date, tz)
        _, range_end = local_date_to_utc_range(end_date, tz)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT timestamp FROM snapshots WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (range_start, range_end),
            ).fetchall()
        # Convert UTC timestamps to local dates and deduplicate
        dates = sorted({to_local(r[0], tz)[:10] for r in rows if r[0]})

        results = []
        for date in dates:
            snap = self.get_daily_snapshot(date, target_time)
            if snap:
                entry = {"date": date, "timestamp": snap["timestamp"]}
                entry.update(snap["summary"])
                results.append(entry)
        return results

    def get_range_data(self, start_ts, end_ts):
        """Get all snapshots between two ISO timestamps (inclusive)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json, ds_channels_json, us_channels_json "
                "FROM snapshots WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        results = []
        for row in rows:
            entry = {
                "timestamp": row[0],
                "summary": json.loads(row[1]),
                "ds_channels": json.loads(row[2]),
                "us_channels": json.loads(row[3]),
            }
            results.append(entry)
        return results

    def get_intraday_data(self, date):
        """Get all snapshots for a single day (for day-detail trends).

        date is a local calendar date — converted to UTC range for querying.
        """
        from .tz import local_date_to_utc_range
        start_utc, end_utc = local_date_to_utc_range(date, self.tz_name)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_utc, end_utc),
            ).fetchall()
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(json.loads(row[1]))
            results.append(entry)
        return results

    def get_summary_range(self, start_date, end_date):
        """Get all snapshots (summary only) between two dates. Like get_intraday_data but multi-day.

        start_date and end_date are local calendar dates — converted to UTC range.
        """
        from .tz import local_date_to_utc_range
        range_start, _ = local_date_to_utc_range(start_date, self.tz_name)
        _, range_end = local_date_to_utc_range(end_date, self.tz_name)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (range_start, range_end),
            ).fetchall()
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(json.loads(row[1]))
            results.append(entry)
        return results

    def save_bqm_graph(self, image_data, graph_date=None):
        """Save BQM graph. Skips if already exists (UNIQUE date).

        Args:
            image_data: PNG/JPEG bytes
            graph_date: ISO date string (YYYY-MM-DD) to store as.
                        Defaults to today if not specified.
        """
        from .tz import local_today
        target_date = graph_date or local_today(getattr(self, 'tz_name', ''))
        ts = utc_now()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                    (target_date, ts, image_data),
                )
            log.debug("BQM graph saved for %s", target_date)
        except Exception as e:
            log.error("Failed to save BQM graph: %s", e)

    def import_bqm_graph(self, date, image_data, overwrite=False):
        """Import a BQM graph for a specific date.
        Returns: 'imported', 'skipped', or 'replaced'."""
        ts = date + "T00:00:00"
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT 1 FROM bqm_graphs WHERE date = ?", (date,)
            ).fetchone()
            if existing:
                if not overwrite:
                    return "skipped"
                conn.execute(
                    "UPDATE bqm_graphs SET timestamp = ?, image_blob = ? WHERE date = ?",
                    (ts, image_data, date),
                )
                return "replaced"
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                (date, ts, image_data),
            )
        return "imported"

    def delete_bqm_graph(self, date):
        """Delete a single BQM graph. Returns True if deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM bqm_graphs WHERE date = ?", (date,))
        return cur.rowcount > 0

    def delete_bqm_graphs_range(self, start_date, end_date):
        """Delete BQM graphs in date range (inclusive). Returns count."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM bqm_graphs WHERE date >= ? AND date <= ?",
                (start_date, end_date),
            )
        return cur.rowcount

    def delete_all_bqm_graphs(self):
        """Delete all BQM graphs. Returns count."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM bqm_graphs")
        return cur.rowcount

    def get_bqm_dates(self):
        """Return list of dates with BQM graphs (newest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date FROM bqm_graphs ORDER BY date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_bqm_graph(self, date):
        """Return BQM graph PNG bytes for a date, or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT image_blob FROM bqm_graphs WHERE date = ?", (date,)
            ).fetchone()
        return bytes(row[0]) if row else None

    def get_closest_snapshot(self, timestamp):
        """Find the snapshot closest to a given ISO timestamp (within 2 hours).
        Returns analysis dict with timestamp, or None if nothing within range.

        All timestamps are now stored as UTC with Z suffix.
        """
        ts_param = timestamp
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT timestamp, summary_json, ds_channels_json, us_channels_json
                   FROM snapshots
                   WHERE ABS(julianday(REPLACE(timestamp, 'Z', '')) - julianday(REPLACE(?, 'Z', ''))) <= (2.0 / 24.0)
                   ORDER BY ABS(julianday(REPLACE(timestamp, 'Z', '')) - julianday(REPLACE(?, 'Z', '')))
                   LIMIT 1""",
                (ts_param, ts_param),
            ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "summary": json.loads(row[1]),
            "ds_channels": json.loads(row[2]),
            "us_channels": json.loads(row[3]),
        }

    # ── Speedtest result caching ──

    def save_speedtest_results(self, results):
        """Bulk insert speedtest results, ignoring duplicates by id."""
        if not results:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO speedtest_results "
                    "(id, timestamp, download_mbps, upload_mbps, download_human, "
                    "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                    "server_id, server_name) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            r["id"], r["timestamp"], r["download_mbps"],
                            r["upload_mbps"], r["download_human"], r["upload_human"],
                            r["ping_ms"], r["jitter_ms"], r["packet_loss_pct"],
                            r.get("server_id"), r.get("server_name", ""),
                        )
                        for r in results
                    ],
                )
            log.debug("Saved %d speedtest results", len(results))
        except Exception as e:
            log.error("Failed to save speedtest results: %s", e)

    def get_speedtest_results(self, limit=2000):
        """Return cached speedtest results, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                "server_id, server_name "
                "FROM speedtest_results ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_speedtest_by_id(self, result_id):
        """Return a single speedtest result by id, or None."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                "server_id, server_name "
                "FROM speedtest_results WHERE id = ?",
                (result_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_speedtest_count(self):
        """Return number of cached speedtest results."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM speedtest_results").fetchone()
        return row[0] if row else 0

    def get_latest_speedtest_id(self):
        """Return the highest speedtest result id, or 0 if none."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(id) FROM speedtest_results"
            ).fetchone()
        return row[0] or 0 if row else 0

    # ── Weather Data ──

    def save_weather_data(self, records, is_demo=False):
        """Bulk insert weather records, ignoring duplicates by timestamp.

        Args:
            records: list of dicts with 'timestamp' and 'temperature' keys
            is_demo: True for demo-seeded data
        """
        if not records:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO weather_data "
                    "(timestamp, temperature, is_demo) VALUES (?, ?, ?)",
                    [(r["timestamp"], r["temperature"], int(is_demo)) for r in records],
                )
            log.debug("Saved %d weather records", len(records))
        except Exception as e:
            log.error("Failed to save weather data: %s", e)

    def get_weather_data(self, limit=2000):
        """Return weather data, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, temperature FROM weather_data "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_weather_in_range(self, start_ts, end_ts):
        """Return weather data within a timestamp range, oldest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, temperature FROM weather_data "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp ASC",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_weather_count(self):
        """Return number of weather records."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM weather_data").fetchone()
        return row[0] if row else 0

    def get_latest_weather_timestamp(self):
        """Return the newest weather timestamp, or None if empty."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM weather_data"
            ).fetchone()
        return row[0] if row and row[0] else None

    # ── Journal Entries ──

    def _connect(self):
        """Return a connection with foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def save_entry(self, date, title, description, icon=None, incident_id=None, is_demo=False):
        """Create a new journal entry. Returns the new entry id."""
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO journal_entries (date, title, description, icon, incident_id, created_at, updated_at, is_demo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (date, title, description, icon, incident_id, now, now, int(is_demo)),
            )
            return cur.lastrowid

    def update_entry(self, entry_id, date, title, description, icon=None, incident_id=None):
        """Update an existing journal entry. Returns True if found."""
        now = utc_now()
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET date=?, title=?, description=?, icon=?, incident_id=?, updated_at=? WHERE id=?",
                (date, title, description, icon, incident_id, now, entry_id),
            ).rowcount
        return rowcount > 0

    def delete_entry(self, entry_id):
        """Delete a journal entry (CASCADE deletes attachments). Returns True if found."""
        with self._connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM journal_entries WHERE id=?", (entry_id,)
            ).rowcount
        return rowcount > 0

    def get_entries(self, limit=100, offset=0, search=None, incident_id=None):
        """Return list of journal entries (newest first) with attachment_count.

        incident_id filtering:
          None (default) → all entries
          0 → only unassigned (WHERE incident_id IS NULL)
          N → only entries for incident N
        """
        query = (
            "SELECT i.id, i.date, i.title, i.description, i.icon, i.incident_id, i.created_at, i.updated_at, "
            "(SELECT COUNT(*) FROM journal_attachments WHERE entry_id = i.id) AS attachment_count "
            "FROM journal_entries i"
        )
        conditions = []
        params = []
        if search:
            conditions.append("(i.title LIKE ? OR i.description LIKE ? OR i.date LIKE ?)")
            like = "%" + search + "%"
            params.extend([like, like, like])
        if incident_id is not None:
            if incident_id == 0:
                conditions.append("i.incident_id IS NULL")
            else:
                conditions.append("i.incident_id = ?")
                params.append(incident_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY i.date DESC, i.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_entry(self, entry_id):
        """Return single journal entry with attachment metadata (no blob data)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, date, title, description, icon, incident_id, created_at, updated_at FROM journal_entries WHERE id=?",
                (entry_id,),
            ).fetchone()
            if not row:
                return None
            entry = dict(row)
            attachments = conn.execute(
                "SELECT id, filename, mime_type, created_at FROM journal_attachments WHERE entry_id=? ORDER BY id",
                (entry_id,),
            ).fetchall()
            entry["attachments"] = [dict(a) for a in attachments]
        return entry

    def save_attachment(self, entry_id, filename, mime_type, data):
        """Save a file attachment for a journal entry. Returns attachment id."""
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO journal_attachments (entry_id, filename, mime_type, data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_id, filename, mime_type, data, now),
            )
            return cur.lastrowid

    def get_attachment(self, attachment_id):
        """Return attachment dict with data bytes, or None."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, entry_id, filename, mime_type, data, created_at "
                "FROM journal_attachments WHERE id=?",
                (attachment_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["data"] = bytes(result["data"])
        return result

    def delete_attachment(self, attachment_id):
        """Delete a single attachment. Returns True if found."""
        with self._connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM journal_attachments WHERE id=?", (attachment_id,)
            ).rowcount
        return rowcount > 0

    def get_attachment_count(self, entry_id):
        """Return number of attachments for a journal entry."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM journal_attachments WHERE entry_id=?",
                (entry_id,),
            ).fetchone()
        return row[0] if row else 0

    def check_entry_exists(self, date, title):
        """Check if a journal entry with same date + title exists. Returns True/False."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM journal_entries WHERE date=? AND title=? LIMIT 1",
                (date, title),
            ).fetchone()
        return row is not None

    def delete_all_entries(self):
        """Delete all journal entries (CASCADE deletes attachments). Returns count."""
        with self._connect() as conn:
            rowcount = conn.execute("DELETE FROM journal_entries").rowcount
        return rowcount

    def delete_entries_batch(self, ids):
        """Delete journal entries by list of IDs. Returns count of deleted."""
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM journal_entries WHERE id IN (%s)" % placeholders, ids
            ).rowcount
        return rowcount

    def get_active_entries(self):
        """Return all journal entries (for export context)."""
        return self.get_entries(limit=100)

    def get_entries_for_export(self, date_from=None, date_to=None, incident_id=None):
        """Return journal entries for export (no pagination).

        Args:
            date_from: Optional start date (YYYY-MM-DD), inclusive.
            date_to: Optional end date (YYYY-MM-DD), inclusive.
            incident_id: None=all, 0=unassigned, N=specific incident.
        """
        query = (
            "SELECT i.id, i.date, i.title, i.description, i.icon, i.incident_id, i.created_at, i.updated_at, "
            "(SELECT COUNT(*) FROM journal_attachments WHERE entry_id = i.id) AS attachment_count "
            "FROM journal_entries i"
        )
        conditions = []
        params = []
        if date_from:
            conditions.append("i.date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("i.date <= ?")
            params.append(date_to)
        if incident_id is not None:
            if incident_id == 0:
                conditions.append("i.incident_id IS NULL")
            else:
                conditions.append("i.incident_id = ?")
                params.append(incident_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY i.date DESC, i.created_at DESC"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── Incident Containers (NEW) ──

    def save_incident(self, name, description=None, status="open", start_date=None, end_date=None, icon=None, is_demo=False):
        """Create a new incident container. Returns the new incident id."""
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO incidents (name, description, status, start_date, end_date, icon, created_at, updated_at, is_demo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, description, status, start_date, end_date, icon, now, now, int(is_demo)),
            )
            return cur.lastrowid

    def update_incident(self, incident_id, name, description=None, status="open", start_date=None, end_date=None, icon=None):
        """Update an existing incident container. Returns True if found."""
        now = utc_now()
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE incidents SET name=?, description=?, status=?, start_date=?, end_date=?, icon=?, updated_at=? WHERE id=?",
                (name, description, status, start_date, end_date, icon, now, incident_id),
            ).rowcount
        return rowcount > 0

    def delete_incident(self, incident_id):
        """Delete an incident container. Entries become unassigned (SET NULL). Returns True if found."""
        with self._connect() as conn:
            # Unassign entries first
            conn.execute(
                "UPDATE journal_entries SET incident_id = NULL WHERE incident_id = ?",
                (incident_id,),
            )
            rowcount = conn.execute(
                "DELETE FROM incidents WHERE id=?", (incident_id,)
            ).rowcount
        return rowcount > 0

    def get_incidents(self, status=None):
        """Return list of incident containers with entry_count."""
        query = (
            "SELECT i.id, i.name, i.description, i.status, i.start_date, i.end_date, "
            "i.icon, i.created_at, i.updated_at, "
            "(SELECT COUNT(*) FROM journal_entries WHERE incident_id = i.id) AS entry_count "
            "FROM incidents i"
        )
        params = []
        if status:
            query += " WHERE i.status = ?"
            params.append(status)
        query += " ORDER BY i.created_at DESC"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_incident(self, incident_id):
        """Return single incident container with entry_count."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT i.id, i.name, i.description, i.status, i.start_date, i.end_date, "
                "i.icon, i.created_at, i.updated_at, "
                "(SELECT COUNT(*) FROM journal_entries WHERE incident_id = i.id) AS entry_count "
                "FROM incidents i WHERE i.id=?",
                (incident_id,),
            ).fetchone()
        return dict(row) if row else None

    def assign_entries_to_incident(self, entry_ids, incident_id):
        """Assign journal entries to an incident. Returns count of updated entries."""
        if not entry_ids:
            return 0
        placeholders = ",".join("?" for _ in entry_ids)
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET incident_id = ? WHERE id IN (%s)" % placeholders,
                [incident_id] + list(entry_ids),
            ).rowcount
        return rowcount

    def unassign_entries(self, entry_ids):
        """Remove incident assignment from journal entries. Returns count."""
        if not entry_ids:
            return 0
        placeholders = ",".join("?" for _ in entry_ids)
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET incident_id = NULL WHERE id IN (%s)" % placeholders,
                list(entry_ids),
            ).rowcount
        return rowcount

    def assign_entries_by_date_range(self, incident_id, start_date, end_date):
        """Assign all journal entries in a date range to an incident. Returns count."""
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET incident_id = ? WHERE date >= ? AND date <= ?",
                (incident_id, start_date, end_date),
            ).rowcount
        return rowcount

    # ── Events ──

    def save_event(self, timestamp, severity, event_type, message, details=None):
        """Save a single event. Returns the new event id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, severity, event_type, message, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (timestamp, severity, event_type, message,
                 json.dumps(details) if details else None),
            )
            return cur.lastrowid

    def save_events(self, events_list, is_demo=False):
        """Bulk insert events. Returns count of inserted rows."""
        if not events_list:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO events (timestamp, severity, event_type, message, details, is_demo) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (e["timestamp"], e["severity"], e["event_type"], e["message"],
                     json.dumps(e.get("details")) if e.get("details") else None,
                     int(is_demo))
                    for e in events_list
                ],
            )
        return len(events_list)

    def get_events(self, limit=200, offset=0, severity=None, event_type=None, acknowledged=None):
        """Return list of event dicts, newest first, with optional filters."""
        query = "SELECT id, timestamp, severity, event_type, message, details, acknowledged FROM events"
        conditions = []
        params = []
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if acknowledged is not None:
            conditions.append("acknowledged = ?")
            params.append(int(acknowledged))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            event = dict(r)
            if event["details"]:
                try:
                    event["details"] = json.loads(event["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(event)
        return results

    def get_event_count(self, acknowledged=None):
        """Return event count, optionally filtered by acknowledged status."""
        if acknowledged is not None:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE acknowledged = ?",
                    (int(acknowledged),),
                ).fetchone()
        else:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0

    def acknowledge_event(self, event_id):
        """Acknowledge a single event. Returns True if found."""
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE id = ?", (event_id,)
            ).rowcount
        return rowcount > 0

    def acknowledge_all_events(self):
        """Acknowledge all unacknowledged events. Returns rows affected."""
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE acknowledged = 0"
            ).rowcount
        return rowcount

    def get_recent_events(self, hours=48):
        """Return events from the last N hours, newest first."""
        cutoff = utc_cutoff(hours=hours)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, severity, event_type, message, details, acknowledged "
                "FROM events WHERE timestamp >= ? ORDER BY timestamp DESC",
                (cutoff,),
            ).fetchall()
        results = []
        for r in rows:
            event = dict(r)
            if event["details"]:
                try:
                    event["details"] = json.loads(event["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(event)
        return results

    # ── Breitbandmessung (BNetzA) ──

    def save_bnetz_measurement(self, parsed_data, pdf_bytes=None, source="upload"):
        """Save a parsed BNetzA measurement with optional PDF. Returns the new id."""
        now = utc_now()
        measurements = {
            "download": parsed_data.get("measurements_download", []),
            "upload": parsed_data.get("measurements_upload", []),
        }
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO bnetz_measurements "
                "(date, timestamp, provider, tariff, "
                "download_max_tariff, download_normal_tariff, download_min_tariff, "
                "upload_max_tariff, upload_normal_tariff, upload_min_tariff, "
                "download_measured_avg, upload_measured_avg, measurement_count, "
                "verdict_download, verdict_upload, measurements_json, pdf_blob, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    parsed_data.get("date", now[:10]),
                    now,
                    parsed_data.get("provider"),
                    parsed_data.get("tariff"),
                    parsed_data.get("download_max"),
                    parsed_data.get("download_normal"),
                    parsed_data.get("download_min"),
                    parsed_data.get("upload_max"),
                    parsed_data.get("upload_normal"),
                    parsed_data.get("upload_min"),
                    parsed_data.get("download_measured_avg"),
                    parsed_data.get("upload_measured_avg"),
                    parsed_data.get("measurement_count"),
                    parsed_data.get("verdict_download"),
                    parsed_data.get("verdict_upload"),
                    json.dumps(measurements),
                    pdf_bytes,
                    source,
                ),
            )
            return cur.lastrowid

    def get_bnetz_measurements(self, limit=50):
        """Return list of BNetzA measurements (without PDF blob), newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, date, timestamp, provider, tariff, "
                "download_max_tariff, download_normal_tariff, download_min_tariff, "
                "upload_max_tariff, upload_normal_tariff, upload_min_tariff, "
                "download_measured_avg, upload_measured_avg, measurement_count, "
                "verdict_download, verdict_upload, measurements_json, source "
                "FROM bnetz_measurements ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            raw = d.pop("measurements_json", None)
            if raw:
                try:
                    d["measurements"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d["measurements"] = None
            else:
                d["measurements"] = None
            results.append(d)
        return results

    def get_bnetz_pdf(self, measurement_id):
        """Return the original PDF bytes for a BNetzA measurement, or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT pdf_blob FROM bnetz_measurements WHERE id = ?",
                (measurement_id,),
            ).fetchone()
        return bytes(row[0]) if row and row[0] else None

    def delete_bnetz_measurement(self, measurement_id):
        """Delete a BNetzA measurement. Returns True if found."""
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                "DELETE FROM bnetz_measurements WHERE id = ?",
                (measurement_id,),
            ).rowcount
        return rowcount > 0

    def get_bnetz_in_range(self, start_ts, end_ts):
        """Return BNetzA measurements within a time range, oldest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, date, timestamp, provider, tariff, "
                "download_max_tariff, download_measured_avg, "
                "upload_max_tariff, upload_measured_avg, "
                "verdict_download, verdict_upload "
                "FROM bnetz_measurements "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_bnetz(self):
        """Return the most recent BNetzA measurement (without blob), or None."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, date, timestamp, provider, tariff, "
                "download_max_tariff, download_normal_tariff, download_min_tariff, "
                "upload_max_tariff, upload_normal_tariff, upload_min_tariff, "
                "download_measured_avg, upload_measured_avg, measurement_count, "
                "verdict_download, verdict_upload "
                "FROM bnetz_measurements ORDER BY date DESC LIMIT 1",
            ).fetchone()
        return dict(row) if row else None

    def get_recent_speedtests(self, limit=10):
        """Return the N most recent speedtest results."""
        return self.get_speedtest_results(limit=limit)

    def get_speedtest_in_range(self, start_ts, end_ts):
        """Return speedtest results within a time range, oldest first.

        All timestamps are now stored as UTC with Z suffix.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct "
                "FROM speedtest_results "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_correlation_timeline(self, start_ts, end_ts, sources=None):
        """Return unified timeline entries from all sources, sorted by timestamp.

        Args:
            start_ts: UTC start timestamp (with Z suffix)
            end_ts: UTC end timestamp (with Z suffix)
            sources: set of source names to include (modem, speedtest, events).
                     None means all.

        Returns list of dicts with 'timestamp', 'source', and source-specific fields.
        """
        if sources is None:
            sources = {"modem", "speedtest", "events", "bnetz"}
        timeline = []

        if "modem" in sources:
            for snap in self.get_range_data(start_ts, end_ts):
                s = snap["summary"]
                timeline.append({
                    "timestamp": snap["timestamp"],
                    "source": "modem",
                    "health": s.get("health", "unknown"),
                    "ds_power_avg": s.get("ds_power_avg"),
                    "ds_power_max": s.get("ds_power_max"),
                    "ds_snr_min": s.get("ds_snr_min"),
                    "ds_snr_avg": s.get("ds_snr_avg"),
                    "us_power_avg": s.get("us_power_avg"),
                    "ds_correctable_errors": s.get("ds_correctable_errors", 0),
                    "ds_uncorrectable_errors": s.get("ds_uncorrectable_errors", 0),
                })

        if "speedtest" in sources:
            for st in self.get_speedtest_in_range(start_ts, end_ts):
                timeline.append({
                    "timestamp": st["timestamp"],
                    "source": "speedtest",
                    "id": st["id"],
                    "download_mbps": st.get("download_mbps"),
                    "upload_mbps": st.get("upload_mbps"),
                    "ping_ms": st.get("ping_ms"),
                    "jitter_ms": st.get("jitter_ms"),
                    "packet_loss_pct": st.get("packet_loss_pct"),
                })

        if "events" in sources:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, timestamp, severity, event_type, message, details "
                    "FROM events WHERE timestamp >= ? AND timestamp <= ? "
                    "ORDER BY timestamp",
                    (start_ts, end_ts),
                ).fetchall()
            for r in rows:
                event = {
                    "timestamp": r["timestamp"],
                    "source": "event",
                    "severity": r["severity"],
                    "event_type": r["event_type"],
                    "message": r["message"],
                }
                if r["details"]:
                    try:
                        event["details"] = json.loads(r["details"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                timeline.append(event)

        if "bnetz" in sources:
            for m in self.get_bnetz_in_range(start_ts, end_ts):
                timeline.append({
                    "timestamp": m["timestamp"],
                    "source": "bnetz",
                    "download_tariff": m.get("download_max_tariff"),
                    "download_avg": m.get("download_measured_avg"),
                    "upload_tariff": m.get("upload_max_tariff"),
                    "upload_avg": m.get("upload_measured_avg"),
                    "verdict_download": m.get("verdict_download"),
                    "verdict_upload": m.get("verdict_upload"),
                })

        timeline.sort(key=lambda x: x["timestamp"])
        return timeline

    def delete_old_events(self, days):
        """Delete events older than given days. Returns count deleted."""
        if days <= 0:
            return 0
        cutoff = utc_cutoff(days=days)
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM events WHERE timestamp < ?", (cutoff,)
            ).rowcount
        return deleted

    # ── Per-Channel History ──

    def get_channel_history(self, channel_id, direction, days=7):
        """Return time series for a single channel over the last N days.
        direction: 'ds' or 'us'. Returns list of dicts with timestamp + channel fields."""
        _COL_MAP = {"ds": "ds_channels_json", "us": "us_channels_json"}
        channel_id = int(channel_id)
        col = _COL_MAP[direction]  # validated in web.py to be 'ds' or 'us'
        cutoff = utc_cutoff(days=days)
        with sqlite3.connect(self.db_path) as conn:
            if direction == "ds":
                rows = conn.execute(
                    "SELECT timestamp, ds_channels_json FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                    (cutoff,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT timestamp, us_channels_json FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                    (cutoff,),
                ).fetchall()
        results = []
        for ts, channels_json in rows:
            channels = json.loads(channels_json)
            for ch in channels:
                if ch.get("channel_id") == channel_id:
                    results.append({
                        "timestamp": ts,
                        "power": ch.get("power"),
                        "snr": ch.get("snr"),
                        "correctable_errors": ch.get("correctable_errors", 0),
                        "uncorrectable_errors": ch.get("uncorrectable_errors", 0),
                        "modulation": ch.get("modulation", ""),
                        "health": ch.get("health", ""),
                    })
                    break
        return results

    def get_multi_channel_history(self, channel_ids, direction, days=7):
        """Return time series for multiple channels over the last N days.
        direction: 'ds' or 'us'. Returns dict {channel_id: [{timestamp, power, snr, ...}, ...]}"""
        channel_ids = [int(c) for c in channel_ids]
        channel_set = set(channel_ids)
        cutoff = utc_cutoff(days=days)
        col = "ds_channels_json" if direction == "ds" else "us_channels_json"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT timestamp, {col} FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                (cutoff,),
            ).fetchall()
        results = {cid: [] for cid in channel_ids}
        for ts, channels_json in rows:
            channels = json.loads(channels_json)
            for ch in channels:
                cid = ch.get("channel_id")
                if cid in channel_set:
                    results[cid].append({
                        "timestamp": ts,
                        "power": ch.get("power"),
                        "snr": ch.get("snr"),
                        "correctable_errors": ch.get("correctable_errors", 0),
                        "uncorrectable_errors": ch.get("uncorrectable_errors", 0),
                        "modulation": ch.get("modulation", ""),
                        "frequency": ch.get("frequency", ""),
                    })
        return results

    def get_current_channels(self):
        """Return DS and US channels from the latest snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT ds_channels_json, us_channels_json FROM snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"ds_channels": [], "us_channels": []}
        return {
            "ds_channels": json.loads(row[0]),
            "us_channels": json.loads(row[1]),
        }

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
        from .tz import local_today
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
