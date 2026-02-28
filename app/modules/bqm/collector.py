"""BQM collector -- daily ThinkBroadband quality graph fetch."""

import logging
import time
from datetime import date, timedelta

from app.collectors.base import Collector, CollectorResult
from .thinkbroadband import fetch_graph
from .storage import BqmStorage

log = logging.getLogger("docsis.collector.bqm")


class BQMCollector(Collector):
    """Fetches the BQM quality graph PNG once per day.

    Uses time-of-day scheduling instead of interval-based polling.
    If collect_time is before 12:00, the graph is stored as yesterday's date
    (the 24h image represents the previous day). Otherwise stored as today.
    """

    name = "bqm"

    def __init__(self, config_mgr, storage, poll_interval=86400, **kwargs):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = BqmStorage(storage.db_path)
        self._last_date = None

    def is_enabled(self) -> bool:
        return self._config_mgr.is_bqm_configured()

    def should_poll(self) -> bool:
        """True if configured time has passed today and not yet collected."""
        today = time.strftime("%Y-%m-%d")
        if today == self._last_date:
            return False
        target = self._config_mgr.get("bqm_collect_time") or "02:00"
        now_hm = time.strftime("%H:%M")
        return now_hm >= target

    def collect(self) -> CollectorResult:
        today = time.strftime("%Y-%m-%d")
        if today == self._last_date:
            return CollectorResult(source=self.name, data={"skipped": True})

        url = self._config_mgr.get("bqm_url")
        image = fetch_graph(url)
        if image:
            collect_time = self._config_mgr.get("bqm_collect_time") or "02:00"
            if collect_time < "12:00":
                graph_date = (date.today() - timedelta(days=1)).isoformat()
            else:
                graph_date = date.today().isoformat()
            self._storage.save_bqm_graph(image, graph_date=graph_date)
            self._last_date = today
            return CollectorResult(source=self.name)

        return CollectorResult(
            source=self.name, success=False, error="Failed to fetch BQM graph"
        )
