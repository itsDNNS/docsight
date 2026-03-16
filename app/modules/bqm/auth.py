"""ThinkBroadband authentication and CSV download helpers."""

import logging
from datetime import date

import requests

from app.web import APP_VERSION

log = logging.getLogger("docsis.bqm.auth")

BASE_URL = "https://www.thinkbroadband.com"
LOGIN_PATH = "/auth/login"
CSV_PATH = "/my-profile/broadband-quality-monitor/download-csv/{monitor_id}/{target_date}"


class ThinkBroadbandBatchAbort(Exception):
    """Abort the current collection batch and let collector backoff handle retries."""


class ThinkBroadbandAuth:
    """Session-backed client for ThinkBroadband BQM CSV downloads."""

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": f"DOCSight/{APP_VERSION} (+https://github.com/itsDNNS/docsight)",
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
        })

    def _login_request(self) -> requests.Response:
        return self._session.post(
            BASE_URL + LOGIN_PATH,
            data={"username": self._username, "password": self._password},
            timeout=30,
            allow_redirects=True,
        )

    def _csv_request(self, monitor_id: str, target_date: str) -> requests.Response:
        return self._session.get(
            BASE_URL + CSV_PATH.format(monitor_id=monitor_id, target_date=target_date),
            timeout=30,
            allow_redirects=True,
        )

    def _is_csv_response(self, response: requests.Response) -> bool:
        content_type = (response.headers.get("Content-Type") or "").lower()
        return response.status_code == 200 and ("csv" in content_type or response.text.startswith('"Timestamp",'))

    def _handle_rate_limit(self, response: requests.Response, action: str):
        if response.status_code in (403, 429):
            log.warning("ThinkBroadband %s aborted with HTTP %s", action, response.status_code)
            raise ThinkBroadbandBatchAbort(f"HTTP {response.status_code}")

    def login(self) -> bool:
        """Authenticate and persist the session cookie."""
        try:
            response = self._login_request()
            self._handle_rate_limit(response, "login")
            if response.status_code >= 400:
                log.warning("ThinkBroadband login failed with HTTP %s", response.status_code)
                return False
            return True
        except ThinkBroadbandBatchAbort:
            raise
        except requests.RequestException as exc:
            log.warning("ThinkBroadband login request failed: %s", exc)
            return False

    def download_csv(self, monitor_id: str, target_date: str) -> str:
        """Download a CSV export, re-authenticating once on session expiry."""
        response = None
        try:
            for attempt in range(2):
                response = self._csv_request(monitor_id, target_date)
                self._handle_rate_limit(response, "CSV download")
                if self._is_csv_response(response):
                    return response.text
                if attempt == 0 and self.login():
                    continue
                break
        except ThinkBroadbandBatchAbort:
            raise
        except requests.RequestException as exc:
            log.warning("ThinkBroadband CSV request failed: %s", exc)
            return ""
        log.warning(
            "ThinkBroadband CSV download failed for monitor=%s date=%s with HTTP %s",
            monitor_id,
            target_date,
            response.status_code if response is not None else "n/a",
        )
        return ""

    def validate_monitor_id(self, monitor_id: str) -> bool:
        """Check whether the configured monitor can be downloaded with the current session."""
        try:
            response = self._csv_request(monitor_id, date.today().isoformat())
            self._handle_rate_limit(response, "monitor validation")
            return self._is_csv_response(response)
        except ThinkBroadbandBatchAbort:
            raise
        except requests.RequestException as exc:
            log.warning("ThinkBroadband monitor validation failed: %s", exc)
            return False
