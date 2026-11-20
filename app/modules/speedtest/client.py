"""Speedtest Tracker API client – fetches speed test results."""

import logging
from datetime import datetime, timezone

import requests

from app.config import parse_config_bool
from app.tz import UTC_FMT

log = logging.getLogger("docsis.speedtest")

# Speedtest Tracker lists a test as soon as it starts, without measurements yet
_UNFINISHED_STATUSES = frozenset({"waiting", "started", "checking", "running", "benchmarking"})


def is_finished(result):
    """True for a finished API result or parsed result; no status (older versions) counts as finished."""
    return result.get("status") not in _UNFINISHED_STATUSES


def public_error(exc: BaseException) -> str:
    """A fixed description of a failed Speedtest Tracker request.

    Exception texts can carry the request's Authorization header, so they are
    never shown or logged.
    """
    if isinstance(exc, requests.HTTPError):
        return f"HTTP {exc.response.status_code}" if exc.response is not None else "HTTP error"
    if isinstance(exc, requests.Timeout):  # ConnectTimeout is also a ConnectionError
        return "Speedtest Tracker timeout"
    if isinstance(exc, requests.ConnectionError):
        return "Cannot reach Speedtest Tracker"
    return "Unexpected error, see the DOCSight log"


class SpeedtestClient:
    """Client for the Speedtest Tracker API (github.com/alexjustesen/speedtest-tracker)."""

    def __init__(self, url, token, tls_insecure: bool | str = False):
        tls_insecure = parse_config_bool(tls_insecure)
        self.base_url = url.rstrip("/")
        self.token = token
        self.verify_tls = not tls_insecure
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
        })
        if tls_insecure:
            log.warning("Speedtest Tracker TLS certificate verification disabled")

    @staticmethod
    def _normalize_ts(ts):
        """Normalize a timestamp to ISO 8601 UTC with Z suffix for consistent sorting."""
        if not ts:
            return ts
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime(UTC_FMT)
        except (ValueError, TypeError):
            return ts

    def _parse_result(self, item):
        """Extract relevant fields from a single API result object."""
        data = item.get("data") or {}
        ping_obj = data.get("ping") or {}
        server = data.get("server") or {}
        raw_ts = data.get("timestamp") or item.get("created_at")  # None keeps a stored time
        dl = data.get("download") or {}
        ul = data.get("upload") or {}
        dl_lat = dl.get("latency") or {}
        ul_lat = ul.get("latency") or {}
        iface = data.get("interface") or {}
        result_obj = data.get("result") or {}

        def _round2(val):
            return round(float(val), 2) if val is not None else None

        def _mbps(bits):  # omitted until a test finishes, and for failed tests
            return round(bits / 1_000_000, 2) if bits is not None else None

        ping_low_raw = ping_obj.get("low")
        ping_high_raw = ping_obj.get("high")

        return {
            "id": item.get("id"),
            "status": item.get("status"),
            "timestamp": self._normalize_ts(raw_ts),
            "download_mbps": _mbps(item.get("download_bits")),
            "upload_mbps": _mbps(item.get("upload_bits")),
            "download_human": item.get("download_bits_human"),
            "upload_human": item.get("upload_bits_human"),
            "ping_ms": _round2(item.get("ping")),
            "jitter_ms": _round2(ping_obj.get("jitter")),
            "packet_loss_pct": _round2(data.get("packetLoss")),
            "server_id": server.get("id"),
            "server_name": server.get("name"),
            # enriched fields
            "isp": data.get("isp"),
            "server_host": server.get("host"),
            "server_location": server.get("location"),
            "server_country": server.get("country"),
            "server_ip": server.get("ip"),
            "ping_low": _round2(ping_low_raw),
            "ping_high": _round2(ping_high_raw),
            "dl_latency_iqm": _round2(dl_lat.get("iqm")),
            "dl_latency_jitter": _round2(dl_lat.get("jitter")),
            "ul_latency_iqm": _round2(ul_lat.get("iqm")),
            "ul_latency_jitter": _round2(ul_lat.get("jitter")),
            "dl_bytes": dl.get("bytes"),
            "ul_bytes": ul.get("bytes"),
            "dl_elapsed_ms": dl.get("elapsed"),
            "ul_elapsed_ms": ul.get("elapsed"),
            "external_ip": iface.get("externalIp"),
            "is_vpn": iface.get("isVpn"),
            "result_url": result_obj.get("url"),
        }

    def _get_page(self, size, page=1, timeout=30):
        """One page of results, newest first. A reply without a list of results is no proof of an empty Tracker."""
        resp = self.session.get(
            self.base_url + "/api/v1/results",
            params={"page[size]": size, "page[number]": page, "sort": "-created_at"},
            timeout=timeout,
            verify=self.verify_tls,
        )
        resp.raise_for_status()
        body = resp.json()
        items = body.get("data")
        if not isinstance(items, list) or not all(isinstance(r, dict) and type(r.get("id")) is int for r in items):
            raise TypeError("results are not a list of results with ids")
        return body

    def get_latest(self, count=1):
        """Fetch the latest N speed test results."""
        results, _ = self.get_latest_with_error(count)
        return results

    def get_latest_with_error(self, count=1):
        """Fetch the latest N results, returning (results, error_string|None)."""
        try:
            return [self._parse_result(r) for r in self._get_page(count, timeout=15)["data"]], None
        except Exception as exc:
            msg = public_error(exc)
            log.warning("Failed to fetch speedtest results: %s (%s)", msg, type(exc).__name__)
            return [], msg

    def get_results(self, start_date=None, end_date=None, per_page=100):
        """Fetch speed test results, newest first. Paginates to collect up to per_page results."""
        return self.get_results_with_error(per_page)[0]

    def get_results_with_error(self, per_page=100):
        """Fetch up to per_page finished results, newest first, returning (results, error_string|None)."""
        all_results = []
        page = 1
        try:
            while len(all_results) < per_page:
                body = self._get_page(min(per_page, 500), page)  # a fixed size, so skipped results do not shift pages
                all_results.extend(self._parse_result(r) for r in body["data"] if is_finished(r))
                if not body["data"] or page >= body.get("meta", {}).get("last_page", 1):
                    if body.get("links", {}).get("next"):  # then the read is not complete
                        raise TypeError("the last page links to more results")
                    break
                page += 1
        except Exception as exc:
            error = public_error(exc)
            log.warning("Failed to fetch speedtest results: %s (%s)", error, type(exc).__name__)
            return all_results[:per_page], error
        return all_results[:per_page], None

    def get_newer_than(self, floor, known_ids):
        """Fetch the newest 500 finished results above floor that are not known yet, oldest first.

        Rechecking the ids above the floor picks up a test that finished after a newer one.
        """
        all_results = []
        page = 1
        try:
            while True:
                body = self._get_page(500, page)
                # Creation times can tie, so ids are not strictly descending: only a page
                # entirely at or below the floor ends the scan
                fresh = [item for item in body["data"] if item["id"] > floor]
                if not fresh:
                    break
                all_results.extend(
                    self._parse_result(item) for item in fresh if item.get("id") not in known_ids and is_finished(item)
                )
                meta = body.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                if len(all_results) >= 500:
                    break
                page += 1
        except Exception as exc:
            log.warning("Failed to fetch newer speedtest results: %s (%s)", public_error(exc), type(exc).__name__)
        return all_results[:500][::-1]
