"""Smart Capture execution storage mixin."""

import json
import sqlite3

from ..tz import utc_now, utc_cutoff


class SmartCaptureMixin:

    def save_execution(self, trigger_type, action_type, status,
                       trigger_event_id=None, trigger_timestamp=None,
                       fired_at=None, suppression_reason=None, details=None):
        """Save a Smart Capture execution record. Returns the new row id.

        Note: trigger_event_id may be None when the event has not yet been
        assigned a DB id at evaluation time. trigger_timestamp is stored
        as a secondary correlation key.
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO smart_capture_executions "
                "(trigger_event_id, trigger_timestamp, trigger_type, action_type, status, "
                "fired_at, suppression_reason, details, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trigger_event_id, trigger_timestamp, trigger_type, action_type,
                 status.value, fired_at, suppression_reason,
                 json.dumps(details) if details else None,
                 utc_now()),
            )
            return cur.lastrowid

    def get_execution(self, execution_id):
        """Return a single execution record by id, or None."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM smart_capture_executions WHERE id = ?",
                (execution_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        if result["details"]:
            try:
                result["details"] = json.loads(result["details"])
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    def update_execution(self, execution_id, status=None, fired_at=None,
                         completed_at=None, linked_result_id=None):
        """Update fields on an existing execution record."""
        updates = []
        params = []
        if status is not None:
            updates.append("status = ?")
            params.append(status.value if hasattr(status, 'value') else str(status))
        if fired_at is not None:
            updates.append("fired_at = ?")
            params.append(fired_at)
        if completed_at is not None:
            updates.append("completed_at = ?")
            params.append(completed_at)
        if linked_result_id is not None:
            updates.append("linked_result_id = ?")
            params.append(linked_result_id)
        if not updates:
            return
        params.append(execution_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE smart_capture_executions SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def get_executions(self, limit=50, offset=0, status=None):
        """Return execution records, newest first."""
        query = "SELECT * FROM smart_capture_executions"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            record = dict(r)
            if record["details"]:
                try:
                    record["details"] = json.loads(record["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(record)
        return results

    def count_executions_since(self, since_timestamp, status=None):
        """Count executions created after the given timestamp."""
        query = "SELECT COUNT(*) FROM smart_capture_executions WHERE created_at >= ?"
        params = [since_timestamp]
        if status:
            query += " AND status = ?"
            params.append(status)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(query, params).fetchone()
        return row[0] if row else 0

    def delete_old_executions(self, days):
        """Delete executions older than given days. Returns count deleted."""
        if days <= 0:
            return 0
        cutoff = utc_cutoff(days=days)
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM smart_capture_executions WHERE created_at < ?", (cutoff,)
            ).rowcount
        return deleted
