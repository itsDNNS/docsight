"""Shared SQLite connection helpers."""

import sqlite3
from typing import Any

DEFAULT_SQLITE_TIMEOUT_SECONDS = 30
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 30_000


def connect_sqlite(db_path: str, **kwargs: Any) -> sqlite3.Connection:
    """Open a SQLite connection with DOCSight's local-write busy timeout."""
    kwargs.setdefault("timeout", DEFAULT_SQLITE_TIMEOUT_SECONDS)
    conn = sqlite3.connect(db_path, **kwargs)
    conn.execute(f"PRAGMA busy_timeout={DEFAULT_SQLITE_BUSY_TIMEOUT_MS}")
    return conn
