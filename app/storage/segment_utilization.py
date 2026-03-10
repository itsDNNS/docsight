"""Segment utilization storage (standalone, not a core mixin)."""

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

    def downsample(self, fine_after_days=7, fine_bucket_min=5, coarse_after_days=30, coarse_bucket_min=15):
        """Aggregate old samples into time-bucketed averages.

        - Samples older than fine_after_days (default 7): averaged into fine_bucket_min (5-min) buckets
        - Samples older than coarse_after_days (default 30): averaged into coarse_bucket_min (15-min) buckets

        Returns total number of rows removed by aggregation.
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        removed = 0

        tiers = [
            (coarse_after_days, coarse_bucket_min),  # coarse first (older data)
            (fine_after_days, fine_bucket_min),
        ]

        for after_days, bucket_min in tiers:
            cutoff = (now - timedelta(days=after_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            removed += self._downsample_range(cutoff, bucket_min)

        return removed

    def _downsample_range(self, before_ts, bucket_minutes):
        """Aggregate all samples before before_ts into bucket_minutes-wide averages."""
        with self._lock:
            conn = self._connect()
            try:
                # Bucket key: floor minute to nearest bucket boundary
                # timestamp format: 2025-03-02T14:23:45Z
                # substr(timestamp,1,14) = "2025-03-02T14:"
                # substr(timestamp,15,2) = "23" (minutes)
                bucket_expr = (
                    "substr(timestamp,1,14) || "
                    f"printf('%02d', (CAST(substr(timestamp,15,2) AS INTEGER) / {bucket_minutes}) * {bucket_minutes}) || "
                    "':00Z'"
                )

                # Find buckets with >1 sample (only those need aggregation)
                rows = conn.execute(
                    f"SELECT {bucket_expr} as bucket_ts, "
                    "AVG(ds_total) as ds_total, AVG(us_total) as us_total, "
                    "AVG(ds_own) as ds_own, AVG(us_own) as us_own, "
                    "COUNT(*) as cnt "
                    "FROM segment_utilization "
                    "WHERE timestamp < ? "
                    f"GROUP BY bucket_ts HAVING cnt > 1",
                    (before_ts,),
                ).fetchall()

                if not rows:
                    return 0

                # Delete all rows in affected buckets, then insert averages
                removed = 0
                for row in rows:
                    bucket_ts = row["bucket_ts"]
                    conn.execute(
                        f"DELETE FROM segment_utilization "
                        f"WHERE timestamp < ? AND {bucket_expr} = ?",
                        (before_ts, bucket_ts),
                    )
                    deleted = conn.execute("SELECT changes()").fetchone()[0]
                    conn.execute(
                        "INSERT OR IGNORE INTO segment_utilization "
                        "(timestamp, ds_total, us_total, ds_own, us_own) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (bucket_ts, row["ds_total"], row["us_total"], row["ds_own"], row["us_own"]),
                    )
                    removed += deleted - 1  # -1 because we re-inserted one averaged row

                conn.commit()
                return removed
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
