"""Segment utilization collector for fritzbox_cable module."""

import logging

import requests

from app import fritzbox as fb
from app.collectors.base import Collector, CollectorResult
from app.modules.fritzbox_cable.storage import SegmentUtilizationStorage

log = logging.getLogger("docsis.collector.segment_utilization")


def _last_non_null(values):
    """Return the last non-None value from a list, or None if all are None/empty."""
    for v in reversed(values):
        if v is not None:
            return v
    return None


class SegmentUtilizationCollector(Collector):
    """Polls FritzBox /api/v0/monitor/segment/0 for cable segment utilization."""

    def __init__(self, config_mgr, storage, web=None, **kwargs):
        super().__init__(poll_interval_seconds=300)
        self._config = config_mgr
        self._storage = SegmentUtilizationStorage(storage.db_path)
        self._web = web

    @property
    def name(self):
        return "segment_utilization"

    def is_enabled(self):
        return (
            self._config.get("modem_type") == "fritzbox"
            and bool(self._config.get("segment_utilization_enabled"))
        )

    def collect(self):
        url = self._config.get("modem_url")
        try:
            sid = fb.login(
                url,
                self._config.get("modem_user"),
                self._config.get("modem_password"),
            )
        except Exception as e:
            return CollectorResult.failure(self.name, str(e))

        try:
            resp = requests.get(
                f"{url}/api/v0/monitor/segment/0",
                headers={"AUTHORIZATION": f"AVM-SID {sid}"},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            return CollectorResult.failure(self.name, f"API request failed: {e}")

        try:
            body = resp.json()
            data_items = body["data"]
            own = next(d for d in data_items if d["type"] == "own")
            total = next(d for d in data_items if d["type"] == "total")

            ds_total = _last_non_null(total["downstream"])
            us_total = _last_non_null(total["upstream"])
            ds_own = _last_non_null(own["downstream"])
            us_own = _last_non_null(own["upstream"])

            self._storage.save(ds_total, us_total, ds_own, us_own)

            log.info(
                "Segment utilization: DS %.1f%% (own %.2f%%), US %.1f%% (own %.2f%%)",
                ds_total or 0, ds_own or 0, us_total or 0, us_own or 0,
            )
            return CollectorResult.ok(
                self.name,
                {"ds_total": ds_total, "us_total": us_total, "ds_own": ds_own, "us_own": us_own},
            )
        except Exception as e:
            return CollectorResult.failure(self.name, f"Parse failed: {e}")
