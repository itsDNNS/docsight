"""Storage mixin for device state."""

from typing import Dict, Any

class DeviceStorageMethods:
    def get_device_state(self) -> Dict[str, Any]:
        """Fetch the current tracked device state."""
        with self._read() as conn:
            row = conn.execute("SELECT * FROM device_state WHERE id = 1").fetchone()
            if row:
                return dict(row)
            return {}

    def update_device_state(self, uptime: int | None, sw_version: str | None, ipv4: str | None, ipv6: str | None, updated_at: str):
        """Update the tracked device state. Inserts if missing, otherwise overwrites."""
        with self._write() as conn:
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
