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
        server = data.get("server") or {}
        return {
            "id": item.get("id"),
            "timestamp": data.get("timestamp") or item.get("created_at", ""),
            "download_mbps": round(item.get("download_bits", 0) / 1_000_000, 2),
            "upload_mbps": round(item.get("upload_bits", 0) / 1_000_000, 2),
            "download_human": item.get("download_bits_human", ""),
            "upload_human": item.get("upload_bits_human", ""),
            "ping_ms": round(float(item.get("ping", 0)), 2),
            "jitter_ms": round(float(ping_obj.get("jitter", 0)), 2),
            "packet_loss_pct": round(float(data.get("packetLoss") or 0), 2),
            "server_id": server.get("id"),
            "server_name": server.get("name", ""),
        }

    def get_latest(self, count=1):
        """Fetch the latest N speed test results."""
        results, _ = self.get_latest_with_error(count)
        return results

    def get_latest_with_error(self, count=1):
        """Fetch the latest N results, returning (results, error_string|None)."""
        try:
            resp = self.session.get(
                self.base_url + "/api/v1/results",
                params={"page[size]": count, "sort": "-created_at"},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("data", [])
            return [self._parse_result(r) for r in results], None
        except requests.ConnectionError as e:
            msg = f"ConnectionError: {str(e).split(chr(10))[0][:200]}"
            log.warning("Failed to fetch speedtest results: %s", msg)
            return [], msg
        except requests.HTTPError as e:
            msg = f"HTTP {e.response.status_code}" if e.response is not None else str(e)
            log.warning("Failed to fetch speedtest results: %s", msg)
            return [], msg
        except requests.Timeout:
            log.warning("Speedtest Tracker request timed out")
            return [], "Timeout (15s)"
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e).split(chr(10))[0][:200]}"
            log.warning("Failed to fetch speedtest results: %s", msg)
            return [], msg

    def get_results(self, start_date=None, end_date=None, per_page=100):
        """Fetch speed test results, newest first. Paginates to collect up to per_page results."""
        all_results = []
        page = 1
        try:
            while len(all_results) < per_page:
                batch = min(per_page - len(all_results), 500)
                resp = self.session.get(
                    self.base_url + "/api/v1/results",
                    params={
                        "page[size]": batch,
                        "page[number]": page,
                        "sort": "-created_at",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                body = resp.json()
                items = body.get("data", [])
                if not items:
                    break
                all_results.extend(self._parse_result(r) for r in items)
                meta = body.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1
            return all_results
        except Exception as e:
            log.warning("Failed to fetch speedtest results: %s", e)
            return all_results

    def get_newer_than(self, last_id, per_page=500):
        """Fetch results with id > last_id. Sorts newest-first and stops at last_id."""
        all_results = []
        page = 1
        done = False
        try:
            while not done:
                batch = min(per_page - len(all_results), 500) if per_page else 500
                resp = self.session.get(
                    self.base_url + "/api/v1/results",
                    params={
                        "page[size]": batch,
                        "page[number]": page,
                        "sort": "-created_at",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                body = resp.json()
                items = body.get("data", [])
                if not items:
                    break
                for item in items:
                    if item.get("id", 0) > last_id:
                        all_results.append(self._parse_result(item))
                    else:
                        done = True
                        break
                meta = body.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                if per_page and len(all_results) >= per_page:
                    break
                page += 1
            # Return in chronological order (oldest first)
            all_results.reverse()
            return all_results
        except Exception as e:
            log.warning("Failed to fetch newer speedtest results: %s", e)
            return all_results
