"""Arris SB6190 driver for DOCSight.

DOCSIS 3.0 modem with HTTPS CGI interface. Authentication uses a
Base64-encoded credentials POST to /cgi-bin/adv_pwd_cgi with a random
CSRF nonce. Channel data is on /cgi-bin/status in standard (non-transposed)
HTML tables where each row is one channel. Device info is on /cgi-bin/swinfo.
"""

from __future__ import annotations

import base64
import logging
import random
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .base import ModemDriver
from .format_compat import unwrap
from .formats.html_rows import parse_sb6190_html
from ..types import DocsisData, DeviceInfo, ConnectionInfo
from .utils import request_error_summary

log = logging.getLogger("docsis.driver.sb6190")


class SB6190Driver(ModemDriver):
    """Driver for Arris SB6190 DOCSIS 3.0 cable modem.

    Uses HTTPS with a self-signed certificate. Authentication posts
    Base64-encoded credentials to /cgi-bin/adv_pwd_cgi. Channel data
    is scraped from /cgi-bin/status where each table row is one channel.
    """

    FORMAT_FAMILIES = ("sb6190_html",)

    def __init__(self, url, user, password):
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
            log.info("SB6190 requires HTTPS, upgraded URL to %s", url)
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False
        from .utils import make_legacy_tls_adapter
        self._session.mount("https://", make_legacy_tls_adapter(sec_level=1))

    def login(self) -> None:
        # The SB6190 login page JS URL-encodes the full "username=..." and
        # "password=..." strings before Base64 encoding, not just the values.
        payload = base64.b64encode(
            (quote(f"username={self._user}") + ":" + quote(f"password={self._password}")).encode()
        ).decode()
        nonce = str(random.randint(10_000_000, 99_999_999))
        try:
            r = self._session.post(
                f"{self._url}/cgi-bin/adv_pwd_cgi",
                data={"arguments": payload, "ar_nonce": nonce},
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"SB6190 login failed: {e}")
        if "Error:" in r.text:
            msg = r.text.split("Error:", 1)[1].strip()
            raise RuntimeError(f"SB6190 login rejected: {msg}")
        if "Url:" not in r.text:
            raise RuntimeError("SB6190 login failed: unexpected response (no redirect URL)")
        try:
            status = self._session.get(f"{self._url}/cgi-bin/status", timeout=30)
            status.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"SB6190 login failed: authenticated page check failed: {e}")
        if not self._is_authenticated_status_page(status.text):
            raise RuntimeError("SB6190 login failed: authenticated status page not returned")
        log.info("SB6190 login OK")

    def get_docsis_data(self) -> DocsisData:
        try:
            r = self._session.get(f"{self._url}/cgi-bin/status", timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"SB6190 DOCSIS data retrieval failed: {e}")

        return unwrap(parse_sb6190_html(r.text), log)

    def get_device_info(self) -> DeviceInfo:
        try:
            r = self._session.get(f"{self._url}/cgi-bin/swinfo", timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("SB6190 device info unavailable: %s", request_error_summary(e))
            return {"manufacturer": "Arris", "model": "SB6190", "sw_version": ""}

        soup = BeautifulSoup(r.text, "html.parser")
        info = {}
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                if "software version" in label:
                    info["sw_version"] = value
                elif "hardware version" in label:
                    info["hw_version"] = value
        result: DeviceInfo = {
            "manufacturer": "Arris",
            "model": "SB6190",
            "sw_version": info.get("sw_version", ""),
        }
        if info.get("hw_version"):
            result["hw_version"] = info["hw_version"]
        return result

    def get_connection_info(self) -> ConnectionInfo:
        return {}

    @staticmethod
    def _is_authenticated_status_page(html: str) -> bool:
        """True when the authenticated status page exposes channel tables."""
        text = (html or "").lower()
        return "downstream bonded" in text and "upstream bonded" in text
