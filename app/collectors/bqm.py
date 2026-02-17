"""BQM collector — daily ThinkBroadband quality graph fetch."""

import logging
import time

from .base import Collector, CollectorResult
from .. import thinkbroadband

log = logging.getLogger("docsis.collector.bqm")


class BQMCollector(Collector):
    """Fetches the BQM quality graph PNG once per day."""

    name = "bqm"

    def __init__(self, config_mgr, storage, poll_interval=86400):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = storage
        self._last_date = None

    def is_enabled(self) -> bool:
        return self._config_mgr.is_bqm_configured()

    def collect(self) -> CollectorResult:
        today = time.strftime("%Y-%m-%d")
        if today == self._last_date:
            return CollectorResult(source=self.name, data={"skipped": True})

        url = self._config_mgr.get("bqm_url")
        image = thinkbroadband.fetch_graph(url)
        if image:
            self._storage.save_bqm_graph(image)
            self._last_date = today
            return CollectorResult(source=self.name)

        return CollectorResult(
            source=self.name, success=False, error="Failed to fetch BQM graph"
        )
