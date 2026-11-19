"""Speedtest storage schema migrations."""

from app.storage.migrations import DEMO_FLAG, add_columns, schema_baseline


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


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS speedtest_results ("
    "id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, download_mbps REAL, upload_mbps REAL, "
    "download_human TEXT, upload_human TEXT, ping_ms REAL, jitter_ms REAL, "
    "packet_loss_pct REAL, server_id INTEGER, server_name TEXT, "
    "is_demo INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS idx_speedtest_ts ON speedtest_results(timestamp)",
    "CREATE TABLE IF NOT EXISTS speedtest_meta (key TEXT PRIMARY KEY, value TEXT)",
)


MIGRATIONS = (
    schema_baseline("speedtest-0001-baseline", _SCHEMA),
    add_columns("speedtest-0002-columns", [
        ("speedtest_results", declaration)
        for declaration in (
            "server_id INTEGER", "server_name TEXT", DEMO_FLAG,
            *(f"{name} {column_type}" for name, column_type in _ENRICHED_COLUMNS),
        )
    ]),
)
