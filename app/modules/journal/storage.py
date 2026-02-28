"""Standalone journal entries, attachments, and incidents storage."""

import logging
import sqlite3

from app.tz import utc_now

log = logging.getLogger("docsis.storage.journal")


class JournalStorage:
    """Standalone journal data storage (not a mixin).

    Creates the journal_entries, journal_attachments, and incidents tables
    if they don't exist.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """Create the journal tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    icon TEXT,
                    incident_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_demo INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    data BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    start_date TEXT,
                    end_date TEXT,
                    icon TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_demo INTEGER NOT NULL DEFAULT 0
                )
            """)
            # Migration: add is_demo column if missing
            for tbl in ("journal_entries", "incidents"):
                try:
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                    if "is_demo" not in cols:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
                except Exception:
                    pass

    def _connect(self):
        """Return a connection with foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ── Journal Entries ──

    def save_entry(self, date, title, description, icon=None, incident_id=None, is_demo=False):
        """Create a new journal entry. Returns the new entry id."""
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO journal_entries (date, title, description, icon, incident_id, created_at, updated_at, is_demo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (date, title, description, icon, incident_id, now, now, int(is_demo)),
            )
            return cur.lastrowid

    def update_entry(self, entry_id, date, title, description, icon=None, incident_id=None):
        """Update an existing journal entry. Returns True if found."""
        now = utc_now()
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET date=?, title=?, description=?, icon=?, incident_id=?, updated_at=? WHERE id=?",
                (date, title, description, icon, incident_id, now, entry_id),
            ).rowcount
        return rowcount > 0

    def delete_entry(self, entry_id):
        """Delete a journal entry (CASCADE deletes attachments). Returns True if found."""
        with self._connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM journal_entries WHERE id=?", (entry_id,)
            ).rowcount
        return rowcount > 0

    def get_entries(self, limit=100, offset=0, search=None, incident_id=None):
        """Return list of journal entries (newest first) with attachment_count.

        incident_id filtering:
          None (default) -> all entries
          0 -> only unassigned (WHERE incident_id IS NULL)
          N -> only entries for incident N
        """
        query = (
            "SELECT i.id, i.date, i.title, i.description, i.icon, i.incident_id, i.created_at, i.updated_at, "
            "(SELECT COUNT(*) FROM journal_attachments WHERE entry_id = i.id) AS attachment_count "
            "FROM journal_entries i"
        )
        conditions = []
        params = []
        if search:
            conditions.append("(i.title LIKE ? OR i.description LIKE ? OR i.date LIKE ?)")
            like = "%" + search + "%"
            params.extend([like, like, like])
        if incident_id is not None:
            if incident_id == 0:
                conditions.append("i.incident_id IS NULL")
            else:
                conditions.append("i.incident_id = ?")
                params.append(incident_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY i.date DESC, i.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_entry(self, entry_id):
        """Return single journal entry with attachment metadata (no blob data)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, date, title, description, icon, incident_id, created_at, updated_at FROM journal_entries WHERE id=?",
                (entry_id,),
            ).fetchone()
            if not row:
                return None
            entry = dict(row)
            attachments = conn.execute(
                "SELECT id, filename, mime_type, created_at FROM journal_attachments WHERE entry_id=? ORDER BY id",
                (entry_id,),
            ).fetchall()
            entry["attachments"] = [dict(a) for a in attachments]
        return entry

    def save_attachment(self, entry_id, filename, mime_type, data):
        """Save a file attachment for a journal entry. Returns attachment id."""
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO journal_attachments (entry_id, filename, mime_type, data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_id, filename, mime_type, data, now),
            )
            return cur.lastrowid

    def get_attachment(self, attachment_id):
        """Return attachment dict with data bytes, or None."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, entry_id, filename, mime_type, data, created_at "
                "FROM journal_attachments WHERE id=?",
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
                "DELETE FROM journal_attachments WHERE id=?", (attachment_id,)
            ).rowcount
        return rowcount > 0

    def get_attachment_count(self, entry_id):
        """Return number of attachments for a journal entry."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM journal_attachments WHERE entry_id=?",
                (entry_id,),
            ).fetchone()
        return row[0] if row else 0

    def check_entry_exists(self, date, title):
        """Check if a journal entry with same date + title exists. Returns True/False."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM journal_entries WHERE date=? AND title=? LIMIT 1",
                (date, title),
            ).fetchone()
        return row is not None

    def delete_all_entries(self):
        """Delete all journal entries (CASCADE deletes attachments). Returns count."""
        with self._connect() as conn:
            rowcount = conn.execute("DELETE FROM journal_entries").rowcount
        return rowcount

    def delete_entries_batch(self, ids):
        """Delete journal entries by list of IDs. Returns count of deleted."""
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM journal_entries WHERE id IN (%s)" % placeholders, ids
            ).rowcount
        return rowcount

    def get_active_entries(self):
        """Return all journal entries (for export context)."""
        return self.get_entries(limit=100)

    def get_entries_for_export(self, date_from=None, date_to=None, incident_id=None):
        """Return journal entries for export (no pagination).

        Args:
            date_from: Optional start date (YYYY-MM-DD), inclusive.
            date_to: Optional end date (YYYY-MM-DD), inclusive.
            incident_id: None=all, 0=unassigned, N=specific incident.
        """
        query = (
            "SELECT i.id, i.date, i.title, i.description, i.icon, i.incident_id, i.created_at, i.updated_at, "
            "(SELECT COUNT(*) FROM journal_attachments WHERE entry_id = i.id) AS attachment_count "
            "FROM journal_entries i"
        )
        conditions = []
        params = []
        if date_from:
            conditions.append("i.date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("i.date <= ?")
            params.append(date_to)
        if incident_id is not None:
            if incident_id == 0:
                conditions.append("i.incident_id IS NULL")
            else:
                conditions.append("i.incident_id = ?")
                params.append(incident_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY i.date DESC, i.created_at DESC"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── Incident Containers ──

    def save_incident(self, name, description=None, status="open", start_date=None, end_date=None, icon=None, is_demo=False):
        """Create a new incident container. Returns the new incident id."""
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO incidents (name, description, status, start_date, end_date, icon, created_at, updated_at, is_demo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, description, status, start_date, end_date, icon, now, now, int(is_demo)),
            )
            return cur.lastrowid

    def update_incident(self, incident_id, name, description=None, status="open", start_date=None, end_date=None, icon=None):
        """Update an existing incident container. Returns True if found."""
        now = utc_now()
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE incidents SET name=?, description=?, status=?, start_date=?, end_date=?, icon=?, updated_at=? WHERE id=?",
                (name, description, status, start_date, end_date, icon, now, incident_id),
            ).rowcount
        return rowcount > 0

    def delete_incident(self, incident_id):
        """Delete an incident container. Entries become unassigned (SET NULL). Returns True if found."""
        with self._connect() as conn:
            # Unassign entries first
            conn.execute(
                "UPDATE journal_entries SET incident_id = NULL WHERE incident_id = ?",
                (incident_id,),
            )
            rowcount = conn.execute(
                "DELETE FROM incidents WHERE id=?", (incident_id,)
            ).rowcount
        return rowcount > 0

    def get_incidents(self, status=None):
        """Return list of incident containers with entry_count."""
        query = (
            "SELECT i.id, i.name, i.description, i.status, i.start_date, i.end_date, "
            "i.icon, i.created_at, i.updated_at, "
            "(SELECT COUNT(*) FROM journal_entries WHERE incident_id = i.id) AS entry_count "
            "FROM incidents i"
        )
        params = []
        if status:
            query += " WHERE i.status = ?"
            params.append(status)
        query += " ORDER BY i.created_at DESC"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_incident(self, incident_id):
        """Return single incident container with entry_count."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT i.id, i.name, i.description, i.status, i.start_date, i.end_date, "
                "i.icon, i.created_at, i.updated_at, "
                "(SELECT COUNT(*) FROM journal_entries WHERE incident_id = i.id) AS entry_count "
                "FROM incidents i WHERE i.id=?",
                (incident_id,),
            ).fetchone()
        return dict(row) if row else None

    def assign_entries_to_incident(self, entry_ids, incident_id):
        """Assign journal entries to an incident. Returns count of updated entries."""
        if not entry_ids:
            return 0
        placeholders = ",".join("?" for _ in entry_ids)
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET incident_id = ? WHERE id IN (%s)" % placeholders,
                [incident_id] + list(entry_ids),
            ).rowcount
        return rowcount

    def unassign_entries(self, entry_ids):
        """Remove incident assignment from journal entries. Returns count."""
        if not entry_ids:
            return 0
        placeholders = ",".join("?" for _ in entry_ids)
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET incident_id = NULL WHERE id IN (%s)" % placeholders,
                list(entry_ids),
            ).rowcount
        return rowcount

    def assign_entries_by_date_range(self, incident_id, start_date, end_date):
        """Assign all journal entries in a date range to an incident. Returns count."""
        with self._connect() as conn:
            rowcount = conn.execute(
                "UPDATE journal_entries SET incident_id = ? WHERE date >= ? AND date <= ?",
                (incident_id, start_date, end_date),
            ).rowcount
        return rowcount
