"""BQM collector -- daily ThinkBroadband CSV fetch."""

import logging
import random
import time
from datetime import date, timedelta

from app.collectors.base import Collector, CollectorResult
from .auth import ThinkBroadbandAuth, ThinkBroadbandBatchAbort
from .csv_parser import parse_bqm_csv
from .storage import BqmStorage

log = logging.getLogger("docsis.collector.bqm")


class BQMCollector(Collector):
    """Fetches ThinkBroadband BQM CSV data once per day.

    Uses time-of-day scheduling instead of interval-based polling.
    If collect_time is before 12:00, the graph date is stored as yesterday
    (the 24h export represents the previous day). Otherwise stored as today.
    """

    name = "bqm"

    def __init__(self, config_mgr, storage, poll_interval=86400, **kwargs):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = BqmStorage(storage.db_path)
        self._last_date = None
        self._spread_offset = random.randint(0, 120)  # 0-120 min before target

    def is_enabled(self) -> bool:
        return self._config_mgr.is_bqm_configured()

    def should_poll(self) -> bool:
        """True if configured time + spread offset has passed today."""
        today = time.strftime("%Y-%m-%d")
        if today == self._last_date:
            return False
        target = self._config_mgr.get("bqm_collect_time") or "02:00"
        h, m = map(int, target.split(":"))
        total = h * 60 + m - self._spread_offset
        if 0 <= total < 30:
            total = 30  # never fire before 00:30
        target = f"{(total // 60) % 24:02d}:{total % 60:02d}"
        now_hm = time.strftime("%H:%M")
        return now_hm >= target

    def collect(self) -> CollectorResult:
        today = time.strftime("%Y-%m-%d")
        if today == self._last_date:
            return CollectorResult(source=self.name, data={"skipped": True})

        collect_time = self._config_mgr.get("bqm_collect_time") or "02:00"
        if collect_time < "12:00":
            graph_date = (date.today() - timedelta(days=1)).isoformat()
        else:
            graph_date = date.today().isoformat()

        client = ThinkBroadbandAuth(
            self._config_mgr.get("bqm_username") or "",
            self._config_mgr.get("bqm_password") or "",
        )
        try:
            if not client.login():
                return CollectorResult.failure(self.name, "Failed to authenticate with ThinkBroadband")
            content = client.download_csv(self._config_mgr.get("bqm_monitor_id") or "", graph_date)
            if not content:
                return CollectorResult.failure(self.name, "Failed to download BQM CSV")
            rows = parse_bqm_csv(content)
            if not rows:
                return CollectorResult.failure(self.name, "BQM CSV contained no valid rows")
            self._storage.store_csv_data(rows)
            self._last_date = today
            return CollectorResult.ok(self.name, {"rows": len(rows), "date": graph_date})
        except ThinkBroadbandBatchAbort as exc:
            return CollectorResult.failure(self.name, f"ThinkBroadband batch aborted: {exc}")
        except ValueError as exc:
            return CollectorResult.failure(self.name, f"Invalid BQM CSV: {exc}")
