"""Weather storage schema migrations."""

from app.storage.migrations import Migration, add_column_if_missing, table_columns, table_exists


def _apply_baseline(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_data ("
        "timestamp TEXT PRIMARY KEY, temperature REAL NOT NULL, is_demo INTEGER DEFAULT 0)"
    )


def _baseline_applied(_conn):
    # Replay idempotent schema declarations once to repair missing indexes.
    return False


def _demo_applied(conn):
    columns = table_columns(conn, "weather_data")
    return not columns or "is_demo" in columns


def _apply_demo(conn):
    add_column_if_missing(
        conn, "weather_data", "is_demo", "is_demo INTEGER NOT NULL DEFAULT 0"
    )


MIGRATIONS = (
    Migration("weather-0001-baseline", _apply_baseline, _baseline_applied),
    Migration("weather-0002-demo-flag", _apply_demo, _demo_applied),
)
