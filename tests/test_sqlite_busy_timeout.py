"""SQLite busy-timeout contracts for local storage connections."""

from app.modules.bqm.storage import BqmStorage
from app.storage import SnapshotStorage
from app.storage.sqlite import DEFAULT_SQLITE_BUSY_TIMEOUT_MS, connect_sqlite


def test_shared_sqlite_helper_sets_busy_timeout(tmp_path):
    with connect_sqlite(str(tmp_path / "helper.db")) as conn:
        value = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert value == DEFAULT_SQLITE_BUSY_TIMEOUT_MS


def test_core_storage_connections_set_busy_timeout(tmp_path):
    storage = SnapshotStorage(str(tmp_path / "core.db"), max_days=7)

    with storage._connect() as conn:
        value = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert value == DEFAULT_SQLITE_BUSY_TIMEOUT_MS


def test_module_storage_connections_use_shared_busy_timeout(tmp_path):
    storage = BqmStorage(str(tmp_path / "bqm.db"))

    with connect_sqlite(storage.db_path) as conn:
        value = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert value == DEFAULT_SQLITE_BUSY_TIMEOUT_MS
