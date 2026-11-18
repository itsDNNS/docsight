"""BNetz storage schema migrations."""

from app.storage.migrations import Migration, add_column_if_missing, schema_baseline, table_columns, table_exists


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS bnetz_measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
        timestamp TEXT NOT NULL, provider TEXT, tariff TEXT,
        download_max_tariff REAL, download_normal_tariff REAL,
        download_min_tariff REAL, upload_max_tariff REAL,
        upload_normal_tariff REAL, upload_min_tariff REAL,
        download_measured_avg REAL, upload_measured_avg REAL,
        measurement_count INTEGER, verdict_download TEXT, verdict_upload TEXT,
        measurements_json TEXT, pdf_blob BLOB, source TEXT DEFAULT 'upload',
        is_demo INTEGER NOT NULL DEFAULT 0
    )
    """,
)


def _columns_applied(conn):
    columns = table_columns(conn, "bnetz_measurements")
    return not columns or {"source", "is_demo"} <= columns


def _apply_columns(conn):
    add_column_if_missing(
        conn, "bnetz_measurements", "source", "source TEXT DEFAULT 'upload'"
    )
    add_column_if_missing(
        conn, "bnetz_measurements", "is_demo", "is_demo INTEGER NOT NULL DEFAULT 0"
    )


MIGRATIONS = (
    schema_baseline("bnetz-0001-baseline", _SCHEMA),
    Migration("bnetz-0002-columns", _apply_columns, _columns_applied),
)
