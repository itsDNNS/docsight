"""Storage base class with schema init and constants."""

import logging
import os
import sqlite3

from ..tz import utc_now, utc_cutoff, local_to_utc

ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf", "text/plain",
}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_ENTRY = 10

log = logging.getLogger("docsis.storage")


class StorageBase:
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
            # ── Migration: add is_demo column to demo-seeded tables ──
            # Note: speedtest_results, bqm_graphs, bnetz_measurements tables are
            # now created by their respective modules. We still try the migration
            # here because the tables may already exist from a previous version.
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

    def _connect(self):
        """Return a connection with foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
