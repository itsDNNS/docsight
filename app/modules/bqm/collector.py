"""BQM collector -- daily ThinkBroadband CSV fetch via public share URL."""

import logging
import random
import time
from datetime import timedelta

from app.collectors.base import Collector, CollectorResult
from app.tz import get_tz_name, local_now

from .auth import BASE_URL, SHARE_PATH, extract_share_id, fetch_graph, fetch_share_csv, is_csv_url, is_share_url, ThinkBroadbandBatchAbort
from .csv_parser import parse_bqm_csv
from .storage import BqmStorage

log = logging.getLogger("docsis.collector.bqm")


def collect_bqm(storage, bqm_url, collection_date, png_date):
    """Fetch, store and record one day of BQM data for a ThinkBroadband share URL.

    CSV share URLs store the "yesterday" CSV; other URLs store the graph PNG
    (from the share address for ThinkBroadband share URLs) under ``png_date``.
    The day is recorded as collected only once stored.
    """
    share_id = extract_share_id(bqm_url)
    try:
        if is_csv_url(bqm_url):
            content = fetch_share_csv(share_id, variant="y")
            if not content:
                return {"success": False, "error": "BQM CSV download failed"}
            rows = parse_bqm_csv(content)
            if not rows:
                return {"success": False, "error": "BQM CSV contained no valid rows"}
            storage.store_csv_data(rows)
            dates = sorted({row["date"] for row in rows})
            result = {
                "success": True,
                "mode": "csv",
                "rows": len(rows),
                "date": dates[-1],
                "date_range": {"start": dates[0], "end": dates[-1]},
            }
        else:
            share = share_id and is_share_url(bqm_url)
            image = fetch_graph(f"{BASE_URL}{SHARE_PATH}{share_id}.png" if share else bqm_url)
            if not image:
                return {"success": False, "error": "BQM graph download failed"}
            storage.save_bqm_graph(image, graph_date=png_date)
            result = {"success": True, "mode": "png", "date": png_date}
    except ThinkBroadbandBatchAbort:
        return {"success": False, "error": "ThinkBroadband temporarily rejected the BQM request"}
    except ValueError as exc:
        log.warning("Invalid BQM CSV: %s", exc)
        return {"success": False, "error": "BQM CSV is invalid"}
    except Exception:
        log.exception("BQM fetch failed")
        return {"success": False, "error": "BQM fetch failed"}
    storage.record_collection_success(
        collection_date=collection_date,
        target_date=result["date"],
        mode=result["mode"],
        rows=result.get("rows", 1),
    )
    return result


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

    def _pending_day(self):
        """Return (now, today, yesterday) in the configured zone, or None once yesterday is collected."""
        now = local_now(get_tz_name(self._config_mgr))
        today = now.date().isoformat()
        if today == self._last_date:
            return None
        target_date = (now.date() - timedelta(days=1)).isoformat()
        if self._storage.get_collection_metadata().get("last_success_target_date") == target_date:
            self._last_date = today
            return None
        return now, today, target_date

    def should_poll(self) -> bool:
        """True if configured time + spread offset has passed, target date is missing and no retry backoff runs."""
        with self._lock:
            if time.time() - self._last_poll < self._penalty_seconds_unlocked():
                return False
        pending = self._pending_day()
        if not pending:
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
        return pending[0].strftime("%H:%M") >= target

    def collect(self) -> CollectorResult:
        pending = self._pending_day()
        if not pending:
            return CollectorResult(source=self.name, data={"skipped": True, "reason": "already_collected"})
        _, today, target_date = pending
        bqm_url = self._config_mgr.get("bqm_url") or ""
        if is_csv_url(bqm_url) and not extract_share_id(bqm_url):
            return CollectorResult(source=self.name, data={"skipped": True, "reason": "no_share_id"})
        result = collect_bqm(self._storage, bqm_url, today, target_date)
        if result["success"]:
            self._last_date = today
        return CollectorResult(source=self.name, data=result, success=result["success"], error=result.get("error"))
