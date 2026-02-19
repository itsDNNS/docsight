"""Tests for backup and restore functionality."""

import json
import os
import sqlite3
import tarfile

import pytest
from io import BytesIO

from app.backup import (
    BACKUP_META_FILE,
    FORMAT_VERSION,
    MAGIC,
    browse_directory,
    cleanup_old_backups,
    create_backup,
    create_backup_to_file,
    list_backups,
    restore_backup,
    validate_backup,
)


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
    conn.commit()
    conn.close()

    # Create config files
    config = {"modem_type": "fritzbox", "poll_interval": 900}
    (d / "config.json").write_text(json.dumps(config))
    (d / ".config_key").write_bytes(b"test-key-data")
    (d / ".session_key").write_bytes(b"session-secret")

    return str(d)


@pytest.fixture
def backup_dir(tmp_path):
    """Create an empty backup directory."""
    d = tmp_path / "backups"
    d.mkdir()
    return str(d)


# ── TestCreateBackup ──


class TestCreateBackup:
    def test_creates_valid_archive(self, data_dir):
        buf = create_backup(data_dir)
        assert buf.tell() == 0  # seek(0) was called
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()
            assert BACKUP_META_FILE in names
            assert "docsis_history.db" in names
            assert "config.json" in names
            assert ".config_key" in names
            assert ".session_key" in names

    def test_meta_has_required_fields(self, data_dir):
        buf = create_backup(data_dir)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            meta = json.loads(tar.extractfile(BACKUP_META_FILE).read())
            assert meta["magic"] == MAGIC
            assert meta["format_version"] == FORMAT_VERSION
            assert "timestamp" in meta
            assert "app_version" in meta
            assert "tables" in meta

    def test_demo_data_excluded(self, data_dir):
        buf = create_backup(data_dir)
        # Extract the DB from the archive and check demo data is gone
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
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
            conn.close()
        finally:
            os.unlink(tmp_path)

    def test_handles_missing_db(self, tmp_path):
        """Backup should work even without a database file."""
        d = tmp_path / "empty_data"
        d.mkdir()
        (d / "config.json").write_text("{}")
        buf = create_backup(str(d))
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()
            assert "docsis_history.db" not in names
            assert BACKUP_META_FILE in names

    def test_create_to_file(self, data_dir, backup_dir):
        filename = create_backup_to_file(data_dir, backup_dir)
        assert filename.startswith("docsight_backup_")
        assert filename.endswith(".tar.gz")
        assert os.path.exists(os.path.join(backup_dir, filename))


# ── TestValidateBackup ──


class TestValidateBackup:
    def test_valid_backup(self, data_dir):
        buf = create_backup(data_dir)
        meta = validate_backup(buf)
        assert meta["magic"] == MAGIC
        assert meta["has_database"] is True
        assert meta["has_config"] is True
        assert "files" in meta

    def test_accepts_bytes(self, data_dir):
        buf = create_backup(data_dir)
        meta = validate_backup(buf.read())
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
    def test_restores_files(self, data_dir, tmp_path):
        buf = create_backup(data_dir)
        restore_dir = str(tmp_path / "restore")
        result = restore_backup(buf, restore_dir)
        assert "docsis_history.db" in result["restored_files"]
        assert "config.json" in result["restored_files"]
        assert os.path.exists(os.path.join(restore_dir, "docsis_history.db"))
        assert os.path.exists(os.path.join(restore_dir, "config.json"))

    def test_restored_data_correct(self, data_dir, tmp_path):
        buf = create_backup(data_dir)
        restore_dir = str(tmp_path / "restore")
        restore_backup(buf, restore_dir)

        # Check config
        with open(os.path.join(restore_dir, "config.json")) as f:
            config = json.load(f)
        assert config["modem_type"] == "fritzbox"

        # Check DB has non-demo data
        conn = sqlite3.connect(os.path.join(restore_dir, "docsis_history.db"))
        count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        assert count == 1  # demo row was excluded
        conn.close()

    def test_accepts_bytes(self, data_dir, tmp_path):
        buf = create_backup(data_dir)
        restore_dir = str(tmp_path / "restore")
        result = restore_backup(buf.read(), restore_dir)
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

    def test_browse_nonexistent_dir(self, tmp_path):
        with pytest.raises(ValueError, match="Not a directory"):
            browse_directory(str(tmp_path / "nope"), allowed_roots=[str(tmp_path)])
