"""SQLite storage for Connection Monitor targets and samples."""

import logging
import os
import sqlite3
import time

logger = logging.getLogger(__name__)


class ConnectionMonitorStorage:
    """Manages connection_targets and connection_samples tables."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS connection_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    host TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    poll_interval_ms INTEGER NOT NULL DEFAULT 5000,
                    probe_method TEXT NOT NULL DEFAULT 'auto',
                    tcp_port INTEGER NOT NULL DEFAULT 443,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS connection_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    latency_ms REAL,
                    timeout BOOLEAN NOT NULL DEFAULT 0,
                    probe_method TEXT NOT NULL,
                    FOREIGN KEY (target_id) REFERENCES connection_targets(id)
                        ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_samples_target_ts
                ON connection_samples (target_id, timestamp)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS connection_samples_aggregated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    bucket_start REAL NOT NULL,
                    bucket_seconds INTEGER NOT NULL,
                    avg_latency_ms REAL,
                    min_latency_ms REAL,
                    max_latency_ms REAL,
                    p95_latency_ms REAL,
                    packet_loss_pct REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    FOREIGN KEY (target_id) REFERENCES connection_targets(id)
                        ON DELETE CASCADE,
                    UNIQUE(target_id, bucket_start, bucket_seconds)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agg_target_bucket
                ON connection_samples_aggregated (target_id, bucket_seconds, bucket_start)
            """)

    # --- Target CRUD ---

    def create_target(
        self,
        label: str,
        host: str,
        enabled: bool = True,
        poll_interval_ms: int = 5000,
        probe_method: str = "auto",
        tcp_port: int = 443,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO connection_targets
                   (label, host, enabled, poll_interval_ms, probe_method, tcp_port, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (label, host, enabled, poll_interval_ms, probe_method, tcp_port, time.time()),
            )
            return cur.lastrowid

    def get_targets(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM connection_targets ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_target(self, target_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM connection_targets WHERE id = ?", (target_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_target(self, target_id: int, **fields) -> bool:
        allowed = {"label", "host", "enabled", "poll_interval_ms", "probe_method", "tcp_port"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [target_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE connection_targets SET {set_clause} WHERE id = ?",
                values,
            )
            return True

    def delete_target(self, target_id: int):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM connection_targets WHERE id = ?", (target_id,)
            )

    # --- Samples ---

    def save_samples(self, samples: list[dict]):
        if not samples:
            return
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO connection_samples
                   (target_id, timestamp, latency_ms, timeout, probe_method)
                   VALUES (:target_id, :timestamp, :latency_ms, :timeout, :probe_method)""",
                samples,
            )

    def get_samples(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        """Get samples for a target. limit <= 0 means no limit."""
        clauses = ["target_id = ?"]
        params: list = [target_id]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        query = f"SELECT * FROM connection_samples WHERE {where} ORDER BY timestamp"
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # --- Summary ---

    def get_summary(self, target_id: int, window_seconds: int = 60) -> dict:
        cutoff = time.time() - window_seconds
        with self._connect() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) as sample_count,
                    AVG(CASE WHEN timeout = 0 THEN latency_ms END) as avg_latency_ms,
                    MIN(CASE WHEN timeout = 0 THEN latency_ms END) as min_latency_ms,
                    MAX(CASE WHEN timeout = 0 THEN latency_ms END) as max_latency_ms,
                    ROUND(100.0 * SUM(CASE WHEN timeout = 1 THEN 1 ELSE 0 END) / MAX(COUNT(*), 1), 2) as packet_loss_pct
                FROM connection_samples
                WHERE target_id = ? AND timestamp >= ?""",
                (target_id, cutoff),
            ).fetchone()
            return dict(row) if row else {}

    # --- Outages ---

    def get_outages(
        self,
        target_id: int,
        threshold: int = 5,
        start: float | None = None,
        end: float | None = None,
    ) -> list[dict]:
        """Derive outages from consecutive timeout sequences."""
        clauses = ["target_id = ?"]
        params: list = [target_id]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT timestamp, timeout FROM connection_samples WHERE {where} ORDER BY timestamp",
                params,
            ).fetchall()

        outages = []
        run_start = None
        run_count = 0
        for row in rows:
            if row["timeout"]:
                if run_start is None:
                    run_start = row["timestamp"]
                run_count += 1
            else:
                if run_count >= threshold:
                    outages.append({
                        "start": run_start,
                        "end": row["timestamp"],
                        "duration_seconds": round(row["timestamp"] - run_start, 1),
                        "timeout_count": run_count,
                    })
                run_start = None
                run_count = 0
        # Handle ongoing outage at end of data
        if run_count >= threshold:
            last_ts = rows[-1]["timestamp"] if rows else time.time()
            outages.append({
                "start": run_start,
                "end": None,
                "duration_seconds": round(last_ts - run_start, 1),
                "timeout_count": run_count,
            })
        return outages

    # --- Retention ---

    def cleanup(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - (retention_days * 86400)
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM connection_samples WHERE timestamp < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
            if deleted:
                logger.info("Connection Monitor: cleaned up %d old samples", deleted)
            return deleted
