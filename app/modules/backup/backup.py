"""Backup and restore for DOCSight data.

Creates tar.gz archives containing the SQLite database (via VACUUM INTO
for consistency), config files, and encryption keys.  No Flask dependency.
"""

import json
import logging
import os
import shutil
import sqlite3

from app.storage.sqlite import (
    consistent_copy,
    open_readonly,
    verify_database,
    write_transaction,
)
import tarfile
import tempfile
from datetime import datetime, timezone
from io import BytesIO

log = logging.getLogger("docsis.backup")

# Files under data_dir to include in backups
DATA_FILES = [
    "docsis_history.db", "connection_monitor.db",
    "config.json", ".config_key", ".session_key", ".auth_state",
]

BACKUP_META_FILE = "backup_meta.json"
FORMAT_VERSION = 1
MAGIC = "docsight-backup"


def _get_app_version():
    """Read app version (best-effort)."""
    for vpath in ("/app/VERSION", os.path.join(os.path.dirname(__file__), "..", "VERSION")):
        try:
            with open(vpath) as f:
                v = f.read().strip()
                if v:
                    return v
        except FileNotFoundError:
            pass
    return "dev"


def _get_table_counts(db_path):
    """Return {table_name: row_count} for all user tables."""
    counts = {}
    try:
        with open_readonly(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            for table in tables:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM [{table}]"  # noqa: S608
                ).fetchone()[0]
    except Exception as e:
        log.warning("Could not read table counts: %s", e)
    return counts


def _vacuum_db(data_dir, db_name, dest_path):
    """Create a consistent copy of a database using VACUUM INTO.

    Also removes demo data (is_demo=1) from the copy when applicable.
    """
    src = os.path.join(data_dir, db_name)
    if not os.path.exists(src):
        return False

    consistent_copy(src, dest_path)

    # Remove demo data from copy (only relevant for main DB)
    if db_name == "docsis_history.db":
        demo_tables = [
            "snapshots", "events", "journal_entries", "incidents",
            "speedtest_results", "bqm_graphs", "bnetz_measurements",
        ]
        with write_transaction(dest_path) as conn:
            for table in demo_tables:
                try:
                    conn.execute(
                        f"DELETE FROM [{table}] WHERE is_demo = 1"  # noqa: S608
                    )
                except sqlite3.OperationalError:
                    pass  # table may not exist or lack is_demo column
    return True


def _write_backup_archive(data_dir, archive_target, work_dir=None):
    """Write a backup archive to a path or binary file object."""
    db_files = {"docsis_history.db", "connection_monitor.db"}
    if work_dir is None:
        work_dir = data_dir

    with tempfile.TemporaryDirectory(
        prefix=".docsight-backup-work-", dir=work_dir
    ) as tmp:
        # Vacuum all databases for consistent copies
        vacuumed = {}
        for db_name in db_files:
            db_copy = os.path.join(tmp, db_name)
            vacuumed[db_name] = _vacuum_db(data_dir, db_name, db_copy)

        main_copy = os.path.join(tmp, "docsis_history.db")
        meta = {
            "magic": MAGIC,
            "format_version": FORMAT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "app_version": _get_app_version(),
            "tables": _get_table_counts(main_copy) if vacuumed.get("docsis_history.db") else {},
        }
        meta_path = os.path.join(tmp, BACKUP_META_FILE)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        if isinstance(archive_target, (str, bytes, os.PathLike)):
            tar_context = tarfile.open(name=archive_target, mode="w:gz")
        else:
            tar_context = tarfile.open(fileobj=archive_target, mode="w:gz")

        with tar_context as tar:
            tar.add(meta_path, arcname=BACKUP_META_FILE)
            for db_name, has_db in vacuumed.items():
                if has_db:
                    tar.add(os.path.join(tmp, db_name), arcname=db_name)
            for fname in DATA_FILES:
                if fname in db_files:
                    continue  # already added via vacuum copy
                fpath = os.path.join(data_dir, fname)
                if os.path.exists(fpath):
                    tar.add(fpath, arcname=fname)


def create_backup_to_file(data_dir, dest_dir):
    """Create a backup and atomically publish it in dest_dir.

    Returns:
        Filename of the created backup.
    """
    os.makedirs(dest_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"docsight_backup_{ts}.tar.gz"
    dest_path = os.path.join(dest_dir, filename)

    temp_fd, temp_path = tempfile.mkstemp(
        prefix=f".{filename}.", suffix=".tmp", dir=dest_dir
    )
    try:
        os.close(temp_fd)
        temp_fd = None
        _write_backup_archive(data_dir, temp_path, work_dir=data_dir)
        os.replace(temp_path, dest_path)
        temp_path = None
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass

    log.info("Backup saved to %s", dest_path)
    return filename


def validate_backup(archive_bytes):
    """Validate a backup archive and return metadata.

    Args:
        archive_bytes: bytes or BytesIO of the archive.

    Returns:
        dict with meta info or raises ValueError.
    """
    if isinstance(archive_bytes, (bytes, bytearray)):
        archive_bytes = BytesIO(archive_bytes)

    try:
        with tarfile.open(fileobj=archive_bytes, mode="r:gz") as tar:
            # Security: check for path traversal
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise ValueError(f"Unsafe path in archive: {member.name}")

            names = tar.getnames()
            if BACKUP_META_FILE not in names:
                raise ValueError("Missing backup_meta.json - not a valid DOCSight backup")

            meta_file = tar.extractfile(BACKUP_META_FILE)
            if meta_file is None:
                raise ValueError("Cannot read backup_meta.json")

            meta = json.loads(meta_file.read().decode("utf-8"))
            if meta.get("magic") != MAGIC:
                raise ValueError("Invalid backup: wrong magic value")

            meta["files"] = names
            meta["has_database"] = "docsis_history.db" in names
            meta["has_config"] = "config.json" in names
            return meta

    except tarfile.TarError as e:
        raise ValueError(f"Invalid archive: {e}") from e


def restore_backup(archive_bytes, data_dir):
    """Restore a backup archive to data_dir.

    Args:
        archive_bytes: bytes or BytesIO of the archive.
        data_dir: target directory (e.g. /data).

    Returns:
        dict with restore results.
    """
    if isinstance(archive_bytes, (bytes, bytearray)):
        archive_bytes = BytesIO(archive_bytes)

    meta = validate_backup(archive_bytes)
    archive_bytes.seek(0)

    if meta.get("format_version", 0) > FORMAT_VERSION:
        log.warning(
            "Backup format_version %d is newer than supported %d - attempting restore anyway",
            meta["format_version"], FORMAT_VERSION,
        )

    os.makedirs(data_dir, exist_ok=True)
    restored_files = []
    database_names = {"docsis_history.db", "connection_monitor.db"}
    staged = {}

    try:
        with tarfile.open(fileobj=archive_bytes, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name == BACKUP_META_FILE:
                    continue
                if member.name not in DATA_FILES:
                    log.warning("Skipping unknown file in backup: %s", member.name)
                    continue
                source = tar.extractfile(member)
                if source is None:
                    continue

                fd, staged_path = tempfile.mkstemp(
                    prefix=f".docsight-restore-{member.name}.",
                    suffix=".tmp",
                    dir=data_dir,
                )
                try:
                    with os.fdopen(fd, "wb") as destination:
                        shutil.copyfileobj(source, destination)
                except BaseException:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    try:
                        os.remove(staged_path)
                    except FileNotFoundError:
                        pass
                    raise
                staged[member.name] = staged_path

        for name, staged_path in staged.items():
            if name not in database_names:
                continue
            try:
                integrity = verify_database(staged_path)
            except sqlite3.DatabaseError as exc:
                raise ValueError(f"Restored database failed verification: {name}") from exc
            if integrity.lower() != "ok":
                raise ValueError(
                    f"Restored database failed integrity check: {name}: {integrity}"
                )

        for name, staged_path in staged.items():
            destination = os.path.join(data_dir, name)
            os.replace(staged_path, destination)
            staged[name] = None
            if name in database_names:
                for suffix in ("-wal", "-shm"):
                    try:
                        os.remove(destination + suffix)
                    except FileNotFoundError:
                        pass
            restored_files.append(name)
    finally:
        for staged_path in staged.values():
            if staged_path is None:
                continue
            try:
                os.remove(staged_path)
            except FileNotFoundError:
                pass

    log.info("Restored %d files to %s", len(restored_files), data_dir)
    return {
        "restored_files": restored_files,
        "meta": meta,
    }


def list_backups(backup_dir):
    """List backup files in a directory.

    Returns:
        List of dicts with filename, size, modified timestamp.
    """
    if not os.path.isdir(backup_dir):
        return []

    backups = []
    for fname in os.listdir(backup_dir):
        if not fname.startswith("docsight_backup_") or not fname.endswith(".tar.gz"):
            continue
        fpath = os.path.join(backup_dir, fname)
        if not os.path.isfile(fpath):
            continue
        stat = os.stat(fpath)
        backups.append({
            "filename": fname,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })

    backups.sort(key=lambda b: b["modified"], reverse=True)
    return backups


def cleanup_old_backups(backup_dir, keep=5):
    """Delete old backups, keeping the newest `keep` files.

    Returns:
        Number of deleted files.
    """
    backups = list_backups(backup_dir)
    if len(backups) <= keep:
        return 0

    deleted = 0
    for backup in backups[keep:]:
        fpath = os.path.join(backup_dir, backup["filename"])
        try:
            os.remove(fpath)
            deleted += 1
            log.info("Deleted old backup: %s", backup["filename"])
        except OSError as e:
            log.warning("Failed to delete old backup %s: %s", backup["filename"], e)

    return deleted


def browse_directory(path, allowed_roots=None):
    """Browse a server-side directory for the path picker.

    Args:
        path: directory path to browse.
        allowed_roots: list of allowed root paths (default: ["/backup", "/data"]).

    Returns:
        dict with current path, parent, and list of subdirectories.

    Raises:
        ValueError if path is outside allowed roots or not accessible.
    """
    if allowed_roots is None:
        allowed_roots = ["/backup", "/data"]
        data_dir = os.environ.get("DATA_DIR")
        if data_dir:
            allowed_roots.append(data_dir)

    real_path = os.path.realpath(path)

    # Security: ensure path is within allowed roots
    allowed = False
    for root in allowed_roots:
        real_root = os.path.realpath(root)
        if real_path == real_root or real_path.startswith(real_root + os.sep):
            allowed = True
            break

    if not allowed:
        raise ValueError(f"Path not allowed: {path}")

    if not os.path.isdir(real_path):
        raise ValueError(f"Not a directory: {path}")

    dirs = []
    try:
        for entry in sorted(os.listdir(real_path)):
            # Skip hidden directories
            if entry.startswith("."):
                continue
            full = os.path.join(real_path, entry)
            if os.path.isdir(full):
                dirs.append(entry)
    except PermissionError:
        raise ValueError(f"Permission denied: {path}")

    # Determine parent (only if within allowed roots)
    parent = None
    parent_path = os.path.dirname(real_path)
    for root in allowed_roots:
        real_root = os.path.realpath(root)
        if parent_path == real_root or parent_path.startswith(real_root + os.sep):
            parent = parent_path
            break

    return {
        "path": real_path,
        "parent": parent,
        "directories": dirs,
    }
