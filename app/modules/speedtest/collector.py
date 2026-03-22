"""Speedtest Tracker collector -- delta-sync from external API."""

import logging

from app.collectors.base import Collector, CollectorResult
from .client import SpeedtestClient
from .storage import SpeedtestStorage

log = logging.getLogger("docsis.collector.speedtest")


class SpeedtestCollector(Collector):
    """Fetches speed test results from Speedtest Tracker and caches them locally."""

    name = "speedtest"

    def __init__(self, config_mgr, storage, web, poll_interval=300, **kwargs):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = SpeedtestStorage(storage.db_path)
        self._web = web
        self._client = None
        self._last_url = None
        self.on_import = None  # Optional callback for Smart Capture

    def is_enabled(self) -> bool:
        return self._config_mgr.is_speedtest_configured()

    def _ensure_client(self):
        """Re-initialize client if the configured URL changed."""
        url = self._config_mgr.get("speedtest_tracker_url")
        if url != self._last_url:
            token = self._config_mgr.get("speedtest_tracker_token")
            self._client = SpeedtestClient(url, token)
            self._last_url = url
            # Detect server switch and clear stale cache
            self._storage.check_source_url(url)
            log.info("Speedtest Tracker: %s", url)

    def collect(self) -> CollectorResult:
        self._ensure_client()

        # Latest result for dashboard
        results, error = self._client.get_latest_with_error(1)
        if error:
            log.warning("Speedtest fetch failed: %s", error)
            return CollectorResult.failure(self.name, f"Speedtest Tracker: {error}")
        if results:
            self._web.update_state(speedtest_latest=results[0])

        # Delta cache (isolated: failure here should not penalize the collector)
        try:
            last_id = self._storage.get_latest_speedtest_id()
            cached_count = self._storage.get_speedtest_count()
            # ID-reset detection: reuse the result already fetched above
            if cached_count > 0 and last_id > 0:
                if not error and not results:
                    # Remote reachable but empty — server was wiped
                    log.info("Remote has no results but cache has %d, clearing", cached_count)
                    self._storage.clear_cache()
                    self._web.clear_speedtest_latest()
                    cached_count = 0
                elif results and results[0].get("id", 0) < last_id:
                    log.info(
                        "Speedtest ID reset detected (cache=%d, remote=%d), rebuilding",
                        last_id, results[0].get("id", 0),
                    )
                    self._storage.clear_cache()
                    cached_count = 0
            is_backfill = cached_count < 50
            if is_backfill:
                new_results = self._client.get_results(per_page=2000)
            else:
                new_results = self._client.get_newer_than(last_id)
            if new_results:
                genuinely_new = [r for r in new_results if r.get("id", 0) > last_id]
                self._storage.save_speedtest_results(new_results)
                log.info(
                    "Cached %d new speedtest results (total: %d)",
                    len(new_results),
                    cached_count + len(new_results),
                )
                # Skip on_import during initial backfill to avoid matching
                # historical results to fresh FIRED executions
                if genuinely_new and self.on_import and not is_backfill:
                    self.on_import(genuinely_new)
        except Exception as e:
            log.warning("Speedtest delta cache failed: %s", e)

        return CollectorResult(source=self.name)
