"""Standalone BNetzA measurement storage."""

import json
import logging
import sqlite3

from app.tz import utc_now

log = logging.getLogger("docsis.storage.bnetz")


class BnetzStorage:
    """Standalone BNetzA data storage (not a mixin).

    Creates the bnetz_measurements table if it doesn't exist.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """Create the bnetz_measurements table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bnetz_measurements ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  date TEXT NOT NULL,"
                "  timestamp TEXT NOT NULL,"
                "  provider TEXT,"
                "  tariff TEXT,"
                "  download_max_tariff REAL,"
                "  download_normal_tariff REAL,"
                "  download_min_tariff REAL,"
                "  upload_max_tariff REAL,"
                "  upload_normal_tariff REAL,"
                "  upload_min_tariff REAL,"
                "  download_measured_avg REAL,"
                "  upload_measured_avg REAL,"
                "  measurement_count INTEGER,"
                "  verdict_download TEXT,"
                "  verdict_upload TEXT,"
                "  measurements_json TEXT,"
                "  pdf_blob BLOB,"
                "  source TEXT DEFAULT 'upload',"
                "  is_demo INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            # Migration: add source/is_demo columns if missing
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(bnetz_measurements)").fetchall()]
                if "source" not in cols:
                    conn.execute("ALTER TABLE bnetz_measurements ADD COLUMN source TEXT DEFAULT 'upload'")
                if "is_demo" not in cols:
                    conn.execute("ALTER TABLE bnetz_measurements ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

    def save_bnetz_measurement(self, parsed_data, pdf_bytes=None, source="upload"):
        """Save a parsed BNetzA measurement with optional PDF. Returns the new id."""
        now = utc_now()
        measurements = {
            "download": parsed_data.get("measurements_download", []),
            "upload": parsed_data.get("measurements_upload", []),
        }
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO bnetz_measurements "
                "(date, timestamp, provider, tariff, "
                "download_max_tariff, download_normal_tariff, download_min_tariff, "
                "upload_max_tariff, upload_normal_tariff, upload_min_tariff, "
                "download_measured_avg, upload_measured_avg, measurement_count, "
                "verdict_download, verdict_upload, measurements_json, pdf_blob, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    parsed_data.get("date", now[:10]),
                    now,
                    parsed_data.get("provider"),
                    parsed_data.get("tariff"),
                    parsed_data.get("download_max"),
                    parsed_data.get("download_normal"),
                    parsed_data.get("download_min"),
                    parsed_data.get("upload_max"),
                    parsed_data.get("upload_normal"),
                    parsed_data.get("upload_min"),
                    parsed_data.get("download_measured_avg"),
                    parsed_data.get("upload_measured_avg"),
                    parsed_data.get("measurement_count"),
                    parsed_data.get("verdict_download"),
                    parsed_data.get("verdict_upload"),
                    json.dumps(measurements),
                    pdf_bytes,
                    source,
                ),
            )
            return cur.lastrowid

    def get_bnetz_measurements(self, limit=50):
        """Return list of BNetzA measurements (without PDF blob), newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, date, timestamp, provider, tariff, "
                "download_max_tariff, download_normal_tariff, download_min_tariff, "
                "upload_max_tariff, upload_normal_tariff, upload_min_tariff, "
                "download_measured_avg, upload_measured_avg, measurement_count, "
                "verdict_download, verdict_upload, measurements_json, source "
                "FROM bnetz_measurements ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            raw = d.pop("measurements_json", None)
            if raw:
                try:
                    d["measurements"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d["measurements"] = None
            else:
                d["measurements"] = None
            results.append(d)
        return results

    def get_bnetz_pdf(self, measurement_id):
        """Return the original PDF bytes for a BNetzA measurement, or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT pdf_blob FROM bnetz_measurements WHERE id = ?",
                (measurement_id,),
            ).fetchone()
        return bytes(row[0]) if row and row[0] else None

    def delete_bnetz_measurement(self, measurement_id):
        """Delete a BNetzA measurement. Returns True if found."""
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                "DELETE FROM bnetz_measurements WHERE id = ?",
                (measurement_id,),
            ).rowcount
        return rowcount > 0

    def get_bnetz_in_range(self, start_ts, end_ts):
        """Return BNetzA measurements within a time range, oldest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, date, timestamp, provider, tariff, "
                "download_max_tariff, download_measured_avg, "
                "upload_max_tariff, upload_measured_avg, "
                "verdict_download, verdict_upload "
                "FROM bnetz_measurements "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_bnetz(self):
        """Return the most recent BNetzA measurement (without blob), or None."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, date, timestamp, provider, tariff, "
                "download_max_tariff, download_normal_tariff, download_min_tariff, "
                "upload_max_tariff, upload_normal_tariff, upload_min_tariff, "
                "download_measured_avg, upload_measured_avg, measurement_count, "
                "verdict_download, verdict_upload "
                "FROM bnetz_measurements ORDER BY date DESC LIMIT 1",
            ).fetchone()
        return dict(row) if row else None
