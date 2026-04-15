"""Standalone speedtest result storage."""

import logging
import sqlite3
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
        """Create the speedtest_results and speedtest_meta tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS speedtest_results ("
                "  id INTEGER PRIMARY KEY,"
                "  timestamp TEXT NOT NULL,"
                "  download_mbps REAL,"
                "  upload_mbps REAL,"
                "  download_human TEXT,"
                "  upload_human TEXT,"
                "  ping_ms REAL,"
                "  jitter_ms REAL,"
                "  packet_loss_pct REAL,"
                "  server_id INTEGER,"
                "  server_name TEXT,"
                "  is_demo INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_speedtest_ts "
                "ON speedtest_results(timestamp)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS speedtest_meta ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT"
                ")"
            )
            # Migration: add server_id/server_name columns if missing
            try:
                conn.execute("ALTER TABLE speedtest_results ADD COLUMN server_id INTEGER")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE speedtest_results ADD COLUMN server_name TEXT")
            except Exception:
                pass
            # Migration: add is_demo column if missing
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(speedtest_results)").fetchall()]
                if "is_demo" not in cols:
                    conn.execute("ALTER TABLE speedtest_results ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            # Migration: add enriched detail columns if missing
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(speedtest_results)").fetchall()]
                enriched_cols = [
                    ("isp", "TEXT"),
                    ("server_host", "TEXT"),
                    ("server_location", "TEXT"),
                    ("server_country", "TEXT"),
                    ("server_ip", "TEXT"),
                    ("ping_low", "REAL"),
                    ("ping_high", "REAL"),
                    ("dl_latency_iqm", "REAL"),
                    ("dl_latency_jitter", "REAL"),
                    ("ul_latency_iqm", "REAL"),
                    ("ul_latency_jitter", "REAL"),
                    ("dl_bytes", "INTEGER"),
                    ("ul_bytes", "INTEGER"),
                    ("dl_elapsed_ms", "INTEGER"),
                    ("ul_elapsed_ms", "INTEGER"),
                    ("external_ip", "TEXT"),
                    ("is_vpn", "INTEGER"),
                    ("result_url", "TEXT"),
                ]
                for col_name, col_type in enriched_cols:
                    if col_name not in cols:
                        conn.execute(
                            f"ALTER TABLE speedtest_results ADD COLUMN {col_name} {col_type}"
                        )
            except Exception:
                pass
            # One-time migration: normalize offset-bearing timestamps to UTC Z-suffix.
            # Only runs once, tracked via speedtest_meta to avoid repeated scans.
            try:
                migrated = conn.execute(
                    "SELECT value FROM speedtest_meta WHERE key = 'ts_migrated'"
                ).fetchone()
                if not migrated:
                    # Match only timestamps with explicit +HH:MM or -HH:MM offset
                    # (not plain ISO like 2026-03-21T12:34:56 or ...Z)
                    rows = conn.execute(
                        "SELECT id, timestamp FROM speedtest_results "
                        "WHERE timestamp GLOB '*[+-][0-9][0-9]:[0-9][0-9]'"
                    ).fetchall()
                    if rows:
                        updates = []
                        for row_id, ts in rows:
                            try:
                                dt = datetime.fromisoformat(ts)
                                if dt.tzinfo is not None:
                                    dt = dt.astimezone(timezone.utc)
                                    updates.append((dt.strftime("%Y-%m-%dT%H:%M:%SZ"), row_id))
                            except (ValueError, TypeError):
                                pass
                        if updates:
                            conn.executemany(
                                "UPDATE speedtest_results SET timestamp = ? WHERE id = ?",
                                updates,
                            )
                            log.info("Normalized %d existing timestamps to UTC", len(updates))
                    conn.execute(
                        "INSERT OR REPLACE INTO speedtest_meta (key, value) VALUES ('ts_migrated', '1')"
                    )
            except Exception:
                pass

    def save_speedtest_results(self, results):
        """Bulk insert speedtest results, upserting enriched fields on conflict."""
        if not results:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
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
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
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
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
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
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM speedtest_results").fetchone()
        return row[0] if row else 0

    def get_latest_speedtest_id(self):
        """Return the highest speedtest result id, or 0 if none."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(id) FROM speedtest_results"
            ).fetchone()
        return row[0] or 0 if row else 0

    def get_recent_speedtests(self, limit=10):
        """Return the N most recent speedtest results."""
        return self.get_speedtest_results(limit=limit)

    def get_meta(self, key):
        """Return a metadata value, or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM speedtest_meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        """Set a metadata value (upsert)."""
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM speedtest_results WHERE is_demo = 0"
            ).fetchone()[0]
            conn.execute("DELETE FROM speedtest_results WHERE is_demo = 0")
        log.info("Cleared %d cached speedtest results", count)
        return count

    def get_speedtest_in_range(self, start_ts, end_ts):
        """Return speedtest results within a time range, oldest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, download_mbps, upload_mbps, download_human, "
                "upload_human, ping_ms, jitter_ms, packet_loss_pct "
                "FROM speedtest_results "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]
