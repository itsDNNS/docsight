"""SQLite snapshot storage for DOCSIS timeline."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf", "text/plain",
}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_INCIDENT = 10

log = logging.getLogger("docsis.storage")


class SnapshotStorage:
    """Persist DOCSIS analysis snapshots to SQLite."""

    def __init__(self, db_path, max_days=7):
        self.db_path = db_path
        self.max_days = max_days
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    ds_channels_json TEXT NOT NULL,
                    us_channels_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_ts
                ON snapshots(timestamp)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bqm_graphs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    image_blob BLOB NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speedtest_results (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    download_mbps REAL,
                    upload_mbps REAL,
                    download_human TEXT,
                    upload_human TEXT,
                    ping_ms REAL,
                    jitter_ms REAL,
                    packet_loss_pct REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    data BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    acknowledged INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_ts
                ON events(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_ack
                ON events(acknowledged)
            """)

    def save_snapshot(self, analysis):
        """Save current analysis as a snapshot. Runs cleanup afterwards."""
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
                    (
                        ts,
                        json.dumps(analysis["summary"]),
                        json.dumps(analysis["ds_channels"]),
                        json.dumps(analysis["us_channels"]),
                    ),
                )
            log.debug("Snapshot saved: %s", ts)
        except Exception as e:
            log.error("Failed to save snapshot: %s", e)
            return
        self._cleanup()

    def get_snapshot_list(self):
        """Return list of available snapshot timestamps (newest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_snapshot(self, timestamp):
        """Load a single snapshot by timestamp. Returns analysis dict or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT summary_json, ds_channels_json, us_channels_json FROM snapshots WHERE timestamp = ?",
                (timestamp,),
            ).fetchone()
        if not row:
            return None
        return {
            "summary": json.loads(row[0]),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
        }

    def get_dates_with_data(self):
        """Return list of dates (YYYY-MM-DD) that have at least one snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT substr(timestamp, 1, 10) as day FROM snapshots ORDER BY day"
            ).fetchall()
        return [r[0] for r in rows]

    def get_daily_snapshot(self, date, target_time="06:00"):
        """Get the snapshot closest to target_time on the given date."""
        target_ts = f"{date}T{target_time}:00"
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT timestamp, summary_json, ds_channels_json, us_channels_json
                   FROM snapshots
                   WHERE timestamp LIKE ?
                   ORDER BY ABS(julianday(timestamp) - julianday(?))
                   LIMIT 1""",
                (f"{date}%", target_ts),
            ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "summary": json.loads(row[1]),
            "ds_channels": json.loads(row[2]),
            "us_channels": json.loads(row[3]),
        }

    def get_trend_data(self, start_date, end_date, target_time="06:00"):
        """Get summary data points for a date range, one per day (closest to target_time).
        Returns list of {date, timestamp, ...summary_fields}."""
        dates = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT substr(timestamp, 1, 10) as day FROM snapshots WHERE day >= ? AND day <= ? ORDER BY day",
                (start_date, end_date),
            ).fetchall()
            dates = [r[0] for r in rows]

        results = []
        for date in dates:
            snap = self.get_daily_snapshot(date, target_time)
            if snap:
                entry = {"date": date, "timestamp": snap["timestamp"]}
                entry.update(snap["summary"])
                results.append(entry)
        return results

    def get_range_data(self, start_ts, end_ts):
        """Get all snapshots between two ISO timestamps (inclusive)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json, ds_channels_json, us_channels_json "
                "FROM snapshots WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        results = []
        for row in rows:
            entry = {
                "timestamp": row[0],
                "summary": json.loads(row[1]),
                "ds_channels": json.loads(row[2]),
                "us_channels": json.loads(row[3]),
            }
            results.append(entry)
        return results

    def get_intraday_data(self, date):
        """Get all snapshots for a single day (for day-detail trends)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots WHERE timestamp LIKE ? ORDER BY timestamp",
                (f"{date}%",),
            ).fetchall()
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(json.loads(row[1]))
            results.append(entry)
        return results

    def save_bqm_graph(self, image_data):
        """Save BQM graph for today. Skips if already exists (UNIQUE date)."""
        today = datetime.now().strftime("%Y-%m-%d")
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                    (today, ts, image_data),
                )
            log.debug("BQM graph saved for %s", today)
        except Exception as e:
            log.error("Failed to save BQM graph: %s", e)

    def get_bqm_dates(self):
        """Return list of dates with BQM graphs (newest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date FROM bqm_graphs ORDER BY date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_bqm_graph(self, date):
        """Return BQM graph PNG bytes for a date, or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT image_blob FROM bqm_graphs WHERE date = ?", (date,)
            ).fetchone()
        return bytes(row[0]) if row else None

    # ── Speedtest result caching ──

    def save_speedtest_results(self, results):
        """Bulk insert speedtest results, ignoring duplicates by id."""
        if not results:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO speedtest_results "
                    "(id, timestamp, download_mbps, upload_mbps, download_human, "
                    "upload_human, ping_ms, jitter_ms, packet_loss_pct) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            r["id"], r["timestamp"], r["download_mbps"],
                            r["upload_mbps"], r["download_human"], r["upload_human"],
                            r["ping_ms"], r["jitter_ms"], r["packet_loss_pct"],
                        )
                        for r in results
                    ],
                )
            log.debug("Saved %d speedtest results", len(results))
        except Exception as e:
            log.error("Failed to save speedtest results: %s", e)

    def get_speedtest_results(self, limit=2000):
        """Return cached speedtest results, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct "
                "FROM speedtest_results ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_speedtest_count(self):
        """Return number of cached speedtest results."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM speedtest_results").fetchone()
        return row[0] if row else 0

    def get_latest_speedtest_id(self):
        """Return the highest speedtest result id, or 0 if none."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(id) FROM speedtest_results"
            ).fetchone()
        return row[0] or 0 if row else 0

    # ── Incident Journal ──

    def _connect(self):
        """Return a connection with foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def save_incident(self, date, title, description):
        """Create a new incident. Returns the new incident id."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO incidents (date, title, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (date, title, description, now, now),
            )
            return cur.lastrowid

    def update_incident(self, incident_id, date, title, description):
        """Update an existing incident. Returns True if found."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE incidents SET date=?, title=?, description=?, updated_at=? WHERE id=?",
                (date, title, description, now, incident_id),
            ).rowcount
        return rowcount > 0

    def delete_incident(self, incident_id):
        """Delete an incident (CASCADE deletes attachments). Returns True if found."""
        with self._connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM incidents WHERE id=?", (incident_id,)
            ).rowcount
        return rowcount > 0

    def get_incidents(self, limit=100, offset=0):
        """Return list of incidents (newest first) with attachment_count."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT i.id, i.date, i.title, i.description, i.created_at, i.updated_at, "
                "(SELECT COUNT(*) FROM incident_attachments WHERE incident_id = i.id) AS attachment_count "
                "FROM incidents i ORDER BY i.date DESC, i.created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_incident(self, incident_id):
        """Return single incident with attachment metadata (no blob data)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, date, title, description, created_at, updated_at FROM incidents WHERE id=?",
                (incident_id,),
            ).fetchone()
            if not row:
                return None
            incident = dict(row)
            attachments = conn.execute(
                "SELECT id, filename, mime_type, created_at FROM incident_attachments WHERE incident_id=? ORDER BY id",
                (incident_id,),
            ).fetchall()
            incident["attachments"] = [dict(a) for a in attachments]
        return incident

    def save_attachment(self, incident_id, filename, mime_type, data):
        """Save a file attachment for an incident. Returns attachment id."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO incident_attachments (incident_id, filename, mime_type, data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (incident_id, filename, mime_type, data, now),
            )
            return cur.lastrowid

    def get_attachment(self, attachment_id):
        """Return attachment dict with data bytes, or None."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, incident_id, filename, mime_type, data, created_at "
                "FROM incident_attachments WHERE id=?",
                (attachment_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["data"] = bytes(result["data"])
        return result

    def delete_attachment(self, attachment_id):
        """Delete a single attachment. Returns True if found."""
        with self._connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM incident_attachments WHERE id=?", (attachment_id,)
            ).rowcount
        return rowcount > 0

    def get_attachment_count(self, incident_id):
        """Return number of attachments for an incident."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM incident_attachments WHERE incident_id=?",
                (incident_id,),
            ).fetchone()
        return row[0] if row else 0

    # ── Events ──

    def save_event(self, timestamp, severity, event_type, message, details=None):
        """Save a single event. Returns the new event id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, severity, event_type, message, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (timestamp, severity, event_type, message,
                 json.dumps(details) if details else None),
            )
            return cur.lastrowid

    def save_events(self, events_list):
        """Bulk insert events. Returns count of inserted rows."""
        if not events_list:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO events (timestamp, severity, event_type, message, details) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (e["timestamp"], e["severity"], e["event_type"], e["message"],
                     json.dumps(e.get("details")) if e.get("details") else None)
                    for e in events_list
                ],
            )
        return len(events_list)

    def get_events(self, limit=200, offset=0, severity=None, event_type=None, acknowledged=None):
        """Return list of event dicts, newest first, with optional filters."""
        query = "SELECT id, timestamp, severity, event_type, message, details, acknowledged FROM events"
        conditions = []
        params = []
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if acknowledged is not None:
            conditions.append("acknowledged = ?")
            params.append(int(acknowledged))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            event = dict(r)
            if event["details"]:
                try:
                    event["details"] = json.loads(event["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(event)
        return results

    def get_event_count(self, acknowledged=None):
        """Return event count, optionally filtered by acknowledged status."""
        if acknowledged is not None:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE acknowledged = ?",
                    (int(acknowledged),),
                ).fetchone()
        else:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0

    def acknowledge_event(self, event_id):
        """Acknowledge a single event. Returns True if found."""
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE id = ?", (event_id,)
            ).rowcount
        return rowcount > 0

    def acknowledge_all_events(self):
        """Acknowledge all unacknowledged events. Returns rows affected."""
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE acknowledged = 0"
            ).rowcount
        return rowcount

    def delete_old_events(self, days):
        """Delete events older than given days. Returns count deleted."""
        if days <= 0:
            return 0
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM events WHERE timestamp < ?", (cutoff,)
            ).rowcount
        return deleted

    def _cleanup(self):
        """Delete snapshots, BQM graphs, and events older than max_days. 0 = keep all."""
        if self.max_days <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=self.max_days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM snapshots WHERE timestamp < ?", (cutoff,)
            ).rowcount
        if deleted:
            log.info("Cleaned up %d old snapshots (before %s)", deleted, cutoff)
        cutoff_date = (datetime.now() - timedelta(days=self.max_days)).strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            bqm_deleted = conn.execute(
                "DELETE FROM bqm_graphs WHERE date < ?", (cutoff_date,)
            ).rowcount
        if bqm_deleted:
            log.info("Cleaned up %d old BQM graphs (before %s)", bqm_deleted, cutoff_date)
        events_deleted = self.delete_old_events(self.max_days)
        if events_deleted:
            log.info("Cleaned up %d old events (before %s)", events_deleted, cutoff)
