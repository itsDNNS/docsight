"""Connection Monitor storage schema migrations."""

from app.storage.migrations import Migration, add_column_if_missing, table_columns, table_exists


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS connection_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL, host TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT 1, poll_interval_ms INTEGER NOT NULL DEFAULT 5000,
        probe_method TEXT NOT NULL DEFAULT 'auto', tcp_port INTEGER NOT NULL DEFAULT 443,
        is_demo INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS connection_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT, target_id INTEGER NOT NULL,
        timestamp REAL NOT NULL, latency_ms REAL, timeout BOOLEAN NOT NULL DEFAULT 0,
        probe_method TEXT NOT NULL,
        FOREIGN KEY (target_id) REFERENCES connection_targets(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_samples_target_ts ON connection_samples (target_id, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS connection_samples_aggregated (
        id INTEGER PRIMARY KEY AUTOINCREMENT, target_id INTEGER NOT NULL,
        bucket_start REAL NOT NULL, bucket_seconds INTEGER NOT NULL,
        avg_latency_ms REAL, min_latency_ms REAL, max_latency_ms REAL,
        p95_latency_ms REAL, packet_loss_pct REAL NOT NULL, sample_count INTEGER NOT NULL,
        FOREIGN KEY (target_id) REFERENCES connection_targets(id) ON DELETE CASCADE,
        UNIQUE(target_id, bucket_start, bucket_seconds)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agg_target_bucket
    ON connection_samples_aggregated (target_id, bucket_seconds, bucket_start)
    """,
    """
    CREATE TABLE IF NOT EXISTS connection_monitor_pinned_days (
        date TEXT NOT NULL PRIMARY KEY, label TEXT, created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS traceroute_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT, target_id INTEGER NOT NULL,
        timestamp REAL NOT NULL, trigger_reason TEXT NOT NULL, hop_count INTEGER NOT NULL,
        route_fingerprint TEXT, reached_target INTEGER NOT NULL DEFAULT 0,
        is_demo INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (target_id) REFERENCES connection_targets(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_traces_target_ts ON traceroute_traces(target_id, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS traceroute_hops (
        id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id INTEGER NOT NULL,
        hop_index INTEGER NOT NULL, hop_ip TEXT, hop_host TEXT, latency_ms REAL,
        probes_responded INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (trace_id) REFERENCES traceroute_traces(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_hops_trace ON traceroute_hops(trace_id)",
)


def _apply_baseline(conn):
    for statement in _SCHEMA:
        conn.execute(statement)


def _baseline_applied(_conn):
    # Replay idempotent schema declarations once to repair missing indexes.
    return False


def _demo_applied(conn):
    columns = table_columns(conn, "connection_targets")
    return not columns or "is_demo" in columns


def _apply_demo(conn):
    add_column_if_missing(
        conn, "connection_targets", "is_demo", "is_demo INTEGER NOT NULL DEFAULT 0"
    )


MIGRATIONS = (
    Migration("connection-monitor-0001-baseline", _apply_baseline, _baseline_applied),
    Migration("connection-monitor-0002-demo-flag", _apply_demo, _demo_applied),
)
