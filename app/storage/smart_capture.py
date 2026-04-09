"""Smart Capture execution storage mixin."""

import json
import sqlite3

from ..tz import utc_now


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
                         completed_at=None, linked_result_id=None,
                         last_error=None, attempt_count=None):
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
        if last_error is not None:
            updates.append("last_error = ?")
            params.append(last_error)
        if attempt_count is not None:
            updates.append("attempt_count = ?")
            params.append(attempt_count)
        if not updates:
            return
        params.append(execution_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE smart_capture_executions SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def get_fired_unmatched(self, action_type):
        """Return FIRED executions without a linked result, filtered by action_type.
        Ordered by fired_at ASC (oldest first) for FIFO matching."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM smart_capture_executions "
                "WHERE status = 'fired' AND linked_result_id IS NULL "
                "AND action_type = ? ORDER BY fired_at ASC",
                (action_type,),
            ).fetchall()
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

    def expire_stale_fired(self, cutoff_timestamp, action_type=None):
        """Bulk-expire FIRED executions with fired_at before cutoff and no linked result.
        Optionally filtered by action_type. Returns count of expired rows."""
        query = (
            "UPDATE smart_capture_executions "
            "SET status = 'expired', "
            "last_error = 'no matching result within timeout window' "
            "WHERE status = 'fired' AND fired_at < ? AND linked_result_id IS NULL"
        )
        params = [cutoff_timestamp]
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(query, params).rowcount
        return rowcount

    def claim_execution(self, execution_id, expected_status, new_status,
                        completed_at=None, linked_result_id=None):
        """Conditionally update execution only if current status matches expected_status.
        Returns True if the row was updated, False if status had already changed.
        Prevents race between expiry (main loop) and matching (collector thread)."""
        updates = ["status = ?"]
        params = [new_status.value if hasattr(new_status, 'value') else str(new_status)]
        if completed_at is not None:
            updates.append("completed_at = ?")
            params.append(completed_at)
        if linked_result_id is not None:
            updates.append("linked_result_id = ?")
            params.append(linked_result_id)
        params.extend([execution_id, expected_status])
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                f"UPDATE smart_capture_executions SET {', '.join(updates)} "
                "WHERE id = ? AND status = ?",
                params,
            ).rowcount
        return rowcount > 0

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

    def expire_stale_pending(self, cutoff_timestamp):
        """Bulk-expire PENDING executions with created_at before cutoff.
        Handles orphaned executions when no adapter is registered."""
        with sqlite3.connect(self.db_path) as conn:
            rowcount = conn.execute(
                "UPDATE smart_capture_executions "
                "SET status = 'expired', "
                "last_error = 'no action adapter configured' "
                "WHERE status = 'pending' AND created_at < ?",
                (cutoff_timestamp,),
            ).rowcount
        return rowcount

