"""Storage mixin for device state."""

import sqlite3
from typing import Dict, Any

class DeviceStorageMixin:
    def get_device_state(self) -> Dict[str, Any]:
        """Fetch the current tracked device state."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM device_state WHERE id = 1").fetchone()
            if row:
                return dict(row)
            return {}

    def update_device_state(self, uptime: int | None, sw_version: str | None, ipv4: str | None, ipv6: str | None, updated_at: str):
        """Update the tracked device state. Inserts if missing, otherwise overwrites."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO device_state (id, uptime_seconds, sw_version, wan_ipv4, wan_ipv6, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    uptime_seconds = excluded.uptime_seconds,
                    sw_version = excluded.sw_version,
                    wan_ipv4 = excluded.wan_ipv4,
                    wan_ipv6 = excluded.wan_ipv6,
                    updated_at = excluded.updated_at
            """, (uptime, sw_version, ipv4, ipv6, updated_at))
