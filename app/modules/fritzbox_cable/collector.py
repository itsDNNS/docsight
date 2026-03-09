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
            from datetime import datetime, timezone

            body = resp.json()
            data_items = body["data"]
            own = next(d for d in data_items if d["type"] == "own")
            total = next(d for d in data_items if d["type"] == "total")

            last_sample_time = body.get("lastSampleTime", 0)
            sample_interval_ms = body.get("sampleInterval", 60000)
            sample_interval_s = sample_interval_ms / 1000
            n_samples = len(total["downstream"])

            saved = 0
            for i in range(n_samples):
                ds_t = total["downstream"][i]
                us_t = total["upstream"][i]
                ds_o = own["downstream"][i]
                us_o = own["upstream"][i]
                if ds_t is None and us_t is None:
                    continue
                sample_epoch = last_sample_time - (n_samples - 1 - i) * sample_interval_s
                ts = datetime.fromtimestamp(sample_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                self._storage.save_at(ts, ds_t, us_t, ds_o, us_o)
                saved += 1

            ds_total = _last_non_null(total["downstream"])
            us_total = _last_non_null(total["upstream"])
            ds_own = _last_non_null(own["downstream"])
            us_own = _last_non_null(own["upstream"])

            log.info(
                "Segment utilization: DS %.1f%% (own %.2f%%), US %.1f%% (own %.2f%%) [%d samples stored]",
                ds_total or 0, ds_own or 0, us_total or 0, us_own or 0, saved,
            )
            return CollectorResult.ok(
                self.name,
                {"ds_total": ds_total, "us_total": us_total, "ds_own": ds_own, "us_own": us_own},
            )
        except Exception as e:
            return CollectorResult.failure(self.name, f"Parse failed: {e}")
