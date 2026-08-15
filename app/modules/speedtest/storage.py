"""Standalone speedtest result storage."""

import logging

from app.storage.migrations import run_migrations
from app.storage.sqlite import bulk_write, open_read, write_transaction
from .migrations import MIGRATIONS
from datetime import datetime, timezone

log = logging.getLogger("docsis.storage.speedtest")


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
                normalized = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
        """Bulk insert speedtest results, upserting enriched fields on conflict."""
        if not results:
            return
        try:
            bulk_write(
                self.db_path,
                    "INSERT INTO speedtest_results "
                    "(id, timestamp, download_mbps, upload_mbps, download_human, "
                    "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                    "server_id, server_name, "
                    "isp, server_host, server_location, server_country, server_ip, "
                    "ping_low, ping_high, dl_latency_iqm, dl_latency_jitter, "
                    "ul_latency_iqm, ul_latency_jitter, dl_bytes, ul_bytes, "
                    "dl_elapsed_ms, ul_elapsed_ms, external_ip, is_vpn, result_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "isp = excluded.isp, "
                    "server_host = excluded.server_host, "
                    "server_location = excluded.server_location, "
                    "server_country = excluded.server_country, "
                    "server_ip = excluded.server_ip, "
                    "ping_low = excluded.ping_low, "
                    "ping_high = excluded.ping_high, "
                    "dl_latency_iqm = excluded.dl_latency_iqm, "
                    "dl_latency_jitter = excluded.dl_latency_jitter, "
                    "ul_latency_iqm = excluded.ul_latency_iqm, "
                    "ul_latency_jitter = excluded.ul_latency_jitter, "
                    "dl_bytes = excluded.dl_bytes, "
                    "ul_bytes = excluded.ul_bytes, "
                    "dl_elapsed_ms = excluded.dl_elapsed_ms, "
                    "ul_elapsed_ms = excluded.ul_elapsed_ms, "
                    "external_ip = excluded.external_ip, "
                    "is_vpn = excluded.is_vpn, "
                    "result_url = excluded.result_url",
                    [
                        (
                            r["id"], r["timestamp"], r["download_mbps"],
                            r["upload_mbps"], r["download_human"], r["upload_human"],
                            r["ping_ms"], r["jitter_ms"], r["packet_loss_pct"],
                            r.get("server_id"), r.get("server_name", ""),
                            r.get("isp"), r.get("server_host"), r.get("server_location"),
                            r.get("server_country"), r.get("server_ip"),
                            r.get("ping_low"), r.get("ping_high"),
                            r.get("dl_latency_iqm"), r.get("dl_latency_jitter"),
                            r.get("ul_latency_iqm"), r.get("ul_latency_jitter"),
                            r.get("dl_bytes"), r.get("ul_bytes"),
                            r.get("dl_elapsed_ms"), r.get("ul_elapsed_ms"),
                            r.get("external_ip"),
                            1 if r.get("is_vpn") else (0 if r.get("is_vpn") is not None else None),
                            r.get("result_url"),
                        )
                        for r in results
                    ],
                )
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
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct, "
                "server_id, server_name, "
                "isp, server_host, server_location, server_country, server_ip, "
                "ping_low, ping_high, dl_latency_iqm, dl_latency_jitter, "
                "ul_latency_iqm, ul_latency_jitter, dl_bytes, ul_bytes, "
                "dl_elapsed_ms, ul_elapsed_ms, external_ip, is_vpn, result_url "
                "FROM speedtest_results WHERE id = ?",
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
