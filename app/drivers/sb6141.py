"""Arris/Motorola SB6141 driver for DOCSight.

The SB6141 is a DOCSIS 3.0 cable modem with a simple HTML web UI and no
authentication. Channel data is on /cmSignalData.htm in transposed tables
(metrics as rows, channels as columns). Error counters are in a separate
"Signal Status (Codewords)" table on the same page.

Device info is on /cmHelpData.htm as plain text with <BR> separators.

This driver may also work with Motorola/Arris SB6xxx modems that share
the same transposed table web UI format.
"""

from __future__ import annotations

import logging
import requests
from bs4 import BeautifulSoup

from .base import ModemDriver
from .formats.html_transposed import (
    extract_transposed_rows,
    extract_upstream_modulation,
    get_row_values,
    parse_sb6141_downstream,
    parse_sb6141_upstream,
)
from .formats.primitives import hz_to_mhz, parse_number
from ..types import DocsisData, DeviceInfo, ConnectionInfo, RawChannel

log = logging.getLogger("docsis.driver.sb6141")

# SB6141 sends malformed HTTP headers (space before colon in Cache-Control),
# which triggers noisy urllib3 HeaderParsingError warnings on every request.
logging.getLogger("urllib3.connection").setLevel(logging.ERROR)


class SB6141Driver(ModemDriver):
    """Driver for Arris/Motorola SB6141 DOCSIS 3.0 cable modem.

    No authentication required. DOCSIS data is scraped from transposed
    HTML tables where each row is a metric and each column is a channel.
    """

    FORMAT_FAMILIES = ("sb6141_transposed_html",)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()

    def login(self) -> None:
        """Verify modem is reachable (no auth required)."""
        try:
            r = self._session.get(
                f"{self._url}/cmSignalData.htm",
                timeout=15,
            )
            r.raise_for_status()
            log.info("SB6141 reachable (no auth required)")
        except requests.RequestException as e:
            raise RuntimeError(f"SB6141 connection failed: {e}")

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from transposed HTML tables."""
        try:
            r = self._session.get(
                f"{self._url}/cmSignalData.htm",
                timeout=15,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"SB6141 DOCSIS data retrieval failed: {e}")

        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table", recursive=True)

        # Find the three main tables by their header text
        ds_table = None
        us_table = None
        cw_table = None

        for table in tables:
            th = table.find("th")
            if not th:
                continue
            text = th.get_text(strip=True).lower()
            if "downstream" in text and "signal" not in text:
                ds_table = table
            elif "upstream" in text:
                us_table = table
            elif "signal status" in text or "codeword" in text:
                cw_table = table

        ds_channels = self._parse_downstream(ds_table, cw_table)
        us_channels = self._parse_upstream(us_table)

        return {
            "channelDs": {"docsis30": ds_channels, "docsis31": []},
            "channelUs": {"docsis30": us_channels, "docsis31": []},
        }

    def get_device_info(self) -> DeviceInfo:
        """Retrieve device info from /cmHelpData.htm."""
        try:
            r = self._session.get(
                f"{self._url}/cmHelpData.htm",
                timeout=15,
            )
            r.raise_for_status()
        except requests.RequestException:
            return {"manufacturer": "Arris", "model": "SB6141", "sw_version": ""}

        text = BeautifulSoup(r.text, "html.parser").get_text()

        model = ""
        firmware = ""
        vendor = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("Model Name:"):
                model = line.split(":", 1)[1].strip()
            elif line.startswith("Firmware Name:"):
                firmware = line.split(":", 1)[1].strip()
            elif line.startswith("Vendor Name:"):
                vendor = line.split(":", 1)[1].strip()

        return {
            "manufacturer": vendor or "Arris",
            "model": model or "SB6141",
            "sw_version": firmware,
        }

    def get_connection_info(self) -> ConnectionInfo:
        """Standalone modem, no connection info."""
        return {}

    def _parse_downstream(self, ds_table, cw_table) -> list[RawChannel]:
        return parse_sb6141_downstream(ds_table, cw_table).value

    def _parse_upstream(self, us_table) -> list[RawChannel]:
        return parse_sb6141_upstream(us_table).value

    @staticmethod
    def _extract_transposed_rows(table) -> list[tuple[str, list[str]]]:
        return extract_transposed_rows(table)

    @staticmethod
    def _get_row_values(rows: list[tuple[str, list[str]]], keyword: str) -> list[str]:
        return get_row_values(rows, keyword)

    @staticmethod
    def _extract_upstream_modulation(raw: str) -> str:
        return extract_upstream_modulation(raw)

    @staticmethod
    def _parse_freq_hz(freq_str: str) -> str:
        return hz_to_mhz(freq_str)

    @staticmethod
    def _parse_number(val_str: str) -> float:
        return parse_number(val_str)
