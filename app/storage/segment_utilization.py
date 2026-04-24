"""Segment utilization storage (standalone, not a core mixin)."""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone


EVENT_DEFAULT_THRESHOLD = 80
EVENT_DEFAULT_MIN_MINUTES = 3


def _parse_ts(ts):
    """Parse DOCSight's ISO timestamp strings into aware UTC datetimes."""
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _minutes_between(start_dt, end_dt):
    """Whole minutes between two aware datetimes (rounded to nearest)."""
    return int(round((end_dt - start_dt).total_seconds() / 60.0))


def _normalize_range_ts(ts, separator="T"):
    """Accept either ISO 'T' or legacy space-separated timestamps for queries."""
    if not ts or len(ts) < 19:
        return ts
    if ts[10] not in ("T", " "):
        return ts
    return ts[:10] + separator + ts[11:]


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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS segment_utilization_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL,
                    start_ts TEXT NOT NULL,
                    end_ts TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    peak_total REAL,
                    peak_own REAL,
                    peak_neighbor_load REAL,
                    confidence TEXT,
                    threshold INTEGER NOT NULL,
                    min_minutes INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_segment_util_events_key
                ON segment_utilization_events(direction, start_ts, threshold, min_minutes)
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
        start_ts = _normalize_range_ts(start_ts, "T")
        end_ts = _normalize_range_ts(end_ts, "T")
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
        start_ts = _normalize_range_ts(start_ts, "T")
        end_ts = _normalize_range_ts(end_ts, "T")
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

        Before data is downsampled, materialize saturation events at default
        parameters (threshold=80%, min_minutes=3) so that peaks are preserved
        for the long-term events view even after sample averaging.

        Returns total number of rows removed by aggregation.
        """
        now = datetime.now(timezone.utc)
        removed = 0

        # Materialize events BEFORE we lose raw peaks to averaging. Use the
        # earliest cutoff (fine) so any data that's about to be aggregated is
        # inspected first.
        fine_cutoff = (now - timedelta(days=fine_after_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.materialize_events_before(fine_cutoff)

        tiers = [
            (coarse_after_days, coarse_bucket_min),  # coarse first (older data)
            (fine_after_days, fine_bucket_min),
        ]

        for after_days, bucket_min in tiers:
            cutoff = (now - timedelta(days=after_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            removed += self._downsample_range(cutoff, bucket_min)

        return removed

    def materialize_events_before(self, before_ts,
                                  threshold=EVENT_DEFAULT_THRESHOLD,
                                  min_minutes=EVENT_DEFAULT_MIN_MINUTES):
        """Detect saturation events ending before ``before_ts`` and persist them.

        Invoked ahead of downsampling so peak samples drive event records that
        survive future aggregation. Idempotent via a UNIQUE index on
        (direction, start_ts, threshold, min_minutes).

        Returns the number of newly inserted event rows.
        """
        before_ts = _normalize_range_ts(before_ts, "T")
        rows = self.get_range("2000-01-01T00:00:00Z", before_ts)
        if not rows:
            return 0

        events = []
        events.extend(self._detect_runs(rows, "ds_total", "ds_own", "downstream", threshold, min_minutes))
        events.extend(self._detect_runs(rows, "us_total", "us_own", "upstream", threshold, min_minutes))
        # Only materialize runs that are fully inside the historical window.
        # Ongoing runs that extend past ``before_ts`` are still visible via
        # live detection on raw data and would just be duplicates here.
        events = [e for e in events if e["end"] < before_ts]
        if not events:
            return 0

        inserted = 0
        with self._lock:
            conn = self._connect()
            try:
                for ev in events:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO segment_utilization_events "
                        "(direction, start_ts, end_ts, duration_minutes, peak_total, peak_own, "
                        " peak_neighbor_load, confidence, threshold, min_minutes) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            ev["direction"], ev["start"], ev["end"], ev["duration_minutes"],
                            ev["peak_total"], ev["peak_own"], ev["peak_neighbor_load"],
                            ev["confidence"], threshold, min_minutes,
                        ),
                    )
                    if cur.rowcount:
                        inserted += 1
                conn.commit()
            finally:
                conn.close()
        return inserted

    def _load_materialized_events(self, start_ts, end_ts, threshold, min_minutes):
        """Return materialized events that fall within the requested range."""
        start_ts = _normalize_range_ts(start_ts, "T")
        end_ts = _normalize_range_ts(end_ts, "T")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT direction, start_ts, end_ts, duration_minutes, peak_total, peak_own, "
                "peak_neighbor_load, confidence "
                "FROM segment_utilization_events "
                "WHERE threshold = ? AND min_minutes = ? "
                "AND start_ts >= ? AND start_ts <= ? "
                "ORDER BY start_ts",
                (threshold, min_minutes, start_ts, end_ts),
            ).fetchall()
            return [
                {
                    "direction": r["direction"],
                    "start": r["start_ts"],
                    "end": r["end_ts"],
                    "duration_minutes": r["duration_minutes"],
                    "peak_total": r["peak_total"],
                    "peak_own": r["peak_own"],
                    "peak_neighbor_load": r["peak_neighbor_load"],
                    "confidence": r["confidence"],
                }
                for r in rows
            ]
        finally:
            conn.close()

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

    def get_events(self, start_ts, end_ts, threshold=EVENT_DEFAULT_THRESHOLD,
                   min_minutes=EVENT_DEFAULT_MIN_MINUTES):
        """Return segment saturation events within a time range.

        Combines live detection on raw samples (``get_range`` -> ``_detect_runs``)
        with records previously materialized by ``materialize_events_before``.
        Materialized events are preferred because they were computed from raw
        peaks before downsampling averaged them away. Live detection catches
        events in still-raw data (not yet materialized) as well as events with
        non-default thresholds. Dedupe key is (direction, start).

        An event is a window where ds_total or us_total stayed at or above
        ``threshold`` for at least ``min_minutes`` consecutive minute-spaced
        samples. A gap greater than ~90s between adjacent samples breaks a
        raw run.
        """
        rows = self.get_range(start_ts, end_ts)
        detected = []
        if rows:
            detected.extend(self._detect_runs(rows, "ds_total", "ds_own", "downstream", threshold, min_minutes))
            detected.extend(self._detect_runs(rows, "us_total", "us_own", "upstream", threshold, min_minutes))

        stored = self._load_materialized_events(start_ts, end_ts, threshold, min_minutes)

        merged = {}
        for ev in detected:
            merged[(ev["direction"], ev["start"])] = ev
        # Stored records win — they were computed on pre-downsample data.
        for ev in stored:
            merged[(ev["direction"], ev["start"])] = ev

        return sorted(merged.values(), key=lambda e: (e["start"], e["direction"]))

    @staticmethod
    def _detect_runs(rows, total_key, own_key, direction, threshold, min_minutes):
        """Walk rows once, emitting one event per qualifying consecutive run."""
        detected = []
        run = []  # list of (ts_str, parsed_dt, total, own)
        prev_dt = None

        def flush():
            if len(run) >= min_minutes:
                peak_total = max(r[2] for r in run)
                peak_idx = max(range(len(run)), key=lambda i: run[i][2])
                peak_own = run[peak_idx][3] if run[peak_idx][3] is not None else 0.0
                peak_neighbor = max(
                    r[2] - (r[3] if r[3] is not None else 0.0) for r in run
                )
                duration = _minutes_between(run[0][1], run[-1][1]) + 1
                detected.append({
                    "direction": direction,
                    "start": run[0][0],
                    "end": run[-1][0],
                    "duration_minutes": duration,
                    "peak_total": peak_total,
                    "peak_own": peak_own,
                    "peak_neighbor_load": peak_neighbor,
                    "confidence": "high",
                })

        for row in rows:
            total = row.get(total_key)
            ts_str = row["timestamp"]
            dt = _parse_ts(ts_str)
            if total is None or dt is None:
                flush()
                run = []
                prev_dt = None
                continue
            if total < threshold:
                flush()
                run = []
                prev_dt = dt
                continue
            # Above threshold. Break run if gap from previous raw step > ~90s.
            if prev_dt is not None and run:
                gap = (dt - prev_dt).total_seconds()
                if gap > 90:
                    flush()
                    run = []
            run.append((ts_str, dt, total, row.get(own_key)))
            prev_dt = dt

        flush()
        return detected

    def cleanup(self, days=365):
        """Delete records older than the given number of days. Returns count deleted."""
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
