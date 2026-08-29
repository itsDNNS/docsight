"""Verified staged database restore contracts."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from app.modules.backup.backup import FORMAT_VERSION, MAGIC, restore_backup
from app.storage.sqlite import verify_database


def _archive(files: dict[str, bytes]) -> io.BytesIO:
    meta = json.dumps({"magic": MAGIC, "format_version": FORMAT_VERSION}).encode()
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tar:
        for name, content in {"backup_meta.json": meta, **files}.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    payload.seek(0)
    return payload


def _database_bytes(tmp_path, rows):
    handle = tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".db", delete=False)
    path = Path(handle.name)
    handle.close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE records (value TEXT)")
        conn.executemany("INSERT INTO records VALUES (?)", [(row,) for row in rows])
        conn.commit()
    payload = path.read_bytes()
    path.unlink()
    return payload


def _claim_database_bytes(tmp_path):
    handle = tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".db", delete=False)
    path = Path(handle.name)
    handle.close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE TABLE de_tkg_claim_drafts "
            "(id INTEGER PRIMARY KEY, ticket_ref TEXT, is_demo INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO de_tkg_claim_drafts VALUES (1, 'SYNTHETIC-REAL', 0)"
        )
        conn.commit()
    payload = path.read_bytes()
    path.unlink()
    return payload


def test_restore_verifies_then_atomically_publishes_and_removes_sidecars(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    live = data_dir / "docsis_history.db"
    live.write_bytes(_database_bytes(tmp_path, ["old"]))
    (data_dir / "docsis_history.db-wal").write_bytes(b"stale wal")
    (data_dir / "docsis_history.db-shm").write_bytes(b"stale shm")
    replacement = _database_bytes(tmp_path, ["new", "second"])

    from app.modules.backup import backup as backup_module

    real_replace = backup_module.os.replace
    replacements = []

    def checked_replace(source, destination):
        source = Path(source)
        destination = Path(destination)
        assert source.parent == data_dir
        assert destination == live
        assert verify_database(str(source)) == "ok"
        replacements.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", checked_replace)
    result = restore_backup(_archive({"docsis_history.db": replacement}), str(data_dir))

    assert result["restored_files"] == ["docsis_history.db"]
    assert len(replacements) == 1
    assert verify_database(str(live)) == "ok"
    with sqlite3.connect(live) as conn:
        assert conn.execute("SELECT value FROM records ORDER BY rowid").fetchall() == [
            ("new",), ("second",)
        ]
    assert not (data_dir / "docsis_history.db-wal").exists()
    assert not (data_dir / "docsis_history.db-shm").exists()
    assert not list(data_dir.glob(".docsight-restore-*"))


def test_corrupt_staged_database_leaves_live_database_byte_identical(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    live = data_dir / "docsis_history.db"
    live.write_bytes(_database_bytes(tmp_path, ["retained"]))
    before = hashlib.sha256(live.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="database|integrity|malformed|encrypted"):
        restore_backup(_archive({"docsis_history.db": b"not a sqlite database"}), str(data_dir))

    assert hashlib.sha256(live.read_bytes()).hexdigest() == before
    with sqlite3.connect(live) as conn:
        assert conn.execute("SELECT value FROM records").fetchall() == [("retained",)]
    assert not list(data_dir.glob(".docsight-restore-*"))


def test_verified_restore_retains_real_tkg_claim_drafts(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = restore_backup(
        _archive({"docsis_history.db": _claim_database_bytes(tmp_path)}),
        str(data_dir),
    )

    assert result["restored_files"] == ["docsis_history.db"]
    assert verify_database(str(data_dir / "docsis_history.db")) == "ok"
    with sqlite3.connect(data_dir / "docsis_history.db") as conn:
        assert conn.execute(
            "SELECT ticket_ref, is_demo FROM de_tkg_claim_drafts"
        ).fetchall() == [("SYNTHETIC-REAL", 0)]


def test_all_databases_are_verified_before_any_database_is_published(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    main = data_dir / "docsis_history.db"
    monitor = data_dir / "connection_monitor.db"
    main.write_bytes(_database_bytes(tmp_path, ["main-old"]))
    monitor.write_bytes(_database_bytes(tmp_path, ["monitor-old"]))
    main_before = main.read_bytes()
    monitor_before = monitor.read_bytes()

    from app.modules.backup import backup as backup_module

    replace_calls = []
    monkeypatch.setattr(
        backup_module.os,
        "replace",
        lambda *args: replace_calls.append(args),
    )

    with pytest.raises(ValueError):
        restore_backup(
            _archive({
                "docsis_history.db": _database_bytes(tmp_path, ["main-new"]),
                "connection_monitor.db": b"corrupt",
            }),
            str(data_dir),
        )

    assert replace_calls == []
    assert main.read_bytes() == main_before
    assert monitor.read_bytes() == monitor_before
