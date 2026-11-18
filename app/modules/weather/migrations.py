"""Weather storage schema migrations."""

from app.storage.migrations import Migration, add_column_if_missing, schema_baseline, table_columns


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS weather_data ("
    "timestamp TEXT PRIMARY KEY, temperature REAL NOT NULL, is_demo INTEGER DEFAULT 0)",
)


def _demo_applied(conn):
    columns = table_columns(conn, "weather_data")
    return not columns or "is_demo" in columns


def _apply_demo(conn):
    add_column_if_missing(
        conn, "weather_data", "is_demo", "is_demo INTEGER NOT NULL DEFAULT 0"
    )


MIGRATIONS = (
    schema_baseline("weather-0001-baseline", _SCHEMA),
    Migration("weather-0002-demo-flag", _apply_demo, _demo_applied),
)
