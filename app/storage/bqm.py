"""BQM graph CRUD mixin."""

import logging
import sqlite3

from ..tz import utc_now

log = logging.getLogger("docsis.storage")


class BqmMixin:

    def save_bqm_graph(self, image_data, graph_date=None):
        """Save BQM graph. Skips if already exists (UNIQUE date).

        Args:
            image_data: PNG/JPEG bytes
            graph_date: ISO date string (YYYY-MM-DD) to store as.
                        Defaults to today if not specified.
        """
        from ..tz import local_today
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
