"""Single owner for SQLite connection policy and transaction boundaries.

Production callers use the managed context managers below.  ``connect_sqlite``
remains the compatibility seam for external modules and intentionally keeps its
original timeout, busy-timeout, and tuple-row behavior.
"""

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
import sqlite3
from pathlib import Path
import threading
from typing import Any

DEFAULT_SQLITE_TIMEOUT_SECONDS = 30
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 30_000


def connect_sqlite(db_path: str, **kwargs: Any) -> sqlite3.Connection:
    """Open a SQLite connection with DOCSight's local-write busy timeout."""
    kwargs.setdefault("timeout", DEFAULT_SQLITE_TIMEOUT_SECONDS)
    conn = sqlite3.connect(db_path, **kwargs)
    conn.execute(f"PRAGMA busy_timeout={DEFAULT_SQLITE_BUSY_TIMEOUT_MS}")
    return conn


_transaction_state = threading.local()


def _managed_timeout(timeout: float | None) -> tuple[float, int]:
    seconds = DEFAULT_SQLITE_TIMEOUT_SECONDS if timeout is None else timeout
    return seconds, max(0, int(seconds * 1000))


def _apply_common_policy(conn: sqlite3.Connection, busy_timeout_ms: int) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    conn.execute("PRAGMA foreign_keys=ON")


@contextmanager
def open_read(
    db_path: str, *, timeout: float | None = None
) -> Iterator[sqlite3.Connection]:
    """Yield a query-only managed connection and always close it."""
    seconds, busy_timeout_ms = _managed_timeout(timeout)
    conn = connect_sqlite(db_path, timeout=seconds, autocommit=True)
    try:
        _apply_common_policy(conn, busy_timeout_ms)
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


@contextmanager
def open_readonly(
    db_path: str, *, timeout: float = DEFAULT_SQLITE_TIMEOUT_SECONDS
) -> Iterator[sqlite3.Connection]:
    """Open an existing database through SQLite's true read-only URI mode."""
    uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout, autocommit=True)
    try:
        _apply_common_policy(conn, max(0, int(timeout * 1000)))
        yield conn
    finally:
        conn.close()


@contextmanager
def write_transaction(
    db_path: str, *, timeout: float | None = None
) -> Iterator[sqlite3.Connection]:
    """Run one immediate transaction with explicit commit/rollback ownership."""
    resolved_path = str(Path(db_path).expanduser().resolve())
    active_paths = getattr(_transaction_state, "active_paths", None)
    if active_paths:
        raise RuntimeError(f"nested write_transaction on {resolved_path}")
    if active_paths is None:
        active_paths = set()
        _transaction_state.active_paths = active_paths
    active_paths.add(resolved_path)

    conn = None
    try:
        seconds, busy_timeout_ms = _managed_timeout(timeout)
        # Explicit BEGIN/commit ownership requires legacy transaction control
        # with implicit transactions disabled.  In sqlite3, commit() is a no-op
        # when autocommit=True, even after an explicit BEGIN.
        conn = connect_sqlite(
            db_path,
            timeout=seconds,
            autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
            isolation_level=None,
        )
        _apply_common_policy(conn, busy_timeout_ms)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            try:
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
    finally:
        active_paths.discard(resolved_path)
        if conn is not None:
            conn.close()


def bulk_write(
    db_path: str,
    sql: str,
    rows: Iterable[Sequence[Any]],
    *,
    chunk_size: int = 0,
) -> int:
    """Execute materialized rows atomically and return affected-row count."""
    materialized = list(rows)
    if not materialized:
        return 0

    total = 0
    with write_transaction(db_path) as conn:
        if chunk_size > 0:
            chunks = (
                materialized[offset:offset + chunk_size]
                for offset in range(0, len(materialized), chunk_size)
            )
        else:
            chunks = (materialized,)
        for chunk in chunks:
            cursor = conn.executemany(sql, chunk)
            total += cursor.rowcount
    return total


def consistent_copy(src_db_path: str, dest_path: str) -> None:
    """Create a consistent SQLite copy using a parameterized VACUUM INTO."""
    conn = connect_sqlite(src_db_path, autocommit=True)
    try:
        conn.execute("VACUUM INTO ?", (dest_path,))
    finally:
        conn.close()


def verify_database(db_path: str) -> str:
    """Return the result of SQLite's full integrity check."""
    with open_readonly(db_path) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else ""
