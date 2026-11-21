"""Speedtest storage schema migrations."""

from datetime import datetime, timezone
import logging

from app.storage.migrations import DEMO_FLAG, Migration, add_columns, schema_baseline
from app.tz import UTC_FMT

log = logging.getLogger("docsis.storage.speedtest")


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


def _store_offset_times_in_utc(conn):
    """Older versions stored Tracker times with their offset, which sort apart from UTC times."""
    updated = 0
    for row_id, timestamp in conn.execute(
        "SELECT id, timestamp FROM speedtest_results WHERE timestamp GLOB '*[+-][0-9][0-9]:[0-9][0-9]'"
    ).fetchall():
        try:
            parsed = datetime.fromisoformat(timestamp)
        except (ValueError, TypeError):
            continue
        if parsed.tzinfo is not None:
            conn.execute("UPDATE speedtest_results SET timestamp = ? WHERE id = ?",
                         (parsed.astimezone(timezone.utc).strftime(UTC_FMT), row_id))
            updated += 1
    # Versions before this migration check the flag themselves
    conn.execute("INSERT OR REPLACE INTO speedtest_meta (key, value) VALUES ('ts_migrated', '1')")
    if updated:
        log.info("Normalized %d existing timestamps to UTC", updated)


def _offset_times_stored_in_utc(conn):
    return conn.execute("SELECT 1 FROM speedtest_meta WHERE key = 'ts_migrated'").fetchone() is not None


MIGRATIONS = (
    schema_baseline("speedtest-0001-baseline", _SCHEMA),
    add_columns("speedtest-0002-columns", [
        ("speedtest_results", declaration)
        for declaration in (
            "server_id INTEGER", "server_name TEXT", DEMO_FLAG,
            *(f"{name} {column_type}" for name, column_type in _ENRICHED_COLUMNS),
        )
    ]),
    Migration("speedtest-0003-utc-timestamps", _store_offset_times_in_utc, _offset_times_stored_in_utc),
)
