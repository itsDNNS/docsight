"""Shared assertions for SQLite infrastructure tests."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


class CountingConnection(sqlite3.Connection):
    """Connection subclass exposing transaction and bulk-call counts."""

    instances: list["CountingConnection"] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commit_calls = 0
        self.rollback_calls = 0
        self.executemany_calls = 0
        type(self).instances.append(self)

    def commit(self):
        self.commit_calls += 1
        return super().commit()

    def rollback(self):
        self.rollback_calls += 1
        return super().rollback()

    def executemany(self, sql, parameters, /):
        self.executemany_calls += 1
        return super().executemany(sql, parameters)


def install_counting_connect(monkeypatch, sqlite_module):
    """Patch an infrastructure module so new connections are countable."""
    original = sqlite_module.sqlite3.connect
    CountingConnection.instances.clear()

    def connect(*args, **kwargs):
        kwargs.setdefault("factory", CountingConnection)
        return original(*args, **kwargs)

    monkeypatch.setattr(sqlite_module.sqlite3, "connect", connect)
    return CountingConnection.instances


def schema_digest(db_path: str | Path) -> str:
    """Hash normalized user-visible schema SQL."""
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    normalized = "\n".join(
        "|".join("" if value is None else " ".join(str(value).split()) for value in row)
        for row in rows
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def data_digest(db_path: str | Path, *, exclude: set[str] | None = None) -> tuple[dict[str, int], str]:
    """Return per-table counts and a stable hash over ordered row tuples."""
    excluded = {"sqlite_sequence", "_docsight_migrations", *(exclude or set())}
    with sqlite3.connect(str(db_path)) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if row[0] not in excluded
        ]
        counts = {}
        payload = []
        for table in tables:
            quoted = table.replace('"', '""')
            rows = conn.execute(f'SELECT * FROM "{quoted}" ORDER BY rowid').fetchall()
            counts[table] = len(rows)
            payload.append((table, rows))
    return counts, hashlib.sha256(repr(payload).encode()).hexdigest()
