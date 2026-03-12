"""SQLite storage for Connection Monitor targets and samples."""

import logging
import math
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

    def _build_sample_where(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
    ) -> tuple[str, list]:
        clauses = ["target_id = ?"]
        params: list = [target_id]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        return " AND ".join(clauses), params

    def get_samples(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
        limit: int = 10000,
        max_points: int | None = None,
    ) -> list[dict]:
        """Get samples for a target. limit <= 0 means no limit."""
        where, params = self._build_sample_where(target_id, start=start, end=end)

        if max_points and max_points > 0:
            with self._connect() as conn:
                total_count = conn.execute(
                    f"SELECT COUNT(*) FROM connection_samples WHERE {where}",
                    params,
                ).fetchone()[0]
                if total_count > max_points:
                    bucket_base = start or 0
                    bucket_seconds = max(
                        1,
                        math.ceil(((end or time.time()) - (start or 0)) / max_points),
                    )
                    rows = conn.execute(
                        f"""
                        SELECT
                            ? + CAST((timestamp - ?) / ? AS INTEGER) * ? AS timestamp,
                            AVG(CASE WHEN timeout = 0 THEN latency_ms END) AS latency_ms,
                            MAX(CASE WHEN timeout = 1 THEN 1 ELSE 0 END) AS timeout,
                            MIN(probe_method) AS probe_method,
                            COUNT(*) AS sample_count,
                            SUM(CASE WHEN timeout = 1 THEN 1 ELSE 0 END) AS timeout_count
                        FROM connection_samples
                        WHERE {where}
                        GROUP BY CAST((timestamp - ?) / ? AS INTEGER)
                        ORDER BY timestamp
                        """,
                        [
                            bucket_base,
                            bucket_base,
                            bucket_seconds,
                            bucket_seconds,
                            *params,
                            bucket_base,
                            bucket_seconds,
                        ],
                    ).fetchall()
                    return [dict(r) for r in rows]

        query = f"SELECT * FROM connection_samples WHERE {where} ORDER BY timestamp"
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_range_stats(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
    ) -> dict:
        where, params = self._build_sample_where(target_id, start=start, end=end)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS sample_count,
                    COUNT(CASE WHEN timeout = 0 AND latency_ms IS NOT NULL THEN 1 END) AS latency_count,
                    AVG(CASE WHEN timeout = 0 THEN latency_ms END) AS avg_latency_ms,
                    MIN(CASE WHEN timeout = 0 THEN latency_ms END) AS min_latency_ms,
                    MAX(CASE WHEN timeout = 0 THEN latency_ms END) AS max_latency_ms,
                    ROUND(
                        100.0 * SUM(CASE WHEN timeout = 1 THEN 1 ELSE 0 END) / MAX(COUNT(*), 1),
                        2
                    ) AS packet_loss_pct
                FROM connection_samples
                WHERE {where}
                """,
                params,
            ).fetchone()
            stats = dict(row) if row else {}
            latency_count = stats.get("latency_count") or 0
            if latency_count > 0:
                p95_offset = max(0, math.ceil(latency_count * 0.95) - 1)
                p95_row = conn.execute(
                    f"""
                    SELECT latency_ms
                    FROM connection_samples
                    WHERE {where} AND timeout = 0 AND latency_ms IS NOT NULL
                    ORDER BY latency_ms
                    LIMIT 1 OFFSET ?
                    """,
                    [*params, p95_offset],
                ).fetchone()
                stats["p95_latency_ms"] = p95_row["latency_ms"] if p95_row else None
            else:
                stats["p95_latency_ms"] = None
            return stats

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

    # --- Aggregation ---

    def get_aggregated_samples(
        self,
        target_id: int,
        bucket_seconds: int,
        start: float | None = None,
        end: float | None = None,
    ) -> list[dict]:
        """Get aggregated samples for a target at a specific resolution."""
        clauses = ["target_id = ?", "bucket_seconds = ?"]
        params: list = [target_id, bucket_seconds]
        if start is not None:
            clauses.append("bucket_start >= ?")
            params.append(start)
        if end is not None:
            clauses.append("bucket_start <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM connection_samples_aggregated WHERE {where} ORDER BY bucket_start",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def aggregate_raw_to_buckets(
        self, target_id: int, cutoff: float, bucket_seconds: int = 60
    ) -> int:
        """Aggregate raw samples older than cutoff into fixed-size buckets.

        Computes avg/min/max/p95 latency, packet loss %, and sample count
        per bucket. Deletes aggregated raw samples. Returns number of
        buckets created.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT timestamp, latency_ms, timeout
                   FROM connection_samples
                   WHERE target_id = ? AND timestamp < ?
                   ORDER BY timestamp""",
                (target_id, cutoff),
            ).fetchall()

            if not rows:
                return 0

            buckets: dict[float, list] = {}
            for row in rows:
                bucket_start = (row["timestamp"] // bucket_seconds) * bucket_seconds
                if bucket_start not in buckets:
                    buckets[bucket_start] = []
                buckets[bucket_start].append(row)

            created = 0
            for bucket_start, samples in buckets.items():
                latencies = [
                    s["latency_ms"] for s in samples
                    if not s["timeout"] and s["latency_ms"] is not None
                ]
                total = len(samples)
                timeouts = sum(1 for s in samples if s["timeout"])

                avg_lat = sum(latencies) / len(latencies) if latencies else None
                min_lat = min(latencies) if latencies else None
                max_lat = max(latencies) if latencies else None
                loss_pct = round(timeouts / total * 100, 2) if total > 0 else 0.0

                # p95 via nearest-rank
                p95_lat = None
                if latencies:
                    sorted_lat = sorted(latencies)
                    idx = min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)
                    p95_lat = sorted_lat[idx]

                conn.execute(
                    """INSERT OR REPLACE INTO connection_samples_aggregated
                       (target_id, bucket_start, bucket_seconds,
                        avg_latency_ms, min_latency_ms, max_latency_ms,
                        p95_latency_ms, packet_loss_pct, sample_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (target_id, bucket_start, bucket_seconds,
                     avg_lat, min_lat, max_lat, p95_lat, loss_pct, total),
                )
                created += 1

            conn.execute(
                "DELETE FROM connection_samples WHERE target_id = ? AND timestamp < ?",
                (target_id, cutoff),
            )

            if created:
                logger.info(
                    "Connection Monitor: aggregated %d raw samples into %d buckets (%ds) for target %d",
                    len(rows), created, bucket_seconds, target_id,
                )
            return created

    def reaggregate_buckets(
        self,
        target_id: int,
        cutoff: float,
        source_seconds: int,
        target_seconds: int,
    ) -> int:
        """Roll up smaller aggregated buckets into larger ones.

        Aggregates source_seconds buckets older than cutoff into
        target_seconds buckets, then deletes the source buckets.
        p95 is approximated as MAX(p95) of constituent buckets.
        Returns number of target buckets created.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT bucket_start, avg_latency_ms, min_latency_ms,
                          max_latency_ms, p95_latency_ms, packet_loss_pct,
                          sample_count
                   FROM connection_samples_aggregated
                   WHERE target_id = ? AND bucket_seconds = ? AND bucket_start < ?
                   ORDER BY bucket_start""",
                (target_id, source_seconds, cutoff),
            ).fetchall()

            if not rows:
                return 0

            # Group into target-sized buckets
            buckets: dict[float, list] = {}
            for row in rows:
                bucket_start = (row["bucket_start"] // target_seconds) * target_seconds
                if bucket_start not in buckets:
                    buckets[bucket_start] = []
                buckets[bucket_start].append(row)

            created = 0
            for bucket_start, sources in buckets.items():
                total_count = sum(s["sample_count"] for s in sources)
                # Weighted average for avg_latency
                non_null = [s for s in sources if s["avg_latency_ms"] is not None]
                if non_null:
                    weight_sum = sum(s["sample_count"] for s in non_null)
                    avg_lat = sum(
                        s["avg_latency_ms"] * s["sample_count"] for s in non_null
                    ) / weight_sum if weight_sum > 0 else None
                    min_lat = min(s["min_latency_ms"] for s in non_null)
                    max_lat = max(s["max_latency_ms"] for s in non_null)
                    p95_vals = [s["p95_latency_ms"] for s in non_null if s["p95_latency_ms"] is not None]
                    p95_lat = max(p95_vals) if p95_vals else None
                else:
                    avg_lat = min_lat = max_lat = p95_lat = None

                # Weighted loss
                loss_pct = round(
                    sum(s["packet_loss_pct"] * s["sample_count"] for s in sources)
                    / total_count, 2
                ) if total_count > 0 else 0.0

                conn.execute(
                    """INSERT OR REPLACE INTO connection_samples_aggregated
                       (target_id, bucket_start, bucket_seconds,
                        avg_latency_ms, min_latency_ms, max_latency_ms,
                        p95_latency_ms, packet_loss_pct, sample_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (target_id, bucket_start, target_seconds,
                     avg_lat, min_lat, max_lat, p95_lat, loss_pct, total_count),
                )
                created += 1

            # Delete source buckets
            conn.execute(
                """DELETE FROM connection_samples_aggregated
                   WHERE target_id = ? AND bucket_seconds = ? AND bucket_start < ?""",
                (target_id, source_seconds, cutoff),
            )

            if created:
                logger.info(
                    "Connection Monitor: re-aggregated %d x %ds buckets into %d x %ds buckets for target %d",
                    len(rows), source_seconds, created, target_seconds, target_id,
                )
            return created

    # Tier boundaries in seconds
    _TIER_RAW_MAX_AGE = 7 * 86400       # 7 days
    _TIER_60S_MAX_AGE = 30 * 86400      # 30 days
    _TIER_300S_MAX_AGE = 90 * 86400     # 90 days

    def aggregate(self):
        """Run the full aggregation cascade for all targets.

        1. Raw samples older than 7d -> 60s buckets
        2. 60s buckets older than 30d -> 300s buckets
        3. 300s buckets older than 90d -> 3600s buckets
        """
        now = time.time()
        targets = self.get_targets()
        for t in targets:
            tid = t["id"]
            # Step 1: raw -> 60s
            self.aggregate_raw_to_buckets(
                tid, cutoff=now - self._TIER_RAW_MAX_AGE, bucket_seconds=60
            )
            # Step 2: 60s -> 300s
            self.reaggregate_buckets(
                tid, cutoff=now - self._TIER_60S_MAX_AGE,
                source_seconds=60, target_seconds=300
            )
            # Step 3: 300s -> 3600s
            self.reaggregate_buckets(
                tid, cutoff=now - self._TIER_300S_MAX_AGE,
                source_seconds=300, target_seconds=3600
            )

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
            cur2 = conn.execute(
                "DELETE FROM connection_samples_aggregated WHERE bucket_start < ?",
                (cutoff,),
            )
            deleted += cur2.rowcount
            if deleted:
                logger.info("Connection Monitor: cleaned up %d old samples/buckets", deleted)
            return deleted
