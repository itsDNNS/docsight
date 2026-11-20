"""Speedtest Tracker collector -- delta-sync from external API."""

import logging
import threading

from app.collectors.base import Collector, CollectorResult
from app.config import parse_config_bool

from .client import SpeedtestClient
from .storage import SpeedtestStorage

log = logging.getLogger("docsis.collector.speedtest")


_SYNC_LOCK = threading.Lock()  # one sync at a time, so an older Tracker answer is never taken for a reset


def _cache_new_results(storage, client, on_import):
    """Cache new finished results and pass each newly cached one to on_import once.

    Returns the error of the first request.
    """
    try:
        storage.check_source_url(client.base_url)  # a different server clears the cache
        latest, error = client.get_latest_with_error(1)
        if error:
            return error
        cached_count = storage.get_speedtest_count()
        last_id = storage.get_latest_speedtest_id()
        if cached_count and (not latest or latest[0].get("id", 0) < last_id):
            log.info("Speedtest Tracker is empty or its ids restarted (cache max=%d), rebuilding", last_id)
            storage.clear_cache()
            cached_count = 0
        # Older versions cached running tests as failed, so a filled cache is reread once completely
        reread_done = storage.get_meta("running_rows_reread")
        fetched, failed = (client.get_results_with_error(per_page=2000) if cached_count < 50 or not reread_done
                           else (client.get_newer_than(*storage.get_recent_ids()), None))
        new_results = storage.save_speedtest_results(fetched)
        if new_results:
            log.info("Cached %d new speedtest results", len(new_results))
        if new_results and on_import and cached_count:  # an empty cache is filled with past results
            on_import(new_results)
        if not (reread_done or failed):
            storage.set_meta("running_rows_reread", "1")
    except Exception as e:
        log.warning("Speedtest sync failed: %s", e)
    return None


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
        self._last_tls_insecure = None
        self.on_import = None  # Optional callback for Smart Capture

    def is_enabled(self) -> bool:
        return self._config_mgr.is_speedtest_configured()

    def _ensure_client(self):
        """Re-initialize client if the configured URL changed."""
        url = self._config_mgr.get("speedtest_tracker_url")
        tls_insecure = parse_config_bool(
            self._config_mgr.get("speedtest_tls_insecure", False)
        )
        if url != self._last_url or tls_insecure != self._last_tls_insecure:
            token = self._config_mgr.get("speedtest_tracker_token")
            self._client = SpeedtestClient(url, token, tls_insecure=tls_insecure)
            self._last_url = url
            self._last_tls_insecure = tls_insecure
            log.info("Speedtest Tracker: %s", url)

    def collect(self) -> CollectorResult | None:
        """Sync unless another sync runs or demo mode is on; None means skipped."""
        if not _SYNC_LOCK.acquire(blocking=False):
            return None
        try:
            if self._config_mgr.is_demo_mode():  # switched on after the caller looked
                return None
            self._ensure_client()
            error = _cache_new_results(self._storage, self._client, self.on_import)
            newest = self._storage.get_speedtest_results(limit=1)
            if newest:
                self._web.update_state(speedtest_latest=newest[0])
            else:
                self._web.clear_speedtest_latest()
        finally:
            _SYNC_LOCK.release()
        if error:
            log.warning("Speedtest fetch failed: %s", error)
            return CollectorResult(source=self.name, success=False, error=f"Speedtest Tracker: {error}")
        return CollectorResult(source=self.name)
