"""Tests for backup and restore functionality."""

import json
import os
import sqlite3
import tarfile
from datetime import datetime as real_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from io import BytesIO

from app.modules.backup import backup as backup_module
from app.modules.backup.backup import (
    BACKUP_META_FILE,
    FORMAT_VERSION,
    MAGIC,
    browse_directory,
    cleanup_old_backups,
    create_backup_to_file,
    list_backups,
    restore_backup,
    validate_backup,
)
from app.modules.backup.collector import BackupCollector


# ── Fixtures ──


@pytest.fixture
def data_dir(tmp_path):
    """Create a minimal data directory with a SQLite DB and config files."""
    d = tmp_path / "data"
    d.mkdir()

    # Create SQLite database with some data
    db_path = d / "docsis_history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, timestamp TEXT, summary_json TEXT, ds_channels_json TEXT, us_channels_json TEXT)")
    conn.execute("INSERT INTO snapshots VALUES (1, '2026-01-01', '{}', '[]', '[]')")
    # Add a demo row that should be excluded
    conn.execute("ALTER TABLE snapshots ADD COLUMN is_demo INTEGER DEFAULT 0")
    conn.execute("INSERT INTO snapshots (id, timestamp, summary_json, ds_channels_json, us_channels_json, is_demo) VALUES (2, '2026-01-02', '{}', '[]', '[]', 1)")
    conn.execute(
        "CREATE TABLE de_tkg_claim_drafts "
        "(id INTEGER PRIMARY KEY, ticket_ref TEXT, is_demo INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "INSERT INTO de_tkg_claim_drafts VALUES (1, 'SYNTHETIC-REAL', 0)"
    )
    conn.execute(
        "INSERT INTO de_tkg_claim_drafts VALUES (2, 'SYNTHETIC-DEMO', 1)"
    )
    conn.commit()
    conn.close()

    # Create config files
    config = {"modem_type": "fritzbox", "poll_interval": 900}
    (d / "config.json").write_text(json.dumps(config))
    (d / ".config_key").write_bytes(b"test-key-data")
    (d / ".session_key").write_bytes(b"session-secret")
    (d / ".auth_state").write_bytes(b"auth-state-fingerprint")

    return str(d)


@pytest.fixture
def backup_dir(tmp_path):
    """Create an empty backup directory."""
    d = tmp_path / "backups"
    d.mkdir()
    return str(d)


@pytest.fixture
def backup_path(data_dir, backup_dir):
    """Create an archive through the production file-backed backup path."""
    filename = create_backup_to_file(data_dir, backup_dir)
    return Path(backup_dir) / filename


# ── TestCreateBackup ──


class TestCreateBackup:
    def test_creates_valid_archive(self, backup_path):
        with tarfile.open(backup_path, mode="r:gz") as tar:
            names = tar.getnames()
            assert BACKUP_META_FILE in names
            assert "docsis_history.db" in names
            assert "config.json" in names
            assert ".config_key" in names
            assert ".session_key" in names
            assert ".auth_state" in names

    def test_meta_has_required_fields(self, backup_path):
        with tarfile.open(backup_path, mode="r:gz") as tar:
            meta = json.loads(tar.extractfile(BACKUP_META_FILE).read())
            assert meta["magic"] == MAGIC
            assert meta["format_version"] == FORMAT_VERSION
            assert "timestamp" in meta
            assert "app_version" in meta
            assert "tables" in meta

    def test_demo_data_excluded(self, backup_path):
        # Extract the DB from the archive and check demo data is gone
        with tarfile.open(backup_path, mode="r:gz") as tar:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(tar.extractfile("docsis_history.db").read())
                tmp_path = tmp.name
        try:
            conn = sqlite3.connect(tmp_path)
            count = conn.execute("SELECT COUNT(*) FROM snapshots WHERE is_demo = 1").fetchone()[0]
            assert count == 0
            # Non-demo data should still be there
            total = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            assert total == 1
            claim_rows = conn.execute(
                "SELECT ticket_ref, is_demo FROM de_tkg_claim_drafts ORDER BY id"
            ).fetchall()
            assert claim_rows == [("SYNTHETIC-REAL", 0)]
            conn.close()
        finally:
            os.unlink(tmp_path)

    def test_handles_missing_db(self, tmp_path):
        """Backup should work even without a database file."""
        d = tmp_path / "empty_data"
        d.mkdir()
        (d / "config.json").write_text("{}")
        backup_dir = tmp_path / "backups"
        filename = create_backup_to_file(str(d), backup_dir)
        with tarfile.open(backup_dir / filename, mode="r:gz") as tar:
            names = tar.getnames()
            assert "docsis_history.db" not in names
            assert BACKUP_META_FILE in names

    def test_backup_uses_data_volume_for_vacuum_workspace(
        self, data_dir, backup_dir, monkeypatch
    ):
        real_temporary_directory = backup_module.tempfile.TemporaryDirectory
        temporary_directories = []

        def checked_temporary_directory(*args, **kwargs):
            temporary_directories.append(kwargs)
            return real_temporary_directory(*args, **kwargs)

        monkeypatch.setattr(
            backup_module.tempfile,
            "TemporaryDirectory",
            checked_temporary_directory,
        )

        create_backup_to_file(data_dir, backup_dir)

        assert len(temporary_directories) == 1
        assert temporary_directories[0]["dir"] == data_dir
        assert temporary_directories[0]["prefix"].startswith(".")

    def test_create_to_file(self, data_dir, backup_dir):
        filename = create_backup_to_file(data_dir, backup_dir)
        assert filename.startswith("docsight_backup_")
        assert filename.endswith(".tar.gz")
        assert os.path.exists(os.path.join(backup_dir, filename))

    def test_create_to_file_uses_atomic_file_backed_archive(
        self, data_dir, backup_dir, monkeypatch
    ):
        """Scheduled backups build on disk and publish only a complete archive."""
        real_replace = os.replace
        real_write_backup_archive = backup_module._write_backup_archive
        replace_calls = []
        work_dirs = []

        def checked_replace(src, dst):
            src_path = Path(src)
            dst_path = Path(dst)
            assert src_path.parent == Path(backup_dir)
            assert dst_path.parent == Path(backup_dir)
            assert tarfile.is_tarfile(src_path)
            replace_calls.append((src_path, dst_path))
            real_replace(src, dst)

        def checked_archive_write(data_path, archive_target, work_dir=None):
            work_dirs.append(work_dir)
            return real_write_backup_archive(
                data_path, archive_target, work_dir=work_dir
            )

        monkeypatch.setattr(backup_module.os, "replace", checked_replace)
        monkeypatch.setattr(
            backup_module, "_write_backup_archive", checked_archive_write
        )

        filename = create_backup_to_file(data_dir, backup_dir)
        archive_path = Path(backup_dir) / filename

        assert len(replace_calls) == 1
        assert replace_calls[0][1] == archive_path
        assert work_dirs == [data_dir]
        assert archive_path.is_file()
        with tarfile.open(archive_path, mode="r:gz") as tar:
            assert BACKUP_META_FILE in tar.getnames()
            assert "docsis_history.db" in tar.getnames()
            assert "config.json" in tar.getnames()
        assert set(Path(backup_dir).iterdir()) == {archive_path}

    def test_create_to_file_removes_partial_temp_after_archive_failure(
        self, data_dir, backup_dir, monkeypatch
    ):
        """A failed archive write leaves an existing completed backup untouched."""

        class FixedDatetime:
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2026, 7, 28, 12, 34, 56, tzinfo=tz)

        completed = Path(backup_dir) / "docsight_backup_2026-07-28_123456.tar.gz"
        completed.write_bytes(b"existing-complete-backup")

        def fail_archive_write(_data_dir, archive_target, work_dir=None):
            assert work_dir == data_dir
            Path(archive_target).write_bytes(b"partial")
            raise RuntimeError("injected archive failure")

        monkeypatch.setattr(backup_module, "datetime", FixedDatetime)
        monkeypatch.setattr(
            backup_module, "_write_backup_archive", fail_archive_write, raising=False
        )

        with pytest.raises(RuntimeError, match="injected archive failure"):
            create_backup_to_file(data_dir, backup_dir)

        assert completed.read_bytes() == b"existing-complete-backup"
        assert set(Path(backup_dir).iterdir()) == {completed}


class TestBackupDownloadRoute:
    @staticmethod
    def _app(data_dir, monkeypatch):
        from flask import Flask
        from app.modules.backup import routes

        config_mgr = MagicMock()
        config_mgr.data_dir = data_dir

        test_app = Flask(__name__)
        test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
        test_app.register_blueprint(routes.bp)
        monkeypatch.setattr(routes, "get_config_manager", lambda: config_mgr)
        monkeypatch.setattr("app.web._auth_required", lambda: False)
        return test_app

    def test_download_is_file_backed_and_cleans_up_on_close(
        self, data_dir, tmp_path, monkeypatch
    ):
        from app.modules.backup import routes

        temp_dir = tmp_path / "manual-backup"
        archive_work_dirs = []

        def make_temp_dir(*args, **kwargs):
            assert kwargs["dir"] == data_dir
            assert kwargs["prefix"].startswith(".")
            temp_dir.mkdir()
            return str(temp_dir)

        real_write_backup_archive = routes._write_backup_archive

        def checked_archive_write(data_path, archive_target, work_dir=None):
            archive_work_dirs.append(work_dir)
            return real_write_backup_archive(
                data_path, archive_target, work_dir=work_dir
            )

        monkeypatch.setattr(
            routes, "_write_backup_archive", checked_archive_write
        )
        monkeypatch.setattr(
            routes, "tempfile", SimpleNamespace(mkdtemp=make_temp_dir), raising=False
        )
        app = self._app(data_dir, monkeypatch)

        response = app.test_client().post("/api/backup", buffered=False)

        assert response.status_code == 200
        assert response.mimetype == "application/gzip"
        assert "attachment" in response.headers["Content-Disposition"]
        assert not isinstance(response.response, BytesIO)
        assert archive_work_dirs == [str(temp_dir)]
        archives = list(temp_dir.glob("*.tar.gz"))
        assert len(archives) == 1
        assert tarfile.is_tarfile(archives[0])

        response.close()

        assert not temp_dir.exists()

    def test_download_cleans_up_after_archive_write_exception(
        self, data_dir, tmp_path, monkeypatch
    ):
        from app.modules.backup import routes

        temp_dir = tmp_path / "failed-manual-backup"

        def make_temp_dir(*args, **kwargs):
            assert kwargs["dir"] == data_dir
            assert kwargs["prefix"].startswith(".")
            temp_dir.mkdir()
            return str(temp_dir)

        def fail_archive_write(*args, **kwargs):
            raise RuntimeError("injected route archive failure")

        monkeypatch.setattr(
            routes, "tempfile", SimpleNamespace(mkdtemp=make_temp_dir), raising=False
        )
        monkeypatch.setattr(
            routes, "_write_backup_archive", fail_archive_write, raising=False
        )
        app = self._app(data_dir, monkeypatch)

        response = app.test_client().post("/api/backup")

        assert response.status_code == 500
        assert response.get_json() == {"error": "injected route archive failure"}
        assert not temp_dir.exists()

    def test_download_closes_stream_before_running_registered_cleanup(
        self, data_dir, tmp_path, monkeypatch
    ):
        from flask import Response
        from app.modules.backup import routes

        temp_dir = tmp_path / "close-order-backup"
        close_events = []

        class TrackingIterable:
            def __iter__(self):
                yield b"archive"

            def close(self):
                close_events.append("iterable")

        def make_temp_dir(*args, **kwargs):
            temp_dir.mkdir()
            return str(temp_dir)

        def write_archive(data_path, archive_target, work_dir=None):
            Path(archive_target).write_bytes(b"archive")

        def remove_temp_dir(path, ignore_errors=False):
            assert path == str(temp_dir)
            assert ignore_errors is True
            close_events.append("cleanup")

        monkeypatch.setattr(
            routes, "tempfile", SimpleNamespace(mkdtemp=make_temp_dir), raising=False
        )
        monkeypatch.setattr(routes, "_write_backup_archive", write_archive)
        monkeypatch.setattr(
            routes,
            "send_file",
            lambda *args, **kwargs: Response(
                TrackingIterable(),
                mimetype="application/gzip",
                direct_passthrough=True,
            ),
        )
        monkeypatch.setattr(routes.shutil, "rmtree", remove_temp_dir)
        app = self._app(data_dir, monkeypatch)

        response = app.test_client().post("/api/backup", buffered=False)

        assert close_events == []
        assert next(iter(response.response)) == b"archive"
        assert close_events == []

        response.close()

        assert close_events == ["iterable", "cleanup"]


# ── TestValidateBackup ──


class TestValidateBackup:
    def test_valid_backup(self, backup_path):
        with backup_path.open("rb") as archive:
            meta = validate_backup(archive)
        assert meta["magic"] == MAGIC
        assert meta["has_database"] is True
        assert meta["has_config"] is True
        assert "files" in meta

    def test_accepts_bytes(self, backup_path):
        meta = validate_backup(backup_path.read_bytes())
        assert meta["magic"] == MAGIC

    def test_invalid_archive(self):
        with pytest.raises(ValueError, match="Invalid archive"):
            validate_backup(b"not a tar file")

    def test_missing_meta(self, tmp_path):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="random.txt")
            info.size = 5
            tar.addfile(info, BytesIO(b"hello"))
        buf.seek(0)
        with pytest.raises(ValueError, match="Missing backup_meta.json"):
            validate_backup(buf)

    def test_wrong_magic(self, tmp_path):
        buf = BytesIO()
        meta = json.dumps({"magic": "wrong", "format_version": 1}).encode()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name=BACKUP_META_FILE)
            info.size = len(meta)
            tar.addfile(info, BytesIO(meta))
        buf.seek(0)
        with pytest.raises(ValueError, match="wrong magic"):
            validate_backup(buf)

    def test_path_traversal_rejected(self):
        buf = BytesIO()
        meta = json.dumps({"magic": MAGIC, "format_version": 1}).encode()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name=BACKUP_META_FILE)
            info.size = len(meta)
            tar.addfile(info, BytesIO(meta))
            info2 = tarfile.TarInfo(name="../etc/passwd")
            info2.size = 4
            tar.addfile(info2, BytesIO(b"evil"))
        buf.seek(0)
        with pytest.raises(ValueError, match="Unsafe path"):
            validate_backup(buf)


# ── TestRestore ──


class TestRestore:
    def test_restores_files(self, backup_path, tmp_path):
        restore_dir = str(tmp_path / "restore")
        with backup_path.open("rb") as archive:
            result = restore_backup(archive, restore_dir)
        assert "docsis_history.db" in result["restored_files"]
        assert "config.json" in result["restored_files"]
        assert ".auth_state" in result["restored_files"]
        assert os.path.exists(os.path.join(restore_dir, "docsis_history.db"))
        assert os.path.exists(os.path.join(restore_dir, "config.json"))
        assert (tmp_path / "restore" / ".auth_state").read_bytes() == b"auth-state-fingerprint"

    def test_restored_data_correct(self, backup_path, tmp_path):
        restore_dir = str(tmp_path / "restore")
        with backup_path.open("rb") as archive:
            restore_backup(archive, restore_dir)

        # Check config
        with open(os.path.join(restore_dir, "config.json")) as f:
            config = json.load(f)
        assert config["modem_type"] == "fritzbox"

        # Check DB has non-demo data
        conn = sqlite3.connect(os.path.join(restore_dir, "docsis_history.db"))
        count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        assert count == 1  # demo row was excluded
        assert conn.execute(
            "SELECT ticket_ref FROM de_tkg_claim_drafts"
        ).fetchall() == [("SYNTHETIC-REAL",)]
        conn.close()

    def test_accepts_bytes(self, backup_path, tmp_path):
        restore_dir = str(tmp_path / "restore")
        result = restore_backup(backup_path.read_bytes(), restore_dir)
        assert len(result["restored_files"]) > 0


# ── TestListAndCleanup ──


class TestListAndCleanup:
    def test_list_empty(self, backup_dir):
        assert list_backups(backup_dir) == []

    def test_list_nonexistent_dir(self):
        assert list_backups("/nonexistent/path") == []

    def test_list_returns_sorted(self, backup_dir):
        import time
        for i in range(3):
            fname = f"docsight_backup_2026-01-0{i+1}_120000.tar.gz"
            with open(os.path.join(backup_dir, fname), "wb") as f:
                f.write(b"fake")
            time.sleep(0.01)  # ensure different mtime

        result = list_backups(backup_dir)
        assert len(result) == 3
        # Most recent first
        assert result[0]["filename"] == "docsight_backup_2026-01-03_120000.tar.gz"

    def test_list_ignores_non_backup_files(self, backup_dir):
        with open(os.path.join(backup_dir, "random.txt"), "w") as f:
            f.write("not a backup")
        assert list_backups(backup_dir) == []

    def test_cleanup_keeps_n(self, backup_dir):
        import time
        for i in range(7):
            fname = f"docsight_backup_2026-01-0{i+1}_120000.tar.gz"
            with open(os.path.join(backup_dir, fname), "wb") as f:
                f.write(b"fake")
            time.sleep(0.01)

        deleted = cleanup_old_backups(backup_dir, keep=3)
        assert deleted == 4
        remaining = list_backups(backup_dir)
        assert len(remaining) == 3

    def test_cleanup_noop_when_few(self, backup_dir):
        fname = "docsight_backup_2026-01-01_120000.tar.gz"
        with open(os.path.join(backup_dir, fname), "wb") as f:
            f.write(b"fake")
        deleted = cleanup_old_backups(backup_dir, keep=5)
        assert deleted == 0


class TestBackupCollectorConfig:
    def test_uses_configured_interval_hours_from_string(self):
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "backup_interval_hours": "168",
        }.get(key, default)

        collector = BackupCollector(mgr)

        assert collector.poll_interval_seconds == 168 * 3600

    def test_collect_casts_retention_from_string(self, monkeypatch):
        mgr = MagicMock()
        mgr.data_dir = "/data"
        mgr.get.side_effect = lambda key, default=None: {
            "backup_path": "/backup",
            "backup_retention": "5",
        }.get(key, default)

        calls = {}

        def fake_create_backup_to_file(data_dir, backup_path):
            calls["create"] = (data_dir, backup_path)
            return "docsight_backup_test.tar.gz"

        def fake_cleanup_old_backups(backup_path, keep=5):
            calls["cleanup"] = (backup_path, keep)
            return 0

        monkeypatch.setattr("app.modules.backup.backup.create_backup_to_file", fake_create_backup_to_file)
        monkeypatch.setattr("app.modules.backup.backup.cleanup_old_backups", fake_cleanup_old_backups)

        collector = BackupCollector(mgr)
        result = collector.collect()

        assert result.success is True
        assert calls["create"] == ("/data", "/backup")
        assert calls["cleanup"] == ("/backup", 5)


# ── TestBrowseDirectory ──


class TestBrowseDirectory:
    def test_browse_lists_dirs(self, tmp_path):
        root = tmp_path / "browse_root"
        root.mkdir()
        (root / "subdir1").mkdir()
        (root / "subdir2").mkdir()
        (root / "file.txt").write_text("hello")

        result = browse_directory(str(root), allowed_roots=[str(root)])
        assert "subdir1" in result["directories"]
        assert "subdir2" in result["directories"]
        assert "file.txt" not in result["directories"]

    def test_browse_hides_hidden_dirs(self, tmp_path):
        root = tmp_path / "hidden_root"
        root.mkdir()
        (root / ".hidden").mkdir()
        (root / "visible").mkdir()

        result = browse_directory(str(root), allowed_roots=[str(root)])
        assert ".hidden" not in result["directories"]
        assert "visible" in result["directories"]

    def test_browse_rejects_outside_allowed(self, tmp_path):
        root = tmp_path / "allowed"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        with pytest.raises(ValueError, match="not allowed"):
            browse_directory(str(outside), allowed_roots=[str(root)])

    def test_browse_rejects_symlink_escape(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        target = tmp_path / "secret"
        target.mkdir()
        link = root / "escape"
        link.symlink_to(target)

        # Browsing the symlink target should be rejected
        with pytest.raises(ValueError, match="not allowed"):
            browse_directory(str(link), allowed_roots=[str(root)])

    def test_browse_returns_parent(self, tmp_path):
        root = tmp_path / "root"
        sub = root / "child"
        sub.mkdir(parents=True)

        result = browse_directory(str(sub), allowed_roots=[str(root)])
        assert result["parent"] == str(root)

    def test_browse_no_parent_at_root(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        result = browse_directory(str(root), allowed_roots=[str(root)])
        assert result["parent"] is None

    def test_browse_uses_data_dir_as_default_allowed_root(self, tmp_path, monkeypatch):
        data_root = tmp_path / "desktop_data"
        nested = data_root / "exports"
        nested.mkdir(parents=True)

        monkeypatch.setenv("DATA_DIR", str(data_root))

        result = browse_directory(str(data_root))

        assert "exports" in result["directories"]
        assert result["path"] == os.path.realpath(data_root)

    def test_browse_nonexistent_dir(self, tmp_path):
        with pytest.raises(ValueError, match="Not a directory"):
            browse_directory(str(tmp_path / "nope"), allowed_roots=[str(tmp_path)])
