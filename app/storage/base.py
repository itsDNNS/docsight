"""Storage base class with managed SQLite access."""

import os

from .migrations import CORE_MIGRATIONS, SCHEMA_VERSION, run_migrations
from .sqlite import open_read, write_transaction


ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf", "text/plain",
}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_ENTRY = 10


class StorageBase:
    """Persist DOCSIS analysis snapshots to SQLite."""

    def __init__(self, db_path, max_days=7):
        self.db_path = db_path
        self.max_days = max_days
        self.tz_name = ""
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        run_migrations(self.db_path, CORE_MIGRATIONS)

    def _read(self):
        return open_read(self.db_path)

    def _write(self):
        return write_transaction(self.db_path)
