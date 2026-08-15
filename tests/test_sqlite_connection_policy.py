"""Managed SQLite connection policy contracts."""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from app.storage import sqlite as sqlite_owner


def _closed(conn):
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_connect_sqlite_compatibility_seam(tmp_path):
    signature = inspect.signature(sqlite_owner.connect_sqlite)
    assert list(signature.parameters) == ["db_path", "kwargs"]
    with sqlite_owner.connect_sqlite(str(tmp_path / "compat.db")) as conn:
        assert conn.row_factory is None
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0


def test_open_read_applies_policy_rejects_writes_and_closes(tmp_path):
    db_path = str(tmp_path / "managed.db")
    with sqlite_owner.connect_sqlite(db_path) as setup:
        setup.execute("CREATE TABLE records (value TEXT)")

    with sqlite_owner.open_read(db_path) as conn:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO records VALUES ('blocked')")

    _closed(conn)


def test_open_read_closes_after_exception(tmp_path):
    db_path = str(tmp_path / "exception.db")
    with sqlite_owner.connect_sqlite(db_path):
        pass

    with pytest.raises(RuntimeError, match="injected"):
        with sqlite_owner.open_read(db_path) as conn:
            raise RuntimeError("injected")

    _closed(conn)


def test_open_readonly_handles_spaces_never_creates_and_closes(tmp_path):
    db_path = tmp_path / "directory with spaces" / "read only.db"
    db_path.parent.mkdir()
    with sqlite_owner.connect_sqlite(str(db_path)) as setup:
        setup.execute("CREATE TABLE records (value TEXT)")
        setup.execute("INSERT INTO records VALUES ('kept')")

    with sqlite_owner.open_readonly(str(db_path), timeout=2) as conn:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("SELECT value FROM records").fetchone()[0] == "kept"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 2_000
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO records VALUES ('blocked')")

    _closed(conn)
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        with sqlite_owner.open_readonly(str(missing)):
            pass
    assert not missing.exists()


def test_consistent_copy_parameterizes_destination_with_quote(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "copy's database.db"
    with sqlite_owner.connect_sqlite(str(source)) as conn:
        conn.execute("CREATE TABLE records (value TEXT)")
        conn.execute("INSERT INTO records VALUES ('kept')")

    sqlite_owner.consistent_copy(str(source), str(destination))

    assert sqlite_owner.verify_database(str(destination)) == "ok"
    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT value FROM records").fetchall() == [("kept",)]
