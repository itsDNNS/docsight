"""Speedtest storage schema migrations."""

from app.storage.migrations import Migration, add_column_if_missing, table_columns, table_exists


_ENRICHED_COLUMNS = (
    ("isp", "TEXT"), ("server_host", "TEXT"), ("server_location", "TEXT"),
    ("server_country", "TEXT"), ("server_ip", "TEXT"), ("ping_low", "REAL"),
    ("ping_high", "REAL"), ("dl_latency_iqm", "REAL"),
    ("dl_latency_jitter", "REAL"), ("ul_latency_iqm", "REAL"),
    ("ul_latency_jitter", "REAL"), ("dl_bytes", "INTEGER"),
    ("ul_bytes", "INTEGER"), ("dl_elapsed_ms", "INTEGER"),
    ("ul_elapsed_ms", "INTEGER"), ("external_ip", "TEXT"),
    ("is_vpn", "INTEGER"), ("result_url", "TEXT"),
)


def _apply_baseline(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS speedtest_results ("
        "id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, download_mbps REAL, upload_mbps REAL, "
        "download_human TEXT, upload_human TEXT, ping_ms REAL, jitter_ms REAL, "
        "packet_loss_pct REAL, server_id INTEGER, server_name TEXT, "
        "is_demo INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_speedtest_ts ON speedtest_results(timestamp)")
    conn.execute("CREATE TABLE IF NOT EXISTS speedtest_meta (key TEXT PRIMARY KEY, value TEXT)")


def _baseline_applied(_conn):
    # Replay idempotent schema declarations once to repair missing indexes.
    return False


def _columns_applied(conn):
    columns = table_columns(conn, "speedtest_results")
    required = {"server_id", "server_name", "is_demo", *(name for name, _ in _ENRICHED_COLUMNS)}
    return not columns or required <= columns


def _apply_columns(conn):
    add_column_if_missing(conn, "speedtest_results", "server_id", "server_id INTEGER")
    add_column_if_missing(conn, "speedtest_results", "server_name", "server_name TEXT")
    add_column_if_missing(
        conn, "speedtest_results", "is_demo", "is_demo INTEGER NOT NULL DEFAULT 0"
    )
    for name, column_type in _ENRICHED_COLUMNS:
        add_column_if_missing(
            conn, "speedtest_results", name, f"{name} {column_type}"
        )


MIGRATIONS = (
    Migration("speedtest-0001-baseline", _apply_baseline, _baseline_applied),
    Migration("speedtest-0002-columns", _apply_columns, _columns_applied),
)
