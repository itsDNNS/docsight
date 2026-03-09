"""Segment utilization storage for fritzbox_cable module."""

import sqlite3
import threading
from datetime import datetime, timezone


class SegmentUtilizationStorage:
    """Standalone storage for cable segment utilization data.

    Uses the shared core DB (same db_path), creates its own table.
    Thread-safe via a lock on write operations.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_table()

    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS segment_utilization (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ds_total REAL,
                    us_total REAL,
                    ds_own REAL,
                    us_own REAL
                )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_segment_util_ts
                ON segment_utilization(timestamp)
            """)
            conn.commit()
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, ds_total, us_total, ds_own, us_own):
        """Store a utilization sample with the current UTC timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.save_at(ts, ds_total, us_total, ds_own, us_own)

    def save_at(self, ts, ds_total, us_total, ds_own, us_own):
        """Store a utilization sample at a specific timestamp (ISO format). Skips duplicates."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO segment_utilization (timestamp, ds_total, us_total, ds_own, us_own) VALUES (?, ?, ?, ?, ?)",
                    (ts, ds_total, us_total, ds_own, us_own),
                )
                conn.commit()
            finally:
                conn.close()

    def get_range(self, start_ts, end_ts):
        """Return records within a time range, sorted by timestamp ascending."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT timestamp, ds_total, us_total, ds_own, us_own FROM segment_utilization WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_latest(self, n=1):
        """Return the N most recent records, most recent first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT timestamp, ds_total, us_total, ds_own, us_own FROM segment_utilization ORDER BY timestamp DESC LIMIT ?",
                (n,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_stats(self, start_ts, end_ts):
        """Return min/max/avg statistics for the given time range."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT
                    COUNT(*) as count,
                    AVG(ds_total) as ds_total_avg,
                    MIN(ds_total) as ds_total_min,
                    MAX(ds_total) as ds_total_max,
                    AVG(us_total) as us_total_avg,
                    MIN(us_total) as us_total_min,
                    MAX(us_total) as us_total_max
                FROM segment_utilization
                WHERE timestamp >= ? AND timestamp <= ?""",
                (start_ts, end_ts),
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def cleanup(self, days=365):
        """Delete records older than the given number of days. Returns count deleted."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "DELETE FROM segment_utilization WHERE timestamp < ?", (cutoff,)
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()
