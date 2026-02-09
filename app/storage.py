"""SQLite snapshot storage for DOCSIS timeline."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

log = logging.getLogger("docsis.storage")


class SnapshotStorage:
    """Persist DOCSIS analysis snapshots to SQLite."""

    def __init__(self, db_path, max_days=7):
        self.db_path = db_path
        self.max_days = max_days
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
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

    def save_snapshot(self, analysis):
        """Save current analysis as a snapshot. Runs cleanup afterwards."""
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
                    (
                        ts,
                        json.dumps(analysis["summary"]),
                        json.dumps(analysis["ds_channels"]),
                        json.dumps(analysis["us_channels"]),
                    ),
                )
            log.debug("Snapshot saved: %s", ts)
        except Exception as e:
            log.error("Failed to save snapshot: %s", e)
            return
        self._cleanup()

    def get_snapshot_list(self):
        """Return list of available snapshot timestamps (newest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_snapshot(self, timestamp):
        """Load a single snapshot by timestamp. Returns analysis dict or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT summary_json, ds_channels_json, us_channels_json FROM snapshots WHERE timestamp = ?",
                (timestamp,),
            ).fetchone()
        if not row:
            return None
        return {
            "summary": json.loads(row[0]),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
        }

    def get_dates_with_data(self):
        """Return list of dates (YYYY-MM-DD) that have at least one snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT substr(timestamp, 1, 10) as day FROM snapshots ORDER BY day"
            ).fetchall()
        return [r[0] for r in rows]

    def get_daily_snapshot(self, date, target_time="06:00"):
        """Get the snapshot closest to target_time on the given date."""
        target_ts = f"{date}T{target_time}:00"
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT timestamp, summary_json, ds_channels_json, us_channels_json
                   FROM snapshots
                   WHERE timestamp LIKE ?
                   ORDER BY ABS(julianday(timestamp) - julianday(?))
                   LIMIT 1""",
                (f"{date}%", target_ts),
            ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "summary": json.loads(row[1]),
            "ds_channels": json.loads(row[2]),
            "us_channels": json.loads(row[3]),
        }

    def get_trend_data(self, start_date, end_date, target_time="06:00"):
        """Get summary data points for a date range, one per day (closest to target_time).
        Returns list of {date, timestamp, ...summary_fields}."""
        dates = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT substr(timestamp, 1, 10) as day FROM snapshots WHERE day >= ? AND day <= ? ORDER BY day",
                (start_date, end_date),
            ).fetchall()
            dates = [r[0] for r in rows]

        results = []
        for date in dates:
            snap = self.get_daily_snapshot(date, target_time)
            if snap:
                entry = {"date": date, "timestamp": snap["timestamp"]}
                entry.update(snap["summary"])
                results.append(entry)
        return results

    def get_intraday_data(self, date):
        """Get all snapshots for a single day (for day-detail trends)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots WHERE timestamp LIKE ? ORDER BY timestamp",
                (f"{date}%",),
            ).fetchall()
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(json.loads(row[1]))
            results.append(entry)
        return results

    def _cleanup(self):
        """Delete snapshots older than max_days."""
        cutoff = (datetime.now() - timedelta(days=self.max_days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM snapshots WHERE timestamp < ?", (cutoff,)
            ).rowcount
        if deleted:
            log.info("Cleaned up %d old snapshots (before %s)", deleted, cutoff)
