"""Journal storage schema migrations."""

from app.storage.migrations import DEMO_FLAG, add_columns, schema_baseline


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS journal_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, title TEXT NOT NULL,
        description TEXT, icon TEXT, incident_id INTEGER, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS journal_attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL,
        filename TEXT NOT NULL, mime_type TEXT NOT NULL, data BLOB NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
        status TEXT NOT NULL DEFAULT 'open', start_date TEXT, end_date TEXT, icon TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        is_demo INTEGER NOT NULL DEFAULT 0
    )
    """,
)


MIGRATIONS = (
    schema_baseline("journal-0001-baseline", _SCHEMA),
    add_columns("journal-0002-demo-flags", [("journal_entries", DEMO_FLAG), ("incidents", DEMO_FLAG)]),
)
