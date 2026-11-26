"""BNetz storage schema migrations."""

from app.storage.migrations import DEMO_FLAG, Migration, add_columns, schema_baseline, table_columns


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


def _demo_speeds_under_mbps(conn):
    # Older demo campaigns stored each speed as "value"; the parsers and the table use "mbps".
    if "measurements_json" not in table_columns(conn, "bnetz_measurements"):
        return
    conn.execute(
        "UPDATE bnetz_measurements SET measurements_json = replace(measurements_json, '\"value\": ', '\"mbps\": ') "
        "WHERE is_demo = 1"
    )


MIGRATIONS = (
    schema_baseline("bnetz-0001-baseline", _SCHEMA),
    add_columns("bnetz-0002-columns", [
        ("bnetz_measurements", "source TEXT DEFAULT 'upload'"), ("bnetz_measurements", DEMO_FLAG),
    ]),
    Migration("bnetz-0003-demo-speeds-mbps", _demo_speeds_under_mbps, lambda _conn: False),
)
