"""Speedtest Tracker API client – fetches speed test results."""

import logging

import requests

log = logging.getLogger("docsis.speedtest")


class SpeedtestClient:
    """Client for the Speedtest Tracker API (github.com/alexjustesen/speedtest-tracker)."""

    def __init__(self, url, token):
        self.base_url = url.rstrip("/")
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
        })

    def _parse_result(self, item):
        """Extract relevant fields from a single API result object."""
        data = item.get("data") or {}
        ping_obj = data.get("ping") or {}
        return {
            "timestamp": data.get("timestamp") or item.get("created_at", ""),
            "download_mbps": round(item.get("download_bits", 0) / 1_000_000, 2),
            "upload_mbps": round(item.get("upload_bits", 0) / 1_000_000, 2),
            "download_human": item.get("download_bits_human", ""),
            "upload_human": item.get("upload_bits_human", ""),
            "ping_ms": round(float(item.get("ping", 0)), 2),
            "jitter_ms": round(float(ping_obj.get("jitter", 0)), 2),
            "packet_loss_pct": round(float(data.get("packetLoss") or 0), 2),
        }

    def get_latest(self, count=1):
        """Fetch the latest N speed test results."""
        try:
            resp = self.session.get(
                self.base_url + "/api/v1/results",
                params={"per.page": count, "sort": "-created_at"},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("data", [])
            return [self._parse_result(r) for r in results]
        except Exception as e:
            log.warning("Failed to fetch speedtest results: %s", e)
            return []

    def get_results(self, start_date, end_date, per_page=100):
        """Fetch speed test results for a date range (YYYY-MM-DD)."""
        try:
            resp = self.session.get(
                self.base_url + "/api/v1/results",
                params={
                    "per.page": per_page,
                    "sort": "-created_at",
                    "filter[start_at]": start_date,
                    "filter[end_at]": end_date,
                },
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json().get("data", [])
            return [self._parse_result(r) for r in results]
        except Exception as e:
            log.warning("Failed to fetch speedtest results: %s", e)
            return []
