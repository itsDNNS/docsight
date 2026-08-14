"""Technicolor TC4400 driver for DOCSight.

The TC4400 is a standalone DOCSIS 3.1 cable modem used by ISPs like
Vodafone and Pyur. It provides channel data via HTML tables at
/cmconnectionstatus.html with HTTP Basic Auth.

References:
- check_tc4400: https://github.com/infertux/check_tc4400
- tc4400_exporter: https://github.com/markuslindenberg/tc4400_exporter
- Technicolor_modem_scrape: https://github.com/Fluepke/Technicolor_modem_scrape
"""

from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup

from .base import ModemDriver
from .formats.html_rows import (
    _cell as format_cell,
    _tc_columns,
    _tc_header_row,
    parse_tc4400_downstream,
    parse_tc4400_upstream,
)
from .formats.primitives import normalize_modulation, parse_mhz_value, parse_number
from ..types import DocsisData, DeviceInfo, ConnectionInfo, RawChannel

log = logging.getLogger("docsis.driver.tc4400")


class TC4400Driver(ModemDriver):
    """Driver for Technicolor TC4400 DOCSIS 3.1 cable modem.

    Authentication uses HTTP Basic Auth. DOCSIS data is scraped from
    HTML tables (no JSON API available). Response time can be ~20s.
    """

    FORMAT_FAMILIES = ("tc4400_html",)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.auth = (user, password)

    def login(self) -> None:
        """Verify credentials with a lightweight request."""
        try:
            r = self._session.get(
                f"{self._url}/cmswinfo.html",
                timeout=30,
            )
            r.raise_for_status()
            log.info("TC4400 auth OK")
        except requests.RequestException as e:
            raise RuntimeError(f"TC4400 authentication failed: {e}")

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from HTML tables.

        The page /cmconnectionstatus.html contains multiple tables:
        - tables[1]: Downstream (SC-QAM + OFDM channels)
        - tables[2]: Upstream (ATDMA + OFDMA channels)
        """
        try:
            r = self._session.get(
                f"{self._url}/cmconnectionstatus.html",
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"TC4400 DOCSIS data retrieval failed: {e}")

        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")

        if len(tables) < 3:
            raise RuntimeError(
                f"TC4400: Expected at least 3 tables, found {len(tables)}"
            )

        downstream = self._parse_downstream(tables[1])
        upstream = self._parse_upstream(tables[2])

        return {
            "docsis": "3.1",
            "downstream": downstream,
            "upstream": upstream,
        }

    def get_device_info(self) -> DeviceInfo:
        """Retrieve device info from /cmswinfo.html."""
        try:
            r = self._session.get(
                f"{self._url}/cmswinfo.html",
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("TC4400 device info failed: %s", e)
            return {
                "manufacturer": "Technicolor",
                "model": "TC4400",
                "sw_version": "",
            }

        soup = BeautifulSoup(r.text, "html.parser")
        info = self._parse_info_table(soup)

        return {
            "manufacturer": "Technicolor",
            "model": info.get("Model Name", "TC4400"),
            "sw_version": info.get(
                "Software Version", info.get("Firmware Version", "")
            ),
        }

    def get_connection_info(self) -> ConnectionInfo:
        """Not applicable for standalone modem."""
        return {}

    # ── Parsers ────────────────────────────────────────────────

    def _parse_downstream(self, table) -> list[RawChannel]:
        return parse_tc4400_downstream(table).value

    def _parse_upstream(self, table) -> list[RawChannel]:
        return parse_tc4400_upstream(table).value

    @staticmethod
    def _find_header_row(rows):
        return _tc_header_row(rows)

    def _map_columns(self, headers: list[str]) -> dict[str, int | None]:
        return _tc_columns(headers)

    @staticmethod
    def _cell(cells: list[str], index: int | None, default: str = "") -> str:
        return format_cell(cells, index, default)

    def _parse_info_table(self, soup) -> dict[str, str]:
        """Parse key-value info table from /cmswinfo.html."""
        info = {}
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    val = cells[1].get_text(strip=True)
                    if key:
                        info[key] = val
        return info

    # ── Value Parsers ──────────────────────────────────────────

    def _parse_frequency(self, freq_str: str) -> float:
        return parse_mhz_value(freq_str)

    @staticmethod
    def _parse_number(value: str) -> float:
        return parse_number(value)

    @staticmethod
    def _normalize_modulation(modulation: str) -> str:
        return normalize_modulation(modulation)
