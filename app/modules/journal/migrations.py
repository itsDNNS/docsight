"""Journal storage schema migrations."""

from app.storage.migrations import (
    Migration,
    add_column_if_missing,
    schema_baseline,
    table_columns,
    table_exists,
)


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


def _demo_applied(conn):
    return all(
        not table_exists(conn, table) or "is_demo" in table_columns(conn, table)
        for table in ("journal_entries", "incidents")
    )


def _apply_demo(conn):
    for table in ("journal_entries", "incidents"):
        add_column_if_missing(conn, table, "is_demo", "is_demo INTEGER NOT NULL DEFAULT 0")


MIGRATIONS = (
    schema_baseline("journal-0001-baseline", _SCHEMA),
    Migration("journal-0002-demo-flags", _apply_demo, _demo_applied),
)
