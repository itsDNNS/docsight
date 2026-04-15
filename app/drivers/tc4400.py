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
from ..types import DocsisData, DeviceInfo, ConnectionInfo, RawChannel

log = logging.getLogger("docsis.driver.tc4400")


class TC4400Driver(ModemDriver):
    """Driver for Technicolor TC4400 DOCSIS 3.1 cable modem.

    Authentication uses HTTP Basic Auth. DOCSIS data is scraped from
    HTML tables (no JSON API available). Response time can be ~20s.
    """

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
        """Parse downstream HTML table (SC-QAM + OFDM channels)."""
        rows = table.find_all("tr")
        if not rows:
            return []

        header_row = self._find_header_row(rows)
        if header_row is None:
            return []

        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        col = self._map_columns(headers)

        result = []
        data_rows = [r for r in rows if r != header_row]
        for row in data_rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 4:
                continue

            lock = self._cell(cells, col["lock_status"])
            if lock.lower() != "locked":
                continue

            try:
                channel_id = self._cell(cells, col["channel_id"], "0")
                
                # Use channel_type (OFDM/SC-QAM) for type, modulation as fallback
                channel_type = self._cell(cells, col["channel_type"], "")
                modulation = self._normalize_modulation(
                    self._cell(cells, col["modulation"])
                )
                
                # For OFDM channels, channel_type gives us OFDM vs SC-QAM
                # For SC-QAM, modulation gives us qam_256 etc.
                if channel_type.upper() in ("OFDM",):
                    final_type = "ofdm"
                elif channel_type.upper() in ("SC-QAM",):
                    final_type = modulation if modulation else "qam"
                else:
                    final_type = modulation if modulation else "unknown"
                
                frequency = self._parse_frequency(
                    self._cell(cells, col["frequency"])
                )
                power = self._parse_number(self._cell(cells, col["power"]))
                snr = self._parse_number(self._cell(cells, col["snr"]))
                corr = int(self._parse_number(self._cell(cells, col["corrected"])))
                uncorr = int(
                    self._parse_number(self._cell(cells, col["uncorrected"]))
                )

                is_ofdm = final_type == "ofdm"

                result.append({
                    "channelID": channel_id,
                    "type": final_type,
                    "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": power,
                    "mse": None if is_ofdm else (-snr if snr else None),
                    "mer": snr if snr else None,
                    "latency": 0,
                    "corrError": corr,
                    "nonCorrError": uncorr,
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse TC4400 DS row: %s", e)

        return result

    def _parse_upstream(self, table) -> list[RawChannel]:
        """Parse upstream HTML table (ATDMA + OFDMA channels)."""
        rows = table.find_all("tr")
        if not rows:
            return []

        header_row = self._find_header_row(rows)
        if header_row is None:
            return []

        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        col = self._map_columns(headers)

        result = []
        data_rows = [r for r in rows if r != header_row]
        for row in data_rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 4:
                continue

            lock = self._cell(cells, col["lock_status"])
            if lock.lower() != "locked":
                continue

            try:
                channel_id = self._cell(cells, col["channel_id"], "0")
                modulation = self._normalize_modulation(
                    self._cell(cells, col["modulation"])
                )
                frequency = self._parse_frequency(
                    self._cell(cells, col["frequency"])
                )
                power = self._parse_number(self._cell(cells, col["power"]))

                result.append({
                    "channelID": channel_id,
                    "type": modulation,
                    "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": power,
                    "multiplex": "",
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse TC4400 US row: %s", e)

        return result

    @staticmethod
    def _find_header_row(rows):
        """Find the actual header row, skipping title rows with colspan."""
        for row in rows:
            cells = row.find_all(["th", "td"])
            if cells and any(cell.get("colspan") for cell in cells):
                continue
            if cells and len(cells) > 3:
                return row
        return None

    def _map_columns(self, headers: list[str]) -> dict[str, int | None]:
        """Map header names to column indices.

        Uses fuzzy matching to handle firmware variations like
        "Received Level" vs "Receive Level", "Channel ID" vs "Channel Index",
        "Channel Type" vs "Modulation / Profile ID".
        """
        col = {
            "channel_id": None,
            "lock_status": None,
            "modulation": None,
            "channel_type": None,
            "frequency": None,
            "power": None,
            "snr": None,
            "corrected": None,
            "uncorrected": None,
        }

        for i, h in enumerate(headers):
            if "channel" in h and ("id" in h or "index" in h):
                col["channel_id"] = i
            elif "lock" in h:
                col["lock_status"] = i
            elif "channel" in h and "type" in h:
                col["channel_type"] = i
            elif "modulation" in h or "profile" in h:
                col["modulation"] = i
            elif "freq" in h:
                col["frequency"] = i
            elif any(kw in h for kw in ("power", "receive", "transmit")):
                col["power"] = i
            elif "snr" in h or "mer" in h:
                col["snr"] = i
            elif "corrected" in h and "un" not in h:
                col["corrected"] = i
            elif "uncorrect" in h:
                col["uncorrected"] = i

        # Positional fallbacks for common TC4400 table layout
        if col["channel_id"] is None:
            col["channel_id"] = 0
        if col["lock_status"] is None:
            col["lock_status"] = 1
        if col["channel_type"] is None and col["modulation"] is None:
            col["modulation"] = 2
        if col["frequency"] is None:
            col["frequency"] = 3

        return col

    @staticmethod
    def _cell(cells: list[str], index: int | None, default: str = "") -> str:
        """Safely get a cell value by index."""
        if index is None or index >= len(cells):
            return default
        return cells[index]

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
        """Parse frequency string to MHz float.

        Handles: "279000000 Hz", "350000 kHz", "279 MHz"
        Note: Returns float (MHz), not a string. TC4400 formats
        the result itself in _parse_downstream/_parse_upstream.
        """
        if not freq_str:
            return 0.0

        parts = freq_str.strip().split()
        try:
            value = float(parts[0])
        except (IndexError, ValueError):
            return 0.0

        unit = parts[1].lower() if len(parts) > 1 else ""
        if unit == "hz":
            return value / 1_000_000
        elif unit == "khz":
            return value / 1_000
        elif unit == "mhz":
            return value
        elif value > 1_000_000:
            return value / 1_000_000
        elif value > 1_000:
            return value / 1_000
        return value

    @staticmethod
    def _parse_number(value: str) -> float:
        from .utils import parse_number
        return parse_number(value)

    @staticmethod
    def _normalize_modulation(modulation: str) -> str:
        """Normalize modulation string to analyzer format.

        Input: "256QAM", "OFDM", "ATDMA", "OFDMA"
        Output: "qam_256", "ofdm", "atdma", "ofdma"
        """
        if not modulation:
            return ""
        mod = modulation.upper().replace("-", "")
        if "OFDMA" in mod:
            return "ofdma"
        if "OFDM" in mod:
            return "ofdm"
        if "ATDMA" in mod:
            return "atdma"
        if "QAM" in mod:
            num = mod.replace("QAM", "").strip()
            return f"qam_{num}" if num else "qam"
        return modulation.lower()
