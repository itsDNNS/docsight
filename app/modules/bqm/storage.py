"""Standalone BQM graph storage."""

import logging
import sqlite3

from app.tz import utc_now

log = logging.getLogger("docsis.storage.bqm")


class BqmStorage:
    """Standalone BQM data storage (not a mixin).

    Creates the bqm_graphs table if it doesn't exist.
    """

    def __init__(self, db_path, tz_name=""):
        self.db_path = db_path
        self.tz_name = tz_name
        self._ensure_table()

    def _ensure_table(self):
        """Create the bqm_graphs table if it doesn't exist."""
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
            # Migration: add is_demo column if missing
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(bqm_graphs)").fetchall()]
                if "is_demo" not in cols:
                    conn.execute("ALTER TABLE bqm_graphs ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

    def save_bqm_graph(self, image_data, graph_date=None):
        """Save BQM graph. Skips if already exists (UNIQUE date)."""
        from app.tz import local_today
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
