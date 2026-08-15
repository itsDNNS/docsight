"""Write transaction ownership and failure contracts."""

from __future__ import annotations

import sqlite3

import pytest

from app.storage import sqlite as sqlite_owner
from tests.sqlite_helpers import install_counting_connect


def _create_table(db_path):
    with sqlite_owner.connect_sqlite(str(db_path)) as conn:
        conn.execute("CREATE TABLE records (value TEXT UNIQUE)")


def test_write_transaction_commits_exactly_once_and_closes(tmp_path, monkeypatch):
    db_path = tmp_path / "success.db"
    _create_table(db_path)
    instances = install_counting_connect(monkeypatch, sqlite_owner)

    with sqlite_owner.write_transaction(str(db_path)) as conn:
        conn.execute("INSERT INTO records VALUES ('kept')")

    assert len(instances) == 1
    assert instances[0].commit_calls == 1
    assert instances[0].rollback_calls == 0
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_write_transaction_rolls_back_fully_and_closes(tmp_path, monkeypatch):
    db_path = tmp_path / "rollback.db"
    _create_table(db_path)
    instances = install_counting_connect(monkeypatch, sqlite_owner)

    with pytest.raises(RuntimeError, match="injected"):
        with sqlite_owner.write_transaction(str(db_path)) as conn:
            conn.execute("INSERT INTO records VALUES ('discarded')")
            raise RuntimeError("injected")

    assert instances[0].commit_calls == 0
    assert instances[0].rollback_calls == 1
    with sqlite3.connect(db_path) as check:
        assert check.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


@pytest.mark.parametrize("same_path", [True, False])
def test_nested_write_transactions_are_rejected(tmp_path, same_path):
    first = tmp_path / "first.db"
    second = first if same_path else tmp_path / "second.db"
    with sqlite_owner.write_transaction(str(first)):
        with pytest.raises(RuntimeError, match="nested write_transaction"):
            with sqlite_owner.write_transaction(str(second)):
                pass


def test_busy_failure_happens_at_begin_and_recovers_after_release(tmp_path):
    db_path = tmp_path / "busy.db"
    _create_table(db_path)
    holder = sqlite3.connect(db_path, autocommit=True)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            with sqlite_owner.write_transaction(str(db_path), timeout=0.05):
                pytest.fail("a busy transaction must not yield")
    finally:
        holder.rollback()
        holder.close()

    with sqlite_owner.write_transaction(str(db_path), timeout=0.05) as conn:
        conn.execute("INSERT INTO records VALUES ('after-release')")
