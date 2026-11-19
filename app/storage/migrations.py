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


# SQLite matches table and column names case-insensitively, so these probes do too.
def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? COLLATE NOCASE", (table,)
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the lowercased column names of ``table``, empty if it is missing."""
    if not table_exists(conn, table):
        return set()
    quoted = table.replace('"', '""')
    return {row[1].lower() for row in conn.execute(f'PRAGMA table_info("{quoted}")')}


def add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, declaration: str
) -> bool:
    columns = table_columns(conn, table)
    if not columns or column in columns:
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


def schema_baseline(migration_id: str, statements: Sequence[str]) -> Migration:
    """Replay idempotent schema declarations once when adopting the registry.

    A table-only shape probe would stamp historical databases that have all
    tables but are missing one of the required indexes.
    """
    return Migration(migration_id, lambda conn: execute_schema(conn, statements), lambda _conn: False)


DEMO_FLAG = "is_demo INTEGER NOT NULL DEFAULT 0"


def add_columns(migration_id: str, columns: Sequence[tuple[str, str]]) -> Migration:
    """Add each (table, column declaration) to existing tables that lack the column."""
    def apply(conn: sqlite3.Connection) -> None:
        for table, declaration in columns:
            add_column_if_missing(conn, table, declaration.split()[0], declaration)

    # Adding only missing columns makes the step its own shape check.
    return Migration(migration_id, apply, lambda _conn: False)


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


def _apply_smart_capture_error_scrub(conn: sqlite3.Connection) -> None:
    # Older Speedtest captures stored the tracker's response body and exception
    # texts, which can contain credentials. Keep only the fixed status part.
    conn.execute(
        "UPDATE smart_capture_executions SET last_error = substr(last_error, 1, 16) "
        "WHERE action_type = 'capture' AND last_error GLOB 'STT returned [0-9][0-9][0-9]: *'"
    )
    conn.execute(
        "UPDATE smart_capture_executions SET last_error = 'Unexpected error, see the DOCSight log' "
        "WHERE action_type = 'capture' AND status = 'expired' "
        "AND NOT (last_error GLOB 'STT returned [0-9][0-9][0-9]' "
        "OR last_error IN ('no matching result within timeout window', 'no action adapter configured'))"
    )


def _apply_unmeasured_summary_null(conn: sqlite3.Connection) -> None:
    # Older versions stored 0 as power and SNR summary when no channel of a
    # direction reported the value. Keep summaries backed by a channel value.
    for key, field, channels in (
        ("ds_power", "power", "ds_channels_json"),
        ("us_power", "power", "us_channels_json"),
        ("ds_snr", "snr", "ds_channels_json"),
    ):
        zero = " AND ".join(
            f"json_type(summary_json, '$.{key}_{part}') IN ('integer', 'real') "
            f"AND json_extract(summary_json, '$.{key}_{part}') = 0"
            for part in ("min", "max", "avg")
        )
        conn.execute(
            f"UPDATE snapshots SET summary_json = json_set(summary_json, "
            f"'$.{key}_min', NULL, '$.{key}_max', NULL, '$.{key}_avg', NULL) "
            f"WHERE json_valid(summary_json) AND {zero} "
            f"AND json_valid({channels}) AND json_type({channels}) = 'array' AND NOT EXISTS ("
            f"SELECT 1 FROM json_each({channels}) WHERE type != 'object' OR json_extract(value, '$.{field}') IS NOT NULL)"
        )


CORE_MIGRATIONS: tuple[Migration, ...] = (
    schema_baseline("core-0001-baseline", CORE_SCHEMA),
    Migration(
        "core-0002-incidents-to-journal",
        _apply_incidents_migration,
        _incidents_migration_applied,
    ),
    add_columns("core-0003-demo-flags", [
        (table, DEMO_FLAG)
        for table in (
            "snapshots", "events", "journal_entries", "incidents", "speedtest_results",
            "bqm_graphs", "bnetz_measurements", "weather_data",
        )
    ]),
    add_columns("core-0004-snapshot-columns", [
        ("snapshots", "analysis_meta_json TEXT"), ("snapshots", "raw_json TEXT"),
    ]),
    Migration("core-0005-meta-version", _apply_meta_version, _meta_version_applied),
    Migration("core-0006-smart-capture-error-scrub", _apply_smart_capture_error_scrub, lambda _conn: False),
    Migration("core-0007-unmeasured-summary-null", _apply_unmeasured_summary_null, lambda _conn: False),
)

SEGMENT_MIGRATIONS: tuple[Migration, ...] = (
    schema_baseline("segment-0001-baseline", SEGMENT_SCHEMA),
    add_columns("segment-0002-demo-flag", [("segment_utilization", DEMO_FLAG)]),
)
