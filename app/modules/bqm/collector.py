"""BQM collector -- daily ThinkBroadband CSV fetch via public share URL."""

import logging
import random
import time
from datetime import date, timedelta

from app.collectors.base import Collector, CollectorResult
from .auth import extract_share_id, fetch_share_csv, ThinkBroadbandBatchAbort
from .csv_parser import parse_bqm_csv
from .storage import BqmStorage

log = logging.getLogger("docsis.collector.bqm")


class BQMCollector(Collector):
    """Fetches ThinkBroadband BQM CSV data once per day via share URL.

    Uses time-of-day scheduling instead of interval-based polling.
    Fetches the "yesterday" CSV (00:00-23:59) which is available after 00:30.
    """

    name = "bqm"

    def __init__(self, config_mgr, storage, poll_interval=86400, **kwargs):
        super().__init__(poll_interval)
        self._config_mgr = config_mgr
        self._storage = BqmStorage(storage.db_path)
        self._last_date = None
        self._spread_offset = random.randint(0, 120)  # 0-120 min after 00:30

    def is_enabled(self) -> bool:
        return self._config_mgr.is_bqm_configured()

    def should_poll(self) -> bool:
        """True if configured time + spread offset has passed today."""
        today = time.strftime("%Y-%m-%d")
        if today == self._last_date:
            return False
        target = self._config_mgr.get("bqm_collect_time") or "02:00"
        h, m = map(int, target.split(":"))
        total = h * 60 + m + self._spread_offset
        if total < 30:
            total = 30  # never fire before 00:30
        # Cap at 23:59 to prevent wrap-around firing a day early
        if total >= 1440:
            total = 1439
        target = f"{total // 60:02d}:{total % 60:02d}"
        now_hm = time.strftime("%H:%M")
        return now_hm >= target

    def collect(self) -> CollectorResult:
        today = time.strftime("%Y-%m-%d")
        if today == self._last_date:
            return CollectorResult(source=self.name, data={"skipped": True})

        bqm_url = self._config_mgr.get("bqm_url") or ""
        share_id = extract_share_id(bqm_url)
        if not share_id:
            # Legacy PNG mode or not configured — skip CSV collection
            return CollectorResult(source=self.name, data={"skipped": True, "reason": "no_csv"})

        graph_date = (date.today() - timedelta(days=1)).isoformat()

        try:
            content = fetch_share_csv(share_id, variant="y")
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
