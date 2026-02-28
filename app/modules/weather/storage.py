"""Standalone weather data storage."""

import logging
import sqlite3

log = logging.getLogger("docsis.storage.weather")


class WeatherStorage:
    """Standalone weather data storage (not a mixin).

    Creates the weather_data table if it doesn't exist.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """Create the weather_data table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS weather_data ("
                "  timestamp TEXT PRIMARY KEY,"
                "  temperature REAL NOT NULL,"
                "  is_demo INTEGER DEFAULT 0"
                ")"
            )

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
