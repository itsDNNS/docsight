"""Weather storage schema migrations."""

from app.storage.migrations import DEMO_FLAG, add_columns, schema_baseline
from app.storage.schema import CORE_SCHEMA


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS weather_data ("
    "timestamp TEXT PRIMARY KEY, temperature REAL NOT NULL, is_demo INTEGER DEFAULT 0)",
)


MIGRATIONS = (
    schema_baseline("weather-0001-baseline", _SCHEMA),
    add_columns("weather-0002-demo-flag", [("weather_data", DEMO_FLAG)]),
    # The weather backfill state lives in _docsight_meta.
    schema_baseline("weather-0003-meta", CORE_SCHEMA[:1]),
)
