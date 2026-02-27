"""Event log mixin."""

import json
import sqlite3

from ..tz import utc_now, utc_cutoff


class EventMixin:

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

    def save_events(self, events_list, is_demo=False):
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

    def get_recent_events(self, hours=48):
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
