"""BNetz storage schema migrations."""

from app.storage.migrations import DEMO_FLAG, add_columns, schema_baseline


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


MIGRATIONS = (
    schema_baseline("bnetz-0001-baseline", _SCHEMA),
    add_columns("bnetz-0002-columns", [
        ("bnetz_measurements", "source TEXT DEFAULT 'upload'"), ("bnetz_measurements", DEMO_FLAG),
    ]),
)
