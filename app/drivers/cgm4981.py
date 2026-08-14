"""DOCSight driver for Technicolor CGM4981COM (Cox Panoramic Gateway PM8 / XB8).

Supported hardware
------------------
- Technicolor / Vantiva CGM4981COM
- Branded as Cox Panoramic Gateway "PM8" or "XB8"
- Firmware series: CGM4981COM_8.x / Prod_23.2 (RDK-B platform)

Authentication
--------------
Standard form POST to ``/check.jst``; session maintained via ``DUKSID`` cookie.

Channel data
------------
All DOCSIS data is embedded in columnar HTML tables on ``/network_setup.jst``.
The page contains three tables parsed by this driver:

  1. **Downstream** – 32× SC-QAM (DOCSIS 3.0) + 2× OFDM (DOCSIS 3.1)
  2. **Upstream**   – 4× SC-QAM ATDMA (DOCSIS 3.0) + 1× OFDMA (DOCSIS 3.1)
  3. **CM Error Codewords** – per-channel correctable / uncorrectable counts
     (aligned to the same 34 downstream channel IDs)

Implementation notes
--------------------
- The three tables share row labels (e.g. "Channel ID" appears in all three).
  This driver parses them by HTML section to avoid label-collision issues.
- OFDM / OFDMA upstream channel power thresholds differ from SC-QAM.
  Cox provisions OFDMA upstream at lower per-channel power (~37 dBmV is normal).
  Adjust the built-in analyzer threshold profile or install a community threshold
  profile if DOCSight flags these as critical:
      ``upstream_power.ofdma.critical: [35.0, 50.0]``
      ``upstream_power.ofdma.good:     [37.0, 47.0]``
"""

from __future__ import annotations

import logging
import re

import requests

from .base import ModemDriver
from ..types import ConnectionInfo, DeviceInfo, DocsisData
from .formats.html_columnar import (
    _float,
    _modulation,
    build_cgm4981_downstream,
    build_cgm4981_upstream,
    parse_cgm4981_columnar_html,
)

log = logging.getLogger("docsis.driver.cgm4981")

__all__ = ["CGM4981Driver", "_float", "_modulation"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOGIN_PATH  = "/check.jst"
_STATUS_PATH = "/network_setup.jst"

# The login-redirect page is always ~8 640 bytes; anything larger is real data.
_MIN_STATUS_PAGE_BYTES = 9_000

# Cookie name that confirms a valid session.
_SESSION_COOKIE = "DUKSID"

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class CGM4981Driver(ModemDriver):
    """Driver for Technicolor CGM4981COM (Cox Panoramic Gateway PM8 / XB8).

    Parses downstream and upstream DOCSIS channel data from the columnar
    HTML tables on ``/network_setup.jst``.  Error counts (correctable and
    uncorrectable codewords) are read from the separate "CM Error Codewords"
    table on the same page.
    """

    FORMAT_FAMILIES = ("cgm4981_columnar_html",)

    def __init__(self, url: str, user: str, password: str) -> None:
        super().__init__(url, user, password)
        self._session: requests.Session = requests.Session()
        self._status_html: str | None = None

    def login(self) -> None:
        """POST credentials to ``/check.jst`` and verify the session cookie."""
        self._status_html = None
        self._session = requests.Session()
        try:
            self._session.post(
                f"{self._url}{_LOGIN_PATH}",
                data={"username": self._user, "password": self._password},
                allow_redirects=True,
                timeout=15,
            ).raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"CGM4981 login request failed: {exc}") from exc

        if _SESSION_COOKIE not in self._session.cookies:
            raise RuntimeError(
                "CGM4981 authentication failed: session cookie not received. "
                "Check username and password."
            )
        log.info(
            "CGM4981 auth OK (DUKSID=%s…)",
            str(self._session.cookies.get(_SESSION_COOKIE, ""))[:8],
        )

    def get_docsis_data(self) -> DocsisData:
        """Return parsed downstream and upstream channel data."""
        return parse_cgm4981_columnar_html(self._fetch_status_page()).value

    def get_device_info(self) -> DeviceInfo:
        """Return model, firmware version, and uptime from the status page."""
        info: DeviceInfo = {
            "manufacturer": "Technicolor",
            "model":        "CGM4981COM",
            "sw_version":   "",
        }
        try:
            html = self._fetch_status_page()

            m = re.search(r"Model:</span>\s*<span[^>]*>\s*(CGM\w+)", html)
            if m:
                info["model"] = m.group(1).strip()

            m = re.search(r"Download Version:</span>\s*<span[^>]*>\s*([^\s<]+)", html)
            if m:
                info["sw_version"] = m.group(1).strip()

            # "0 days 2h: 1m: 11s"
            m = re.search(
                r"System Uptime:</span>\s*<span[^>]*>\s*"
                r"(\d+)\s*days?\s*(\d+)h:\s*(\d+)m:\s*(\d+)s",
                html,
            )
            if m:
                info["uptime_seconds"] = (
                    int(m.group(1)) * 86400
                    + int(m.group(2)) * 3600
                    + int(m.group(3)) * 60
                    + int(m.group(4))
                )
        except Exception:
            pass
        return info

    def get_connection_info(self) -> ConnectionInfo:
        """Return WAN IP and connection status from the status page."""
        info: ConnectionInfo = {}
        try:
            html = self._fetch_status_page()
            m = re.search(
                r"WAN IP Address \(IPv4\):</span>\s*<span[^>]*>\s*([0-9.]+)", html
            )
            if m:
                info["wan_ip"] = m.group(1)
            m = re.search(r"Internet:</span>\s*<span[^>]*>\s*(\w+)", html)
            if m:
                info["status"] = m.group(1)
        except Exception:
            pass
        return info

    def _fetch_status_page(self) -> str:
        """Fetch and cache ``/network_setup.jst``.  Re-authenticates on expiry."""
        if self._status_html is not None:
            return self._status_html

        for attempt in range(2):
            try:
                r = self._session.get(f"{self._url}{_STATUS_PATH}", timeout=40)
                r.raise_for_status()
            except requests.RequestException as exc:
                if attempt == 0:
                    log.warning("CGM4981 status page fetch failed, retrying: %s", exc)
                    self._session = requests.Session()
                    self.login()
                    continue
                raise RuntimeError(
                    f"CGM4981 status page retrieval failed: {exc}"
                ) from exc

            if len(r.text) < _MIN_STATUS_PAGE_BYTES:
                # Session expired — redirect to login page.
                if attempt == 0:
                    log.warning("CGM4981 session expired, re-authenticating")
                    self._session = requests.Session()
                    self.login()
                    continue
                raise RuntimeError(
                    "CGM4981 status page returned login redirect after re-auth"
                )

            self._status_html = r.text
            return self._status_html

        raise RuntimeError("CGM4981 failed to fetch status page after 2 attempts")

    @staticmethod
    def _build_ds_channels(
        ds_rows: dict[str, list[str]],
        err_rows: dict[str, list[str]],
    ) -> list[dict]:
        return build_cgm4981_downstream(ds_rows, err_rows).value

    @staticmethod
    def _build_us_channels(us_rows: dict[str, list[str]]) -> list[dict]:
        return build_cgm4981_upstream(us_rows).value
