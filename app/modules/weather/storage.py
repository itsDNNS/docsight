"""Standalone weather data storage."""

import logging
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path

log = logging.getLogger("docsis.storage.weather")


def _normalize_range_ts(ts, separator=" "):
    """Accept either ISO 'T' or legacy space-separated timestamps for queries."""
    if not ts or len(ts) < 19:
        return ts
    if ts[10] not in ("T", " "):
        return ts
    return ts[:10] + separator + ts[11:]


class WeatherStorage:
    """Standalone weather data storage (not a mixin).

    Creates the weather_data table if it doesn't exist.
    """

    BUSY_TIMEOUT_MS = 5000
    _locks = defaultdict(threading.RLock)

    def __init__(self, db_path):
        self.db_path = db_path
        lock_key = str(Path(db_path).expanduser().resolve(strict=False))
        self._lock = self._locks[lock_key]
        self._ensure_table()

    def _connect(self):
        """Return a connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
        return conn

    def _ensure_table(self):
        """Create the weather_data table if it doesn't exist."""
        with self._lock:
            with self._connect() as conn:
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
            with self._lock:
                with self._connect() as conn:
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
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, temperature FROM weather_data "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_weather_in_range(self, start_ts, end_ts):
        """Return weather data within a timestamp range, oldest first."""
        start_ts = _normalize_range_ts(start_ts, " ")
        end_ts = _normalize_range_ts(end_ts, " ")
        with self._connect() as conn:
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
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM weather_data").fetchone()
        return row[0] if row else 0
