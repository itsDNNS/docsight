"""Standalone speedtest result storage."""

import logging
import sqlite3

log = logging.getLogger("docsis.storage.speedtest")


class SpeedtestStorage:
    """Standalone speedtest data storage (not a mixin).

    Creates the speedtest_results table if it doesn't exist.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """Create the speedtest_results table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS speedtest_results ("
                "  id INTEGER PRIMARY KEY,"
                "  timestamp TEXT NOT NULL,"
                "  download_mbps REAL,"
                "  upload_mbps REAL,"
                "  download_human TEXT,"
                "  upload_human TEXT,"
                "  ping_ms REAL,"
                "  jitter_ms REAL,"
                "  packet_loss_pct REAL,"
                "  server_id INTEGER,"
                "  server_name TEXT,"
                "  is_demo INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_speedtest_ts "
                "ON speedtest_results(timestamp)"
            )
            # Migration: add server_id/server_name columns if missing
            try:
                conn.execute("ALTER TABLE speedtest_results ADD COLUMN server_id INTEGER")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE speedtest_results ADD COLUMN server_name TEXT")
            except Exception:
                pass
            # Migration: add is_demo column if missing
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(speedtest_results)").fetchall()]
                if "is_demo" not in cols:
                    conn.execute("ALTER TABLE speedtest_results ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

    def save_speedtest_results(self, results):
        """Bulk insert speedtest results, ignoring duplicates by id."""
        if not results:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO speedtest_results "
                    "(id, timestamp, download_mbps, upload_mbps, download_human, "
                    "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                    "server_id, server_name) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            r["id"], r["timestamp"], r["download_mbps"],
                            r["upload_mbps"], r["download_human"], r["upload_human"],
                            r["ping_ms"], r["jitter_ms"], r["packet_loss_pct"],
                            r.get("server_id"), r.get("server_name", ""),
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
                "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                "server_id, server_name "
                "FROM speedtest_results ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_speedtest_by_id(self, result_id):
        """Return a single speedtest result by id, or None."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                "server_id, server_name "
                "FROM speedtest_results WHERE id = ?",
                (result_id,),
            ).fetchone()
        return dict(row) if row else None

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

    def get_recent_speedtests(self, limit=10):
        """Return the N most recent speedtest results."""
        return self.get_speedtest_results(limit=limit)

    def get_speedtest_in_range(self, start_ts, end_ts):
        """Return speedtest results within a time range, oldest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct "
                "FROM speedtest_results "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]
