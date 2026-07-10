"""Arris SB6183 driver for DOCSight.

The SB6183 is a DOCSIS 3.0 cable modem with a no-auth HTTP web UI.
Channel data is exposed on ``/RgConnect.asp`` as row-oriented downstream
and upstream bonded-channel tables. Device information is exposed on
``/RgSwInfo.asp``.
"""

from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup

from .base import ModemDriver
from .utils import hz_to_mhz, parse_number
from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel

log = logging.getLogger("docsis.driver.sb6183")


class SB6183Driver(ModemDriver):
    """Driver for Arris SB6183 DOCSIS 3.0 cable modem.

    No authentication is required. DOCSIS channel data is scraped from
    ``/RgConnect.asp`` and product information from ``/RgSwInfo.asp``.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = requests.Session()

    def login(self) -> None:
        """Verify modem is reachable (no auth required)."""
        try:
            r = self._session.get(f"{self._url}/RgConnect.asp", timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"SB6183 connection failed: {e}")
        if not self._is_status_page(r.text):
            raise RuntimeError("SB6183 connection failed: status page not returned")
        log.info("SB6183 reachable (no auth required)")

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from the status page."""
        try:
            r = self._session.get(f"{self._url}/RgConnect.asp", timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"SB6183 DOCSIS data retrieval failed: {e}")

        soup = BeautifulSoup(r.text, "html.parser")
        ds_table = us_table = None
        for table in soup.find_all("table"):
            th = table.find("th")
            if not th:
                continue
            text = th.get_text(" ", strip=True).lower()
            if "downstream bonded" in text:
                ds_table = table
            elif "upstream bonded" in text:
                us_table = table

        return {
            "channelDs": {"docsis30": self._parse_downstream(ds_table), "docsis31": []},
            "channelUs": {"docsis30": self._parse_upstream(us_table), "docsis31": []},
        }

    def get_device_info(self) -> DeviceInfo:
        """Retrieve device info from ``/RgSwInfo.asp``."""
        try:
            r = self._session.get(f"{self._url}/RgSwInfo.asp", timeout=15)
            r.raise_for_status()
        except requests.RequestException:
            return {"manufacturer": "Arris", "model": "SB6183", "sw_version": ""}

        soup = BeautifulSoup(r.text, "html.parser")
        info: dict[str, str] = {}
        model_tag = soup.find(id="thisModelNumberIs")
        model = model_tag.get_text(strip=True) if model_tag else ""

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True).lower()
            value = cells[1].get_text(" ", strip=True)
            if "software version" in label:
                info["sw_version"] = value
            elif "hardware version" in label:
                info["hw_version"] = value
            elif "standard specification" in label:
                info["docsis_status"] = value

        result: DeviceInfo = {
            "manufacturer": "Arris",
            "model": model or "SB6183",
            "sw_version": info.get("sw_version", ""),
        }
        if info.get("hw_version"):
            result["hw_version"] = info["hw_version"]
        if info.get("docsis_status"):
            result["docsis_status"] = info["docsis_status"]
        return result

    def get_connection_info(self) -> ConnectionInfo:
        """Standalone modem, no connection info."""
        return {}

    def _parse_downstream(self, table) -> list[RawChannel]:
        """Parse downstream table where each row is one channel."""
        if not table:
            return []
        result: list[RawChannel] = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) < 9 or not cells[3].isdigit() or cells[1].strip().lower() != "locked":
                continue
            try:
                snr = parse_number(cells[6])
                result.append({
                    "channelID": int(cells[3]),
                    "frequency": hz_to_mhz(cells[4]),
                    "powerLevel": parse_number(cells[5]),
                    "mer": snr,
                    "mse": -snr if snr else None,
                    "modulation": cells[2],
                    "corrErrors": int(parse_number(cells[7])),
                    "nonCorrErrors": int(parse_number(cells[8])),
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse SB6183 DS channel: %s", e)
        return result

    def _parse_upstream(self, table) -> list[RawChannel]:
        """Parse upstream table where each row is one channel."""
        if not table:
            return []
        result: list[RawChannel] = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) < 7 or not cells[3].isdigit() or cells[1].strip().lower() != "locked":
                continue
            try:
                result.append({
                    "channelID": int(cells[3]),
                    "frequency": hz_to_mhz(cells[5]),
                    "powerLevel": parse_number(cells[6]),
                    "modulation": cells[2],
                    "multiplex": cells[2],
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse SB6183 US channel: %s", e)
        return result

    @staticmethod
    def _is_status_page(html: str) -> bool:
        text = (html or "").lower()
        return "downstream bonded" in text and "upstream bonded" in text
