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
        # A normal connection, so checking the WAL-mode file leaves no sidecar behind.
        with closing(sqlite3.connect(source)) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        replacements.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", checked_replace)
    result = restore_backup(_archive({"docsis_history.db": replacement}), str(data_dir))

    assert result["restored_files"] == ["docsis_history.db"]
    assert len(replacements) == 1
    assert not (data_dir / "docsis_history.db-wal").exists()
    assert not (data_dir / "docsis_history.db-shm").exists()
    assert not list(data_dir.glob(".docsight-restore-*"))
    assert verify_database(str(live)) == "ok"
    with closing(sqlite3.connect(live)) as conn:
        assert conn.execute("SELECT value FROM records ORDER BY rowid").fetchall() == [
            ("new",), ("second",)
        ]


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


@pytest.mark.parametrize("backup_has_tokens", [True, False], ids=["with-tokens", "before-tokens"])
def test_restore_skips_session_state_and_keeps_live_api_tokens(tmp_path, backup_has_tokens):
    from app.storage import SnapshotStorage

    if backup_has_tokens:
        backup_db = tmp_path / "backup.db"
        SnapshotStorage(str(backup_db), max_days=7).create_api_token("revoked-since")
        backup = backup_db.read_bytes()
    else:
        backup = _database_bytes(tmp_path, ["old"])
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    live = SnapshotStorage(str(data_dir / "docsis_history.db"), max_days=7)
    live.create_api_token("current")
    live.revoke_api_token(live.create_api_token("revoked")[0])
    (data_dir / ".session_key").write_bytes(b"live-key")

    result = restore_backup(_archive({
        "docsis_history.db": backup, ".session_key": b"backup-key", ".auth_state": b"backup-state",
    }), str(data_dir))

    assert result["restored_files"] == ["docsis_history.db"]
    assert not list(data_dir.glob(".docsight-restore-*"))
    assert not list(data_dir.glob("docsis_history.db-*"))
    assert (data_dir / ".session_key").read_bytes() == b"live-key"
    assert not (data_dir / ".auth_state").exists()
    with closing(sqlite3.connect(data_dir / "docsis_history.db")) as conn:
        rows = conn.execute("SELECT name, revoked FROM api_tokens ORDER BY id").fetchall()
    assert rows == [("current", 0), ("revoked", 1)]


def test_config_reload_uses_the_restored_encryption_key(tmp_path):
    from app.config import ConfigManager

    ConfigManager(str(tmp_path / "backup")).save({"modem_password": "from-backup"})
    live = ConfigManager(str(tmp_path / "live"))
    for name in ("config.json", ".config_key"):
        (tmp_path / "live" / name).write_bytes((tmp_path / "backup" / name).read_bytes())

    live.reload()

    assert live.get("modem_password") == "from-backup"


def test_restore_migrates_an_older_database_before_it_goes_live(tmp_path):
    from app.storage.migrations import CORE_MIGRATIONS, run_migrations

    old_db = tmp_path / "old.db"
    run_migrations(str(old_db), CORE_MIGRATIONS[:-1])
    with closing(sqlite3.connect(old_db)) as conn:
        conn.execute(
            "INSERT INTO smart_capture_executions (trigger_type, action_type, status, last_error, created_at) "
            "VALUES ('t', 'capture', 'expired', 'STT returned 500: upstream body', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    restore_backup(_archive({"docsis_history.db": old_db.read_bytes()}), str(data_dir))

    with closing(sqlite3.connect(data_dir / "docsis_history.db")) as conn:
        assert conn.execute("SELECT last_error FROM smart_capture_executions").fetchall() == [("STT returned 500",)]


def test_token_revoked_during_restore_stays_revoked(tmp_path, monkeypatch):
    import threading

    from app.modules.backup import backup as backup_module
    from app.storage import SnapshotStorage

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    live = SnapshotStorage(str(data_dir / "docsis_history.db"), max_days=7)
    token_id, _ = live.create_api_token("integration")
    real_replace = backup_module.os.replace
    revocation = threading.Thread(target=live.revoke_api_token, args=(token_id,))

    def replace_while_revoking(source, destination):
        revocation.start()
        revocation.join(0.3)
        assert revocation.is_alive(), "the revocation must wait for the swap"
        real_replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", replace_while_revoking)
    restore_backup(_archive({"docsis_history.db": _database_bytes(tmp_path, ["old"])}), str(data_dir))
    revocation.join(5)

    with closing(sqlite3.connect(data_dir / "docsis_history.db")) as conn:
        assert conn.execute("SELECT revoked FROM api_tokens WHERE id = ?", (token_id,)).fetchone() == (1,)
