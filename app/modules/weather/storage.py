"""Standalone weather data storage."""

import logging
from app.storage.migrations import run_migrations
from app.storage.sqlite import DatabaseAccess, bulk_write, open_read
from app.tz import normalize_range_ts
from .migrations import MIGRATIONS

log = logging.getLogger("docsis.storage.weather")
BACKFILL_KEY = "weather_backfill_pending"


class WeatherStorage(DatabaseAccess):
    """Standalone weather data storage (not a mixin).

    Creates the weather_data table if it doesn't exist.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        run_migrations(self.db_path, MIGRATIONS)

    def save_weather_data(self, records, is_demo=False):
        """Bulk insert weather records, ignoring duplicates by timestamp.

        Args:
            records: list of dicts with 'timestamp' and 'temperature' keys
            is_demo: True for demo-seeded data
        """
        if not records:
            return
        bulk_write(
            self.db_path,
            "INSERT OR IGNORE INTO weather_data "
            "(timestamp, temperature, is_demo) VALUES (?, ?, ?)",
            [(r["timestamp"], r["temperature"], int(is_demo)) for r in records],
        )
        log.debug("Saved %d weather records", len(records))

    def backfill_pending(self):
        """True while the history backfill is outstanding; an empty table is marked as awaiting it."""
        with self._write() as conn:
            if conn.execute("SELECT 1 FROM weather_data LIMIT 1").fetchone() is None:
                conn.execute("INSERT OR IGNORE INTO _docsight_meta (key, value) VALUES (?, '1')", (BACKFILL_KEY,))
            row = conn.execute("SELECT 1 FROM _docsight_meta WHERE key = ?", (BACKFILL_KEY,)).fetchone()
        return row is not None

    def finish_backfill(self):
        with self._write() as conn:
            conn.execute("DELETE FROM _docsight_meta WHERE key = ?", (BACKFILL_KEY,))

    def get_weather_data(self, limit=2000):
        """Return weather data, newest first."""
        with open_read(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, temperature FROM weather_data "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_weather_in_range(self, start_ts, end_ts):
        """Return weather data within a timestamp range, oldest first."""
        start_ts = normalize_range_ts(start_ts, " ")
        end_ts = normalize_range_ts(end_ts, " ")
        with open_read(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, temperature FROM weather_data "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp ASC",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_weather_count(self):
        """Return number of weather records."""
        with open_read(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM weather_data").fetchone()
        return row[0] if row else 0
