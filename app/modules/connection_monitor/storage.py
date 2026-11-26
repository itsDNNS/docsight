"""SQLite storage for Connection Monitor targets and samples."""

import logging
import math
import os
from datetime import date, timedelta

from app.storage.migrations import run_migrations
from app.storage.sqlite import DatabaseAccess, bulk_write
from app.tz import local_to_utc, parse_utc
from .migrations import MIGRATIONS
import time

logger = logging.getLogger(__name__)

# Raw samples are kept this long, 60 s buckets until AGG_60S_MAX_AGE, 300 s
# buckets until AGG_300S_MAX_AGE, and 3600 s buckets after that.
RAW_MAX_AGE = 7 * 86400
AGG_60S_MAX_AGE = 30 * 86400
AGG_300S_MAX_AGE = 90 * 86400


def p95_index(count: int) -> int:
    """Index of the nearest-rank 95th percentile among ``count`` sorted values."""
    return math.ceil(count * 0.95) - 1


def pinned_day_range(day, tz_name):
    """UTC epoch range [start, stop) of a pinned local day, or None if it cannot be converted or was skipped."""
    try:
        start = date.fromisoformat(day)
        bounds = [parse_utc(local_to_utc(f"{d}T00:00:00", tz_name)).timestamp()
                  for d in (start, start + timedelta(days=1))]
    except (ValueError, TypeError, OverflowError):
        return None
    return bounds if bounds[0] < bounds[1] else None


class ConnectionMonitorStorage(DatabaseAccess):
    """Manages connection_targets and connection_samples tables."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_tables()

    def _init_tables(self):
        run_migrations(self.db_path, MIGRATIONS)

    # --- Pinned Days ---

    def pin_day(self, date: str, label: str | None = None):
        with self._write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO connection_monitor_pinned_days (date, label, created_at) VALUES (?, ?, ?)",
                (date, label, time.time()),
            )

    def unpin_day(self, date: str) -> bool:
        with self._write() as conn:
            cur = conn.execute(
                "DELETE FROM connection_monitor_pinned_days WHERE date = ?", (date,)
            )
            return cur.rowcount > 0

    def get_pinned_days(self) -> list[dict]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM connection_monitor_pinned_days ORDER BY date DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _not_pinned(conn, tz_name):
        """SQL condition sparing pinned days, read on the caller's write connection to see every committed pin."""
        ranges = []
        for (day,) in conn.execute("SELECT date FROM connection_monitor_pinned_days"):
            bounds = pinned_day_range(day, tz_name)
            if bounds is None:
                logger.warning("Connection Monitor: ignoring pinned day %r that cannot be converted", day)
            else:
                ranges.append(bounds)
        if not ranges:
            return ""
        # Temporary to this connection, which closes with the transaction.
        conn.execute("CREATE TEMP TABLE pinned_ranges (start REAL PRIMARY KEY, stop REAL)")
        for pinned_range in ranges:
            conn.execute("INSERT INTO pinned_ranges VALUES (?, ?)", pinned_range)
        # Ranges never overlap, so only the last one starting at or before a row can contain it.
        return (" AND timestamp >= IFNULL((SELECT stop FROM pinned_ranges WHERE start <= timestamp"
                " ORDER BY start DESC LIMIT 1), timestamp)")

    # --- Target CRUD ---

    def create_target(
        self,
        label: str,
        host: str,
        enabled: bool = True,
        poll_interval_ms: int = 5000,
        probe_method: str = "auto",
        tcp_port: int = 443,
        is_demo: bool = False,
    ) -> int:
        with self._write() as conn:
            cur = conn.execute(
                """INSERT INTO connection_targets
                   (label, host, enabled, poll_interval_ms, probe_method, tcp_port,
                    is_demo, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    label, host, enabled, poll_interval_ms, probe_method,
                    tcp_port, int(is_demo), time.time(),
                ),
            )
            return cur.lastrowid

    def get_targets(self) -> list[dict]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM connection_targets ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_target(self, target_id: int) -> dict | None:
        with self._read() as conn:
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
        with self._write() as conn:
            conn.execute(
                f"UPDATE connection_targets SET {set_clause} WHERE id = ?",
                values,
            )
            return True

    def delete_target(self, target_id: int):
        with self._write() as conn:
            conn.execute(
                "DELETE FROM connection_targets WHERE id = ?", (target_id,)
            )

    def purge_demo_targets(self) -> int:
        """Delete demo targets and their cascaded samples without touching user targets."""
        with self._write() as conn:
            cur = conn.execute(
                "DELETE FROM connection_targets WHERE is_demo = 1"
            )
            return cur.rowcount

    # --- Samples ---

    def save_samples(self, samples: list[dict]):
        if not samples:
            return
        # A target deleted while its probe ran has no row left; skip its samples
        # instead of failing the foreign key and losing every sample of the cycle.
        bulk_write(
            self.db_path,
            """INSERT INTO connection_samples
               (target_id, timestamp, latency_ms, timeout, probe_method)
               SELECT :target_id, :timestamp, :latency_ms, :timeout, :probe_method
               WHERE EXISTS (SELECT 1 FROM connection_targets WHERE id = :target_id)""",
            samples,
        )

    def _build_sample_where(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
        column: str = "timestamp",
    ) -> tuple[str, list]:
        clauses = ["target_id = ?"]
        params: list[object] = [target_id]
        if start is not None:
            clauses.append(f"{column} >= ?")
            params.append(start)
        if end is not None:
            clauses.append(f"{column} <= ?")
            params.append(end)
        return " AND ".join(clauses), params

    def get_samples(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        """Get samples for a target. limit <= 0 means no limit."""
        where, params = self._build_sample_where(target_id, start=start, end=end)

        query = f"SELECT * FROM connection_samples WHERE {where} ORDER BY timestamp"
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        with self._read() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_range_stats(
        self,
        target_id: int,
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, object]:
        where, params = self._build_sample_where(target_id, start=start, end=end)
        with self._read() as conn:
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
                p95_row = conn.execute(
                    f"""
                    SELECT latency_ms
                    FROM connection_samples
                    WHERE {where} AND timeout = 0 AND latency_ms IS NOT NULL
                    ORDER BY latency_ms
                    LIMIT 1 OFFSET ?
                    """,
                    [*params, p95_index(latency_count)],
                ).fetchone()
                stats["p95_latency_ms"] = p95_row["latency_ms"] if p95_row else None
            else:
                stats["p95_latency_ms"] = None
            return stats

    # --- Summary ---

    def get_summary(
        self, target_id: int, window_seconds: int = 60, end: float | None = None,
    ) -> dict[str, object]:
        """Summarize the samples in the window ending at ``end`` (default: now)."""
        end = time.time() if end is None else end
        return self.get_range_stats(target_id, start=end - window_seconds, end=end)

    def get_latest_sample_time(self, target_id: int) -> float | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) AS latest FROM connection_samples WHERE target_id = ?",
                (target_id,),
            ).fetchone()
        return row["latest"] if row else None

    # --- Outages ---

    def get_outages(
        self,
        target_id: int,
        threshold: int = 5,
        start: float | None = None,
        end: float | None = None,
    ) -> list[dict]:
        """Derive outages from consecutive timeout sequences."""
        where, params = self._build_sample_where(target_id, start=start, end=end)
        with self._read() as conn:
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
        where, params = self._build_sample_where(target_id, start=start, end=end, column="bucket_start")
        with self._read() as conn:
            rows = conn.execute(
                f"SELECT * FROM connection_samples_aggregated WHERE {where} AND bucket_seconds = ?"
                " ORDER BY bucket_start",
                [*params, bucket_seconds],
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _group_by_bucket(rows, column: str, bucket_seconds: int):
        """Group rows into fixed-size buckets by ``column``; returns (bucket_start, rows) pairs."""
        buckets: dict[float, list] = {}
        for row in rows:
            buckets.setdefault((row[column] // bucket_seconds) * bucket_seconds, []).append(row)
        return buckets.items()

    @staticmethod
    def _insert_buckets(conn, buckets: list[tuple]) -> int:
        for bucket in buckets:
            conn.execute(
                """INSERT OR REPLACE INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                bucket,
            )
        return len(buckets)

    def aggregate_raw_to_buckets(
        self, target_id: int, cutoff: float, tz_name: str, bucket_seconds: int = 60
    ) -> int:
        """Aggregate raw samples older than cutoff into fixed-size buckets.

        Computes avg/min/max/p95 latency, packet loss %, and sample count
        per bucket. Deletes aggregated raw samples. Returns number of
        buckets created.
        """
        with self._write() as conn:
            rows = conn.execute(
                """SELECT timestamp, latency_ms, timeout
                   FROM connection_samples
                   WHERE target_id = ? AND timestamp < ?
                   ORDER BY timestamp""",
                (target_id, cutoff),
            ).fetchall()

            if not rows:
                return 0

            buckets = []
            for bucket_start, samples in self._group_by_bucket(rows, "timestamp", bucket_seconds):
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
                p95_lat = sorted(latencies)[p95_index(len(latencies))] if latencies else None
                buckets.append((target_id, bucket_start, bucket_seconds,
                                avg_lat, min_lat, max_lat, p95_lat, loss_pct, total))
            created = self._insert_buckets(conn, buckets)

            conn.execute(
                "DELETE FROM connection_samples WHERE target_id = ? AND timestamp < ?"
                + self._not_pinned(conn, tz_name),
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
        with self._write() as conn:
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

            buckets = []
            for bucket_start, sources in self._group_by_bucket(rows, "bucket_start", target_seconds):
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
                buckets.append((target_id, bucket_start, target_seconds,
                                avg_lat, min_lat, max_lat, p95_lat, loss_pct, total_count))
            created = self._insert_buckets(conn, buckets)

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

    def aggregate(self, tz_name):
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
                tid, cutoff=now - RAW_MAX_AGE, tz_name=tz_name, bucket_seconds=60
            )
            # Step 2: 60s -> 300s
            self.reaggregate_buckets(
                tid, cutoff=now - AGG_60S_MAX_AGE,
                source_seconds=60, target_seconds=300
            )
            # Step 3: 300s -> 3600s
            self.reaggregate_buckets(
                tid, cutoff=now - AGG_300S_MAX_AGE,
                source_seconds=300, target_seconds=3600
            )

    # --- Traceroute CRUD ---

    def save_trace(self, target_id, timestamp, trigger_reason, hops,
                   route_fingerprint, reached_target, is_demo=False):
        with self._write() as conn:
            cur = conn.execute(
                """INSERT INTO traceroute_traces
                   (target_id, timestamp, trigger_reason, hop_count,
                    route_fingerprint, reached_target, is_demo)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (target_id, timestamp, trigger_reason, len(hops),
                 route_fingerprint, int(reached_target), int(is_demo)),
            )
            trace_id = cur.lastrowid
            if hops:
                for hop in hops:
                    conn.execute(
                        """INSERT INTO traceroute_hops
                           (trace_id, hop_index, hop_ip, hop_host, latency_ms, probes_responded)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (trace_id, hop["hop_index"], hop["hop_ip"], hop.get("hop_host"),
                         hop.get("latency_ms"), hop.get("probes_responded", 0)),
                    )
            return trace_id

    def get_traces(self, target_id, start=None, end=None, limit=100):
        where, params = self._build_sample_where(target_id, start=start, end=end)
        with self._read() as conn:
            rows = conn.execute(
                f"SELECT * FROM traceroute_traces WHERE {where} ORDER BY timestamp DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]

    def get_trace(self, trace_id):
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM traceroute_traces WHERE id = ?", (trace_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_trace_hops(self, trace_id):
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM traceroute_hops WHERE trace_id = ? ORDER BY hop_index",
                (trace_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def cleanup_traces(self, retention_days, tz_name):
        if not retention_days:
            return
        cutoff = time.time() - (retention_days * 86400)
        with self._write() as conn:
            conn.execute(
                "DELETE FROM traceroute_traces WHERE timestamp < ?" + self._not_pinned(conn, tz_name), (cutoff,)
            )

    def purge_demo_traces(self):
        with self._write() as conn:
            conn.execute("DELETE FROM traceroute_traces WHERE is_demo = 1")

    # --- Retention ---

    def cleanup(self, retention_days: int, tz_name: str) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - (retention_days * 86400)
        with self._write() as conn:
            cur = conn.execute(
                "DELETE FROM connection_samples WHERE timestamp < ?" + self._not_pinned(conn, tz_name),
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
