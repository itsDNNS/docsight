"""Standalone BQM storage for legacy PNG graphs and native CSV data."""

import logging
import sqlite3

from app.tz import local_today, utc_now

log = logging.getLogger("docsis.storage.bqm")


class BqmStorage:
    """Standalone BQM data storage (not a mixin).

    Creates the bqm_graphs and bqm_data tables if they don't exist.
    """

    def __init__(self, db_path, tz_name=""):
        self.db_path = db_path
        self.tz_name = tz_name
        self._ensure_table()

    def _ensure_table(self):
        """Create the BQM tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bqm_graphs ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  date TEXT NOT NULL UNIQUE,"
                "  timestamp TEXT NOT NULL,"
                "  image_blob BLOB NOT NULL,"
                "  is_demo INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bqm_data ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  timestamp TEXT NOT NULL,"
                "  date TEXT NOT NULL,"
                "  sent_polls INTEGER NOT NULL,"
                "  lost_polls INTEGER NOT NULL DEFAULT 0,"
                "  latency_min_ms REAL NOT NULL,"
                "  latency_avg_ms REAL NOT NULL,"
                "  latency_max_ms REAL NOT NULL,"
                "  score INTEGER NOT NULL,"
                "  UNIQUE(timestamp)"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bqm_data_date "
                "ON bqm_data(date)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bqm_meta ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT NOT NULL"
                ")"
            )
            # Migration: add is_demo column if missing
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(bqm_graphs)").fetchall()]
                if "is_demo" not in cols:
                    conn.execute("ALTER TABLE bqm_graphs ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

    def store_csv_data(self, rows):
        """Bulk insert CSV-derived BQM rows, ignoring duplicates by timestamp."""
        if not rows:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA busy_timeout = 5000")
                conn.executemany(
                    "INSERT OR IGNORE INTO bqm_data "
                    "(timestamp, date, sent_polls, lost_polls, latency_min_ms, "
                    "latency_avg_ms, latency_max_ms, score) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            row["timestamp"],
                            row["date"],
                            row["sent_polls"],
                            row["lost_polls"],
                            row["latency_min_ms"],
                            row["latency_avg_ms"],
                            row["latency_max_ms"],
                            row["score"],
                        )
                        for row in rows
                    ],
                )
            log.debug("Stored %d BQM CSV rows", len(rows))
        except Exception as e:
            log.error("Failed to store BQM CSV rows: %s", e)
            raise

    def _rows_for_query(self, query, params):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_data_for_date(self, target_date):
        """Return BQM CSV rows for a single date, oldest first."""
        return self._rows_for_query(
            "SELECT timestamp, date, sent_polls, lost_polls, latency_min_ms, "
            "latency_avg_ms, latency_max_ms, score "
            "FROM bqm_data WHERE date = ? ORDER BY timestamp",
            (target_date,),
        )

    def get_data_for_range(self, start_date, end_date):
        """Return BQM CSV rows across a date range, oldest first."""
        return self._rows_for_query(
            "SELECT timestamp, date, sent_polls, lost_polls, latency_min_ms, "
            "latency_avg_ms, latency_max_ms, score "
            "FROM bqm_data WHERE date >= ? AND date <= ? ORDER BY timestamp",
            (start_date, end_date),
        )

    def get_csv_dates(self):
        """Return list of dates with CSV data (newest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT date FROM bqm_data ORDER BY date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def has_csv_data(self, target_date):
        """Return True if CSV data exists for the given date."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM bqm_data WHERE date = ? LIMIT 1",
                (target_date,),
            ).fetchone()
        return row is not None

    def save_bqm_graph(self, image_data, graph_date=None):
        """Save BQM graph. Skips if already exists (UNIQUE date)."""
        target_date = graph_date or local_today(self.tz_name)
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

    def set_meta(self, key, value):
        """Persist a module metadata key."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO bqm_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def get_collection_metadata(self):
        """Return persisted BQM collection metadata."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT key, value FROM bqm_meta").fetchall()
        return {key: value for key, value in rows}

    def record_collection_success(self, collection_date, target_date, mode, rows=0):
        """Persist the last successful BQM collection."""
        values = {
            "last_success_at": utc_now(),
            "last_success_collection_date": collection_date,
            "last_success_target_date": target_date,
            "last_success_mode": mode,
            "last_success_rows": rows,
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO bqm_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, str(value)) for key, value in values.items()],
            )
