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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bqm_graphs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    image_blob BLOB NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speedtest_results (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    download_mbps REAL,
                    upload_mbps REAL,
                    download_human TEXT,
                    upload_human TEXT,
                    ping_ms REAL,
                    jitter_ms REAL,
                    packet_loss_pct REAL
                )
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

    def get_range_data(self, start_ts, end_ts):
        """Get all snapshots between two ISO timestamps (inclusive)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json, ds_channels_json, us_channels_json "
                "FROM snapshots WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        results = []
        for row in rows:
            entry = {
                "timestamp": row[0],
                "summary": json.loads(row[1]),
                "ds_channels": json.loads(row[2]),
                "us_channels": json.loads(row[3]),
            }
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

    def save_bqm_graph(self, image_data):
        """Save BQM graph for today. Skips if already exists (UNIQUE date)."""
        today = datetime.now().strftime("%Y-%m-%d")
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                    (today, ts, image_data),
                )
            log.debug("BQM graph saved for %s", today)
        except Exception as e:
            log.error("Failed to save BQM graph: %s", e)

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

    # ── Speedtest result caching ──

    def save_speedtest_results(self, results):
        """Bulk insert speedtest results, ignoring duplicates by id."""
        if not results:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO speedtest_results "
                    "(id, timestamp, download_mbps, upload_mbps, download_human, "
                    "upload_human, ping_ms, jitter_ms, packet_loss_pct) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            r["id"], r["timestamp"], r["download_mbps"],
                            r["upload_mbps"], r["download_human"], r["upload_human"],
                            r["ping_ms"], r["jitter_ms"], r["packet_loss_pct"],
                        )
                        for r in results
                    ],
                )
            log.debug("Saved %d speedtest results", len(results))
        except Exception as e:
            log.error("Failed to save speedtest results: %s", e)

    def get_speedtest_results(self, limit=2000):
        """Return cached speedtest results, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct "
                "FROM speedtest_results ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_speedtest_count(self):
        """Return number of cached speedtest results."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM speedtest_results").fetchone()
        return row[0] if row else 0

    def get_latest_speedtest_id(self):
        """Return the highest speedtest result id, or 0 if none."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(id) FROM speedtest_results"
            ).fetchone()
        return row[0] or 0 if row else 0

    def _cleanup(self):
        """Delete snapshots and BQM graphs older than max_days. 0 = keep all."""
        if self.max_days <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=self.max_days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM snapshots WHERE timestamp < ?", (cutoff,)
            ).rowcount
        if deleted:
            log.info("Cleaned up %d old snapshots (before %s)", deleted, cutoff)
        cutoff_date = (datetime.now() - timedelta(days=self.max_days)).strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            bqm_deleted = conn.execute(
                "DELETE FROM bqm_graphs WHERE date < ?", (cutoff_date,)
            ).rowcount
        if bqm_deleted:
            log.info("Cleaned up %d old BQM graphs (before %s)", bqm_deleted, cutoff_date)
