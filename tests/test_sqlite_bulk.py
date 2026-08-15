"""Bulk write correctness and atomicity contracts."""

from __future__ import annotations

import sqlite3

import pytest

from app.storage import sqlite as sqlite_owner
from tests.sqlite_helpers import install_counting_connect


def _create_table(db_path):
    with sqlite_owner.connect_sqlite(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, text_value TEXT, int_value INTEGER, "
            "real_value REAL, blob_value BLOB, null_value TEXT)"
        )


def test_empty_bulk_does_not_open_connection(tmp_path, monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("empty input opened a connection")

    monkeypatch.setattr(sqlite_owner, "write_transaction", forbidden, raising=False)
    assert sqlite_owner.bulk_write(str(tmp_path / "unused.db"), "INSERT INTO x VALUES (?)", []) == 0
    assert sqlite_owner.bulk_write(str(tmp_path / "unused.db"), "INSERT INTO x VALUES (?)", iter(())) == 0
    assert calls == []


def test_bulk_preserves_types_and_consumes_generator_once(tmp_path):
    db_path = tmp_path / "types.db"
    _create_table(db_path)
    yielded = []

    def rows():
        yielded.append(1)
        yield (1, "text", 7, 1.25, b"bytes", None)

    count = sqlite_owner.bulk_write(
        str(db_path),
        "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
        rows(),
    )

    assert count == 1
    assert yielded == [1]
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT text_value, int_value, real_value, blob_value, null_value, "
            "typeof(text_value), typeof(int_value), typeof(real_value), typeof(blob_value), typeof(null_value) "
            "FROM records"
        ).fetchone()
    assert row == ("text", 7, 1.25, b"bytes", None, "text", "integer", "real", "blob", "null")


def test_bulk_is_atomic_when_one_row_is_invalid(tmp_path):
    db_path = tmp_path / "atomic.db"
    _create_table(db_path)

    with pytest.raises(sqlite3.IntegrityError):
        sqlite_owner.bulk_write(
            str(db_path),
            "INSERT INTO records (id, text_value) VALUES (?, ?)",
            [(1, "first"), (1, "duplicate"), (2, "never")],
        )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0


def test_bulk_reports_affected_rows_and_uses_one_transaction(tmp_path, monkeypatch):
    db_path = tmp_path / "count.db"
    _create_table(db_path)
    instances = install_counting_connect(monkeypatch, sqlite_owner)

    count = sqlite_owner.bulk_write(
        str(db_path),
        "INSERT OR IGNORE INTO records (id, text_value) VALUES (?, ?)",
        [(1, "first"), (1, "ignored"), (2, "second"), (3, "third")],
        chunk_size=2,
    )

    assert count == 3
    assert len(instances) == 1
    assert instances[0].commit_calls == 1
    assert instances[0].executemany_calls == 2
