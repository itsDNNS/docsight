"""Speedtest Tracker collector — delta-sync from external API."""

import logging

from .base import Collector, CollectorResult
from ..speedtest import SpeedtestClient

log = logging.getLogger("docsis.collector.speedtest")


class SpeedtestCollector(Collector):
    """Fetches speed test results from Speedtest Tracker and caches them locally."""

    name = "speedtest"

    def __init__(self, config_mgr, storage, web, poll_interval=300):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = storage
        self._web = web
        self._client = None
        self._last_url = None

    def is_enabled(self) -> bool:
        return self._config_mgr.is_speedtest_configured()

    def _ensure_client(self):
        """Re-initialize client if the configured URL changed."""
        url = self._config_mgr.get("speedtest_tracker_url")
        if url != self._last_url:
            token = self._config_mgr.get("speedtest_tracker_token")
            self._client = SpeedtestClient(url, token)
            self._last_url = url
            log.info("Speedtest Tracker: %s", url)

    def collect(self) -> CollectorResult:
        self._ensure_client()

        # Latest result for dashboard
        results = self._client.get_latest(1)
        if results:
            self._web.update_state(speedtest_latest=results[0])

        # Delta cache (isolated: failure here should not penalize the collector)
        try:
            last_id = self._storage.get_latest_speedtest_id()
            cached_count = self._storage.get_speedtest_count()
            if cached_count < 50:
                new_results = self._client.get_results(per_page=2000)
            else:
                new_results = self._client.get_newer_than(last_id)
            if new_results:
                self._storage.save_speedtest_results(new_results)
                log.info(
                    "Cached %d new speedtest results (total: %d)",
                    len(new_results),
                    cached_count + len(new_results),
                )
        except Exception as e:
            log.warning("Speedtest delta cache failed: %s", e)

        return CollectorResult(source=self.name)
