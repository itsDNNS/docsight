"""Verified staged database restore contracts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

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


def _database_bytes(tmp_path, rows, journal_mode="delete"):
    handle = tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".db", delete=False)
    path = Path(handle.name)
    handle.close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA journal_mode={journal_mode}")
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


def test_restore_verifies_then_copies_into_the_open_live_database(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    live = data_dir / "docsis_history.db"
    live.write_bytes(_database_bytes(tmp_path, ["old"]))
    replacement = _database_bytes(tmp_path, ["new", "second"])

    from app.modules.backup import backup as backup_module

    real_copy = backup_module.replace_contents
    copies = []

    def checked_copy(source, target):
        assert Path(source).parent == data_dir
        assert Path(target) == live
        with closing(sqlite3.connect(source)) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        copies.append(source)
        real_copy(source, target)

    monkeypatch.setattr(backup_module, "replace_contents", checked_copy)
    with closing(sqlite3.connect(live)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    # A reader in the middle of a transaction, like a running DOCSight.
    with closing(sqlite3.connect(live, isolation_level=None)) as reader:
        reader.execute("BEGIN")
        assert reader.execute("SELECT value FROM records").fetchall() == [("old",)]
        result = restore_backup(_archive({"docsis_history.db": replacement}), str(data_dir))
        assert reader.execute("SELECT value FROM records").fetchall() == [("old",)]
        reader.execute("COMMIT")
        assert reader.execute("SELECT value FROM records ORDER BY rowid").fetchall() == [("new",), ("second",)]

    assert result["restored_files"] == ["docsis_history.db"]
    assert len(copies) == 1
    assert not list(data_dir.glob(".docsight-restore-*"))
    assert verify_database(str(live)) == "ok"


def test_restore_replaces_a_damaged_live_database(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "docsis_history.db").write_bytes(b"not a database, damaged" * 100)

    restore_backup(_archive({"docsis_history.db": _database_bytes(tmp_path, ["rescued"])}), str(data_dir))

    with closing(sqlite3.connect(data_dir / "docsis_history.db")) as conn:
        assert conn.execute("SELECT value FROM records").fetchall() == [("rescued",)]
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


def test_failure_while_staging_leaves_no_temp_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    live = data_dir / "docsis_history.db"
    live.write_bytes(_database_bytes(tmp_path, ["live"]))
    before = live.read_bytes()

    from app.modules.backup import backup as backup_module

    real_copy = backup_module.shutil.copyfileobj
    copies = []

    def fail_on_second_file(source, destination):
        copies.append(source)
        if len(copies) == 2:
            destination.write(b"partial")
            raise OSError("injected staging failure")
        real_copy(source, destination)

    monkeypatch.setattr(backup_module.shutil, "copyfileobj", fail_on_second_file)

    with pytest.raises(OSError, match="injected staging failure"):
        restore_backup(_archive({
            "docsis_history.db": _database_bytes(tmp_path, ["new"]), "config.json": b"{}",
        }), str(data_dir))

    assert sorted(path.name for path in data_dir.iterdir()) == ["docsis_history.db"]
    assert live.read_bytes() == before


@pytest.mark.parametrize("opened", [False, True], ids=["before-open", "after-open"])
@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_failure_handing_over_a_staged_file_removes_it(tmp_path, monkeypatch, opened, error):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    real_fdopen = os.fdopen
    descriptors = []

    def fail_fdopen(fd, *args, **kwargs):
        descriptors.append(fd)
        if opened:
            real_fdopen(fd, *args, **kwargs)  # the dropped file object closes the descriptor
        raise error("injected handoff failure")

    from app.modules.backup import backup as backup_module

    monkeypatch.setattr(backup_module.os, "fdopen", fail_fdopen)

    with pytest.raises(error, match="injected handoff failure"):
        restore_backup(_archive({"config.json": b"{}"}), str(data_dir))

    assert list(data_dir.iterdir()) == []
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_staged_files_are_written_through_their_temp_descriptor(tmp_path, monkeypatch):
    from app.modules.backup import backup as backup_module

    opened = []
    monkeypatch.setattr(backup_module, "open", lambda path, *args: opened.append(path) or open(path, *args),
                        raising=False)

    restore_backup(_archive({"config.json": b"{}"}), str(tmp_path))

    assert not [path for path in opened if ".docsight-restore-" in str(path)]


def test_failed_restore_removes_sqlite_sidecars_of_staged_databases(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    from app.modules.backup import backup as backup_module

    monkeypatch.setattr(backup_module, "run_migrations", Mock(side_effect=RuntimeError("injected migration failure")))

    with pytest.raises(RuntimeError, match="injected migration failure"):
        restore_backup(_archive({"docsis_history.db": _database_bytes(tmp_path, ["new"], "wal")}), str(data_dir))

    assert list(data_dir.iterdir()) == []


def test_validation_decompresses_the_archive_once():
    class CountingReader(io.BytesIO):
        read_bytes = 0

        def read(self, size=-1):
            data = super().read(size)
            self.read_bytes += len(data)
            return data

    from app.modules.backup.backup import validate_backup

    archive = CountingReader(_archive({"config.json": os.urandom(4 << 20)}).getvalue())
    validate_backup(archive)

    assert archive.read_bytes < 1.5 * len(archive.getvalue())


def test_archive_with_a_bad_gzip_checksum_is_rejected(tmp_path):
    payload = bytearray(_archive({"config.json": b"{}"}).getvalue())
    payload[-8] ^= 0xFF  # the CRC-32 in the gzip trailer

    with pytest.raises(ValueError, match="Invalid archive"):
        restore_backup(bytes(payload), str(tmp_path / "data"))

    assert not (tmp_path / "data").exists()


def test_repeated_member_name_leaves_no_temp_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    real_members = tarfile.TarFile.getmembers
    monkeypatch.setattr(tarfile.TarFile, "getmembers", lambda tar: real_members(tar) * 2)

    restore_backup(_archive({"config.json": b"{}"}), str(data_dir))

    assert sorted(path.name for path in data_dir.iterdir()) == ["config.json"]


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
    run_migrations(str(old_db), [m for m in CORE_MIGRATIONS if m.migration_id < "core-0006"])
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
    real_copy = backup_module.replace_contents
    revocation = threading.Thread(target=live.revoke_api_token, args=(token_id,))

    def copy_while_revoking(source, target):
        revocation.start()
        revocation.join(0.3)
        assert revocation.is_alive(), "the revocation must wait for the copy"
        real_copy(source, target)

    monkeypatch.setattr(backup_module, "replace_contents", copy_while_revoking)
    restore_backup(_archive({"docsis_history.db": _database_bytes(tmp_path, ["old"])}), str(data_dir))
    revocation.join(5)

    with closing(sqlite3.connect(data_dir / "docsis_history.db")) as conn:
        assert conn.execute("SELECT revoked FROM api_tokens WHERE id = ?", (token_id,)).fetchone() == (1,)


def test_settings_save_waits_for_restore_and_reload(make_app, builtin_module_loader_factory, tmp_path, monkeypatch):
    import threading

    from app.config import ConfigManager

    config = ConfigManager(str(tmp_path / "data"))
    app = make_app(config_manager=config, module_loader_factory=builtin_module_loader_factory(config))
    save = threading.Thread(target=config.save, args=({"language": "de"},))
    real_reload = config.reload
    waited = []

    def restore_while_saving(_data, _data_dir, _restored):
        save.start()
        save.join(0.2)
        return {"restored_files": [], "meta": {}}

    def reload_after_restore():
        waited.append(save.is_alive())  # the save is still waiting when the key is reloaded
        real_reload()

    monkeypatch.setattr("app.modules.backup.routes.restore_backup", restore_while_saving)
    monkeypatch.setattr(config, "reload", reload_after_restore)
    response = app.test_client().post(
        "/api/restore", data={"file": (io.BytesIO(b"archive"), "backup.tar.gz")}, content_type="multipart/form-data",
    )
    save.join(5)

    assert response.status_code == 200
    assert waited == [True]
    assert config.get("language") == "de"


@pytest.mark.parametrize(("files", "failure"), [
    (("docsis_history.db",), None),
    (("docsis_history.db",), "reload"),
    (("docsis_history.db", "connection_monitor.db"), "second-copy"),
    (("docsis_history.db",), "after-copy"),
    (("config.json",), None),
], ids=["database", "database-reload-fails", "database-then-copy-fails", "copy-fails-after-copying", "config-only"])
def test_restore_rebuilds_only_the_storages_of_replaced_databases(
    make_app, builtin_module_loader_factory, tmp_path, monkeypatch, files, failure,
):
    from app.config import ConfigManager
    from app.modules.backup import backup
    from app.modules.journal.routes import _get_journal_storage
    from app.runtime import get_runtime
    from app.storage import SnapshotStorage

    config = ConfigManager(str(tmp_path / "data"))
    storage = SnapshotStorage(str(tmp_path / "data" / "docsis_history.db"))
    app = make_app(config_manager=config, storage=storage, module_loader_factory=builtin_module_loader_factory(config))
    client = app.test_client()
    assert client.get("/api/journal").status_code == 200
    with app.app_context():
        journal = _get_journal_storage()
    get_runtime(app).derived_storage.set_value("speedtest_last_trigger", 123.0)
    core_only = tmp_path / "core-only.db"
    SnapshotStorage(str(core_only))  # a backup from an instance that never opened the journal
    contents = {"docsis_history.db": core_only.read_bytes(), "connection_monitor.db": core_only.read_bytes(),
                "config.json": b"{}"}
    real_copy, copies = backup.replace_contents, []

    def copy(source, target):  # copies the first database, then fails as told
        copies.append(target)
        if len(copies) == 1:
            real_copy(source, target)
        if failure == "after-copy" or len(copies) == 2:
            raise TimeoutError("copy step timed out")

    if failure == "reload":
        monkeypatch.setattr(config, "reload", Mock(side_effect=RuntimeError("reload failed")))
    elif failure:
        monkeypatch.setattr(backup, "replace_contents", copy)

    response = client.post(
        "/api/restore",
        data={"file": (_archive({name: contents[name] for name in files}), "backup.tar.gz")},
        content_type="multipart/form-data",
    )

    assert response.status_code == (500 if failure else 200)
    assert client.get("/api/journal").status_code == 200
    with app.app_context():
        assert (_get_journal_storage() is journal) == ("docsis_history.db" not in files)
    assert get_runtime(app).derived_storage.value("speedtest_last_trigger", 0.0) == 123.0
