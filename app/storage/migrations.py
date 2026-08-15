"""Ordered, idempotent, shape-aware SQLite migrations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import sqlite3

from .schema import CORE_SCHEMA, SEGMENT_SCHEMA
from .sqlite import open_read, write_transaction

log = logging.getLogger("docsis.storage.migrations")
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Migration:
    migration_id: str
    apply: Callable[[sqlite3.Connection], None]
    is_applied: Callable[[sqlite3.Connection], bool]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    quoted = table.replace('"', '""')
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{quoted}")')}


def add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, declaration: str
) -> bool:
    if not table_exists(conn, table) or column in table_columns(conn, table):
        return False
    quoted = table.replace('"', '""')
    conn.execute(f'ALTER TABLE "{quoted}" ADD COLUMN {declaration}')
    log.info("Migration: added %s column to %s", column, table)
    return True


def execute_schema(conn: sqlite3.Connection, statements: Sequence[str]) -> None:
    for statement in statements:
        conn.execute(statement)


def _registry_exists(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "_docsight_migrations")


def _ensure_registry(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _docsight_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def run_migrations(db_path: str, migrations: Sequence[Migration]) -> list[str]:
    """Apply or shape-stamp migrations in order, one transaction per step."""
    if not migrations:
        return []
    with open_read(db_path) as conn:
        if _registry_exists(conn):
            recorded = {
                row[0]
                for row in conn.execute("SELECT id FROM _docsight_migrations")
            }
            if all(migration.migration_id in recorded for migration in migrations):
                return []

    newly_recorded = []
    with write_transaction(db_path) as conn:
        _ensure_registry(conn)
    for migration in migrations:
        with write_transaction(db_path) as conn:
            if conn.execute(
                "SELECT 1 FROM _docsight_migrations WHERE id=?",
                (migration.migration_id,),
            ).fetchone():
                continue
            if not migration.is_applied(conn):
                migration.apply(conn)
            conn.execute(
                "INSERT INTO _docsight_migrations (id, applied_at) VALUES (?, ?)",
                (
                    migration.migration_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            newly_recorded.append(migration.migration_id)
    return newly_recorded


def _core_baseline_applied(_conn: sqlite3.Connection) -> bool:
    # Replay the idempotent declarations once when adopting the registry.  A
    # table-only shape probe would stamp historical databases that have all
    # tables but are missing one of the required indexes.
    return False


def _apply_core_baseline(conn: sqlite3.Connection) -> None:
    execute_schema(conn, CORE_SCHEMA)


_LEGACY_INCIDENT_COLUMNS = {
    "id", "date", "title", "description", "created_at", "updated_at",
}


def _incidents_migration_applied(conn: sqlite3.Connection) -> bool:
    incidents_columns = table_columns(conn, "incidents")
    journal_exists = table_exists(conn, "journal_entries")
    if "title" in incidents_columns and journal_exists:
        log.warning(
            "Hybrid journal schema detected; preserving incidents and journal_entries unchanged"
        )
        return True
    if "title" in incidents_columns and not _LEGACY_INCIDENT_COLUMNS <= incidents_columns:
        log.warning("Unknown incidents schema; preserving table unchanged")
        return True
    return "title" not in incidents_columns


def _apply_incidents_migration(conn: sqlite3.Connection) -> None:
    incidents_columns = table_columns(conn, "incidents")
    if _LEGACY_INCIDENT_COLUMNS <= incidents_columns:
        if table_exists(conn, "journal_entries"):
            log.warning(
                "Hybrid journal schema detected; preserving incidents and journal_entries unchanged"
            )
            return
        conn.execute("ALTER TABLE incidents RENAME TO journal_entries")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                data BLOB NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE
            )
            """
        )
        if table_exists(conn, "incident_attachments"):
            attachment_columns = table_columns(conn, "incident_attachments")
            expected = {"id", "incident_id", "filename", "mime_type", "data", "created_at"}
            if expected <= attachment_columns:
                orphan_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM incident_attachments AS attachment
                    LEFT JOIN journal_entries AS entry ON entry.id = attachment.incident_id
                    WHERE entry.id IS NULL
                    """
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO journal_attachments
                        (id, entry_id, filename, mime_type, data, created_at)
                    SELECT id, incident_id, filename, mime_type, data, created_at
                    FROM incident_attachments
                    WHERE incident_id IN (SELECT id FROM journal_entries)
                    """
                )
                if orphan_count:
                    log.warning(
                        "Preserving incident_attachments with %d orphaned row(s)",
                        orphan_count,
                    )
                else:
                    conn.execute("DROP TABLE incident_attachments")
            else:
                log.warning("Unknown incident_attachments shape; preserving table unchanged")
        add_column_if_missing(conn, "journal_entries", "incident_id", "incident_id INTEGER")
        add_column_if_missing(conn, "journal_entries", "icon", "icon TEXT")


_DEMO_TABLES = (
    "snapshots", "events", "journal_entries", "incidents", "speedtest_results",
    "bqm_graphs", "bnetz_measurements", "weather_data",
)


def _demo_flags_applied(conn: sqlite3.Connection) -> bool:
    return all(
        not table_exists(conn, table) or "is_demo" in table_columns(conn, table)
        for table in _DEMO_TABLES
    )


def _apply_demo_flags(conn: sqlite3.Connection) -> None:
    for table in _DEMO_TABLES:
        add_column_if_missing(
            conn, table, "is_demo", "is_demo INTEGER NOT NULL DEFAULT 0"
        )


def _snapshot_columns_applied(conn: sqlite3.Connection) -> bool:
    columns = table_columns(conn, "snapshots")
    return not columns or {"analysis_meta_json", "raw_json"} <= columns


def _apply_snapshot_columns(conn: sqlite3.Connection) -> None:
    add_column_if_missing(
        conn, "snapshots", "analysis_meta_json", "analysis_meta_json TEXT"
    )
    add_column_if_missing(conn, "snapshots", "raw_json", "raw_json TEXT")


def _meta_version_applied(conn: sqlite3.Connection) -> bool:
    if not table_exists(conn, "_docsight_meta"):
        return False
    row = conn.execute(
        "SELECT value FROM _docsight_meta WHERE key='schema_version'"
    ).fetchone()
    return row is not None and row[0] == str(SCHEMA_VERSION)


def _apply_meta_version(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO _docsight_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )


def _segment_applied(_conn: sqlite3.Connection) -> bool:
    # CREATE IF NOT EXISTS also repairs missing indexes on legacy databases.
    return False


CORE_MIGRATIONS: tuple[Migration, ...] = (
    Migration("core-0001-baseline", _apply_core_baseline, _core_baseline_applied),
    Migration(
        "core-0002-incidents-to-journal",
        _apply_incidents_migration,
        _incidents_migration_applied,
    ),
    Migration("core-0003-demo-flags", _apply_demo_flags, _demo_flags_applied),
    Migration(
        "core-0004-snapshot-columns",
        _apply_snapshot_columns,
        _snapshot_columns_applied,
    ),
    Migration("core-0005-meta-version", _apply_meta_version, _meta_version_applied),
)

SEGMENT_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "segment-0001-baseline",
        lambda conn: execute_schema(conn, SEGMENT_SCHEMA),
        _segment_applied,
    ),
)
