"""Standalone speedtest result storage."""

import logging

from app.storage.migrations import run_migrations
from app.storage.sqlite import bulk_write, open_read, write_transaction
from .migrations import MIGRATIONS
from datetime import datetime, timezone
from app.tz import UTC_FMT

log = logging.getLogger("docsis.storage.speedtest")

_COLUMNS = (
    "id", "timestamp", "download_mbps", "upload_mbps", "download_human",
    "upload_human", "ping_ms", "jitter_ms", "packet_loss_pct",
    "server_id", "server_name",
    "isp", "server_host", "server_location", "server_country", "server_ip",
    "ping_low", "ping_high", "dl_latency_iqm", "dl_latency_jitter",
    "ul_latency_iqm", "ul_latency_jitter", "dl_bytes", "ul_bytes",
    "dl_elapsed_ms", "ul_elapsed_ms", "external_ip", "is_vpn", "result_url",
)
# A new result without these (a failed test) is stored as before; a known id keeps what a result omits
_INSERT_DEFAULTS = {
    "download_mbps": "0", "upload_mbps": "0", "download_human": "''", "upload_human": "''", "server_name": "''",
}
_UPSERT = (
    f"INSERT INTO speedtest_results ({', '.join(_COLUMNS)}) VALUES ("
    + ", ".join(f"COALESCE(?{n}, {_INSERT_DEFAULTS[c]})" if c in _INSERT_DEFAULTS else f"?{n}"
                for n, c in enumerate(_COLUMNS, 1))
    + ") ON CONFLICT(id) DO UPDATE SET "
    + ", ".join(f"{c} = COALESCE(?{n}, {c})" for n, c in enumerate(_COLUMNS, 1) if c != "id")
)


class SpeedtestStorage:
    """Standalone speedtest data storage (not a mixin).

    Creates the speedtest_results table if it doesn't exist.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """Create and migrate the speedtest tables."""
        run_migrations(self.db_path, MIGRATIONS)
        self._migrate_timestamps()

    def _migrate_timestamps(self):
        """Normalize offset-bearing timestamps once, preserving existing behavior."""
        with write_transaction(self.db_path) as conn:
            migrated = conn.execute(
                "SELECT value FROM speedtest_meta WHERE key = 'ts_migrated'"
            ).fetchone()
            if migrated:
                return
            rows = conn.execute(
                "SELECT id, timestamp FROM speedtest_results "
                "WHERE timestamp GLOB '*[+-][0-9][0-9]:[0-9][0-9]'"
            ).fetchall()
            updated = 0
            for row_id, timestamp in rows:
                try:
                    parsed = datetime.fromisoformat(timestamp)
                except (ValueError, TypeError):
                    continue
                if parsed.tzinfo is None:
                    continue
                normalized = parsed.astimezone(timezone.utc).strftime(UTC_FMT)
                conn.execute(
                    "UPDATE speedtest_results SET timestamp = ? WHERE id = ?",
                    (normalized, row_id),
                )
                updated += 1
            conn.execute(
                "INSERT OR REPLACE INTO speedtest_meta (key, value) VALUES ('ts_migrated', '1')"
            )
            if updated:
                log.info("Normalized %d existing timestamps to UTC", updated)

    def save_speedtest_results(self, results):
        """Bulk upsert speedtest results; a known id keeps the values a result omits."""
        if not results:
            return
        try:
            bulk_write(self.db_path, _UPSERT, [tuple(r.get(column) for column in _COLUMNS) for r in results])
            log.debug("Saved %d speedtest results", len(results))
        except Exception as e:
            log.error("Failed to save speedtest results: %s", e)

    def get_speedtest_results(self, limit=2000):
        """Return cached speedtest results, newest first."""
        with open_read(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                "server_id, server_name "
                "FROM speedtest_results ORDER BY timestamp DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_speedtest_by_id(self, result_id):
        """Return a single speedtest result by id, or None (includes enriched fields)."""
        with open_read(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM speedtest_results WHERE id = ?",
                (result_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_speedtest_count(self):
        """Return number of cached speedtest results."""
        with open_read(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM speedtest_results").fetchone()
        return row[0] if row else 0

    def get_latest_speedtest_id(self):
        """Return the highest speedtest result id, or 0 if none."""
        with open_read(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(id) FROM speedtest_results"
            ).fetchone()
        return row[0] or 0 if row else 0

    def get_recent_ids(self, limit=10):
        """Ids of the newest cached results, for a delta sync to recheck the ids between them."""
        with open_read(self.db_path) as conn:
            rows = conn.execute("SELECT id FROM speedtest_results ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {row[0] for row in rows}

    def get_recent_speedtests(self, limit=10):
        """Return the N most recent speedtest results."""
        return self.get_speedtest_results(limit=limit)

    def get_meta(self, key):
        """Return a metadata value, or None."""
        with open_read(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM speedtest_meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        """Set a metadata value (upsert)."""
        with write_transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO speedtest_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    @staticmethod
    def _normalize_url(url):
        """Normalize URL for comparison (strip trailing slash, lowercase scheme/host)."""
        if not url:
            return url
        url = url.strip().rstrip("/")
        # Lowercase scheme and host portion
        if "://" in url:
            scheme, rest = url.split("://", 1)
            if "/" in rest:
                host, path = rest.split("/", 1)
                url = f"{scheme.lower()}://{host.lower()}/{path}"
            else:
                url = f"{scheme.lower()}://{rest.lower()}"
        return url

    def check_source_url(self, url):
        """Check if the tracker URL changed. If so, clear the cache and update.

        Returns True if cache was cleared (server switch detected).
        """
        if not url:
            return False
        url = self._normalize_url(url)
        stored = self._normalize_url(self.get_meta("source_url"))
        if stored and stored != url:
            log.info(
                "Speedtest Tracker URL changed (%s -> %s), clearing cache",
                stored, url,
            )
            self.clear_cache()
            self.set_meta("source_url", url)
            return True
        if not stored:
            self.set_meta("source_url", url)
        return False

    def clear_cache(self):
        """Delete all cached speedtest results (non-demo)."""
        with write_transaction(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM speedtest_results WHERE is_demo = 0"
            ).fetchone()[0]
            conn.execute("DELETE FROM speedtest_results WHERE is_demo = 0")
        log.info("Cleared %d cached speedtest results", count)
        return count

    def get_speedtest_in_range(self, start_ts, end_ts):
        """Return speedtest results within a time range, oldest first."""
        with open_read(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct "
                "FROM speedtest_results "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]
