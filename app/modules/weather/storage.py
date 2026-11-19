"""Standalone weather data storage."""

import logging
from app.storage.migrations import run_migrations
from app.storage.sqlite import (
    DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    DatabaseAccess,
    bulk_write,
    open_read,
)
from app.tz import normalize_range_ts
from .migrations import MIGRATIONS
import threading
from collections import defaultdict
from pathlib import Path

log = logging.getLogger("docsis.storage.weather")


class WeatherStorage(DatabaseAccess):
    """Standalone weather data storage (not a mixin).

    Creates the weather_data table if it doesn't exist.
    """

    BUSY_TIMEOUT_MS = DEFAULT_SQLITE_BUSY_TIMEOUT_MS
    _locks = defaultdict(threading.RLock)

    def __init__(self, db_path):
        self.db_path = db_path
        lock_key = str(Path(db_path).expanduser().resolve(strict=False))
        self._lock = self._locks[lock_key]
        self._ensure_table()

    def _ensure_table(self):
        """Create the weather_data table if it doesn't exist."""
        with self._lock:
            run_migrations(self.db_path, MIGRATIONS)

    def save_weather_data(self, records, is_demo=False):
        """Bulk insert weather records, ignoring duplicates by timestamp.

        Args:
            records: list of dicts with 'timestamp' and 'temperature' keys
            is_demo: True for demo-seeded data
        """
        if not records:
            return
        try:
            with self._lock:
                bulk_write(
                    self.db_path,
                    "INSERT OR IGNORE INTO weather_data "
                    "(timestamp, temperature, is_demo) VALUES (?, ?, ?)",
                    [(r["timestamp"], r["temperature"], int(is_demo)) for r in records],
                )
            log.debug("Saved %d weather records", len(records))
        except Exception as e:
            log.error("Failed to save weather data: %s", e)

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
