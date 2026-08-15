"""Declarative SQLite schema statements; execution belongs to migrations."""

CORE_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS _docsight_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        ds_channels_json TEXT NOT NULL,
        us_channels_json TEXT NOT NULL,
        raw_json TEXT,
        analysis_meta_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        uptime_seconds INTEGER,
        sw_version TEXT,
        wan_ipv4 TEXT,
        wan_ipv6 TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp)",
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        severity TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT NOT NULL,
        details TEXT,
        acknowledged INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_ack ON events(acknowledged)",
    "CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_ts_id ON snapshots(timestamp DESC, id DESC)",
    """
    CREATE TABLE IF NOT EXISTS weather_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL UNIQUE,
        temperature REAL NOT NULL,
        is_demo INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_weather_ts ON weather_data(timestamp)",
    """
    CREATE TABLE IF NOT EXISTS api_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        token_prefix TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pwa_push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT NOT NULL UNIQUE,
        subscription_json TEXT NOT NULL,
        user_agent TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pwa_push_subscriptions_updated
    ON pwa_push_subscriptions(updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS smart_capture_executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger_event_id INTEGER,
        trigger_timestamp TEXT,
        trigger_type TEXT NOT NULL,
        action_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        fired_at TEXT,
        completed_at TEXT,
        claimed_at TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        suppression_reason TEXT,
        linked_result_id INTEGER,
        details TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sc_exec_status ON smart_capture_executions(status)",
    "CREATE INDEX IF NOT EXISTS idx_sc_exec_created ON smart_capture_executions(created_at)",
)


SEGMENT_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS segment_utilization (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        ds_total REAL,
        us_total REAL,
        ds_own REAL,
        us_own REAL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_segment_util_ts
    ON segment_utilization(timestamp)
    """,
    """
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
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_segment_util_events_key
    ON segment_utilization_events(direction, start_ts, threshold, min_minutes)
    """,
)
