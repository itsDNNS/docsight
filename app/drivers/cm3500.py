"""Arris CM3500B driver for DOCSight.

The CM3500B is a standalone DOCSIS 3.1 / EuroDOCSIS 3.0 cable modem
by Arris (Commscope). It provides channel data via HTML tables at
/cgi-bin/status_cgi with form-based login (IP-based session).

Tables are identified by their preceding <h4> heading:
- "Downstream QAM"   (SC-QAM channels)
- "Downstream OFDM"  (OFDM channels)
- "Upstream QAM"      (ATDMA channels)
- "Upstream OFDM"     (OFDMA channels, may be empty)

Device info is available on the same status page.
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import ModemDriver
from .formats.html_rows import (
    find_cm3500_sections,
    format_cm3500_frequency,
    parse_cm3500_ds_ofdm,
    parse_cm3500_ds_qam,
    parse_cm3500_html,
    parse_cm3500_us_ofdm,
    parse_cm3500_us_qam,
)
from .formats.primitives import parse_number
from ..types import DocsisData, DeviceInfo, ConnectionInfo, RawChannel

log = logging.getLogger("docsis.driver.cm3500")


class CM3500Driver(ModemDriver):
    """Driver for Arris CM3500B DOCSIS 3.1 cable modem.

    Authentication uses form POST (IP-based session, no cookies).
    DOCSIS data is scraped from HTML tables.
    """

    FORMAT_FAMILIES = ("cm3500_html",)

    def __init__(self, url: str, user: str, password: str):
        # CM3500B requires HTTPS; upgrade silently if user provided HTTP
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
            log.info("CM3500 requires HTTPS, upgraded URL to %s", url)
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False

    def login(self) -> None:
        """Authenticate via form POST to /cgi-bin/login_cgi.

        Retries once with a fresh connection if the modem drops a stale
        TCP connection (common after container restarts).
        """
        for attempt in range(2):
            try:
                r = self._session.post(
                    f"{self._url}/cgi-bin/login_cgi",
                    data={"username": self._user, "password": self._password},
                    timeout=30,
                )
                r.raise_for_status()
                log.info("CM3500 auth OK")
                return
            except requests.ConnectionError:
                if attempt == 0:
                    log.warning("CM3500 connection lost, retrying with fresh session")
                    self._session.close()
                    self._session = requests.Session()
                    self._session.verify = False
                    continue
                raise RuntimeError("CM3500 authentication failed: connection refused after retry")
            except requests.RequestException as e:
                raise RuntimeError(f"CM3500 authentication failed: {e}")

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from HTML tables on status page.

        Returns pre-split format so the analyzer correctly labels
        QAM channels as DOCSIS 3.0 and OFDM/OFDMA channels as 3.1.
        """
        return parse_cm3500_html(self._fetch_status_page()).value

    def get_device_info(self) -> DeviceInfo:
        """Retrieve device info from status page."""
        try:
            soup = self._fetch_status_page()
            info = {}
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) == 2:
                        key = cells[0].get_text(strip=True)
                        val = cells[1].get_text(strip=True)
                        if key:
                            info[key] = val

            model = info.get("Hardware Model", "CM3500B")
            uptime_str = info.get("System Uptime:", "")

            result = {
                "manufacturer": "Arris",
                "model": model,
                "sw_version": "",
            }

            m = re.match(r"(\d+)\s*d:\s*(\d+)\s*h:\s*(\d+)\s*m", uptime_str)
            if m:
                result["uptime_seconds"] = (
                    int(m.group(1)) * 86400
                    + int(m.group(2)) * 3600
                    + int(m.group(3)) * 60
                )

            return result
        except Exception:
            return {"manufacturer": "Arris", "model": "CM3500B", "sw_version": ""}

    def get_connection_info(self) -> ConnectionInfo:
        """Parse provisioned speeds from config_params_cgi service flows."""
        try:
            r = self._session.get(
                f"{self._url}/cgi-bin/config_params_cgi",
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("CM3500 config params unavailable: %s", e)
            return {}

        return self._parse_service_flows(r.text)

    @staticmethod
    def _parse_service_flows(html: str) -> ConnectionInfo:
        """Extract max downstream/upstream speeds from service flow config.

        The config_params_cgi page contains a <pre> block with service flows.
        Each flow has a direction (Downstream/Upstream) and SfMaxTrafficRate
        in bps.  The highest rate per direction is the provisioned speed.
        Some CM3500B firmware renders uint32 rates above 2 Gbit/s as signed
        32-bit integers, so negative values are unwrapped before comparison.
        """
        ds_rates = []
        us_rates = []
        current_dir = None

        for line in html.splitlines():
            stripped = line.strip()
            if stripped.startswith("DownstreamServiceFlow"):
                current_dir = "ds"
            elif stripped.startswith("UpstreamServiceFlow"):
                current_dir = "us"
            elif stripped.startswith(("DownstreamPacketClassification",
                                     "UpstreamPacketClassification")):
                current_dir = None
            elif current_dir and stripped.startswith("SfMaxTrafficRate"):
                match = re.search(r"=\s*(-?\d+)", stripped)
                if match:
                    rate = int(match.group(1))
                    if rate < 0:
                        rate += 2**32
                    if current_dir == "ds":
                        ds_rates.append(rate)
                    else:
                        us_rates.append(rate)

        if not ds_rates and not us_rates:
            return {}

        result = {}
        if ds_rates:
            result["max_downstream_kbps"] = max(ds_rates) // 1000
        if us_rates:
            result["max_upstream_kbps"] = max(us_rates) // 1000
        result["connection_type"] = "DOCSIS"
        return result

    # -- Internal helpers --

    def _fetch_status_page(self) -> BeautifulSoup:
        """Fetch and parse the status page HTML."""
        try:
            r = self._session.get(
                f"{self._url}/cgi-bin/status_cgi",
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"CM3500 status page retrieval failed: {e}")
        return BeautifulSoup(r.text, "html.parser")

    def _find_table_sections(self, soup) -> dict[str, object]:
        return find_cm3500_sections(soup)

    # -- Downstream parsers --

    def _parse_ds_qam(self, table) -> list[RawChannel]:
        return parse_cm3500_ds_qam(table).value

    def _parse_ds_ofdm(self, table) -> list[RawChannel]:
        return parse_cm3500_ds_ofdm(table).value

    # -- Upstream parsers --

    def _parse_us_qam(self, table) -> list[RawChannel]:
        return parse_cm3500_us_qam(table).value

    def _parse_us_ofdm(self, table) -> list[RawChannel]:
        return parse_cm3500_us_ofdm(table).value

    # -- Value parsers --

    @staticmethod
    def _parse_number(value: str) -> float:
        return parse_number(value)

    @staticmethod
    def _format_freq(freq_str: str) -> str:
        return format_cm3500_frequency(freq_str)
