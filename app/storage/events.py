"""Event log mixin."""

from __future__ import annotations

import json
import sqlite3

from ..types import EventDict
from ..tz import utc_cutoff


class EventMixin:

    def save_event(self, timestamp: str, severity: str, event_type: str, message: str, details: dict | None = None) -> int:
        """Save a single event. Returns the new event id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, severity, event_type, message, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (timestamp, severity, event_type, message,
                 json.dumps(details) if details else None),
            )
            return cur.lastrowid

    def save_events(self, events_list: list[EventDict], is_demo: bool = False) -> int:
        """Bulk insert events. Returns count of inserted rows."""
        if not events_list:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO events (timestamp, severity, event_type, message, details, is_demo) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (e["timestamp"], e["severity"], e["event_type"], e["message"],
                     json.dumps(e.get("details")) if e.get("details") else None,
                     int(is_demo))
                    for e in events_list
                ],
            )
        return len(events_list)

    def save_events_with_ids(self, events_list: list[EventDict], is_demo: bool = False) -> list[int]:
        """Insert events individually and return list of row IDs.

        Unlike save_events() (bulk executemany, returns count), this method
        inserts one-by-one within a single transaction so each row ID is
        captured. Each event dict is annotated with '_id' in-place.

        Used by Smart Capture to correlate executions to source events.
        """
        if not events_list:
            return []
        ids = []
        with sqlite3.connect(self.db_path) as conn:
            for e in events_list:
                cur = conn.execute(
                    "INSERT INTO events (timestamp, severity, event_type, message, details, is_demo) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (e["timestamp"], e["severity"], e["event_type"], e["message"],
                     json.dumps(e.get("details")) if e.get("details") else None,
                     int(is_demo)),
                )
                row_id = cur.lastrowid
                ids.append(row_id)
                e["_id"] = row_id
        return ids

    def get_events(self, limit: int = 200, offset: int = 0, severity: str | None = None, event_type: str | None = None, acknowledged: bool | None = None) -> list[dict]:
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

    def get_recent_events(self, hours: int = 48) -> list[dict]:
        """Return events from the last N hours, newest first."""
        cutoff = utc_cutoff(hours=hours)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, severity, event_type, message, details, acknowledged "
                "FROM events WHERE timestamp >= ? ORDER BY timestamp DESC",
                (cutoff,),
            ).fetchall()
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

    def delete_old_events(self, days):
        """Delete events older than given days. Returns count deleted."""
        if days <= 0:
            return 0
        cutoff = utc_cutoff(days=days)
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM events WHERE timestamp < ?", (cutoff,)
            ).rowcount
        return deleted

    def get_latest_spike_timestamp(self):
        """Return timestamp of the most recent error_spike event, or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT timestamp FROM events WHERE event_type = 'error_spike' "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None
