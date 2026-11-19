"""Weather storage schema migrations."""

from app.storage.migrations import DEMO_FLAG, add_columns, schema_baseline


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS weather_data ("
    "timestamp TEXT PRIMARY KEY, temperature REAL NOT NULL, is_demo INTEGER DEFAULT 0)",
)


MIGRATIONS = (
    schema_baseline("weather-0001-baseline", _SCHEMA),
    add_columns("weather-0002-demo-flag", [("weather_data", DEMO_FLAG)]),
)
