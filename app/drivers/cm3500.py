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

import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import ModemDriver

log = logging.getLogger("docsis.driver.cm3500")


class CM3500Driver(ModemDriver):
    """Driver for Arris CM3500B DOCSIS 3.1 cable modem.

    Authentication uses form POST (IP-based session, no cookies).
    DOCSIS data is scraped from HTML tables.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False

    def login(self) -> None:
        """Authenticate via form POST to /cgi-bin/login_cgi."""
        try:
            r = self._session.post(
                f"{self._url}/cgi-bin/login_cgi",
                data={"username": self._user, "password": self._password},
                timeout=30,
            )
            r.raise_for_status()
            log.info("CM3500 auth OK")
        except requests.RequestException as e:
            raise RuntimeError(f"CM3500 authentication failed: {e}")

    def get_docsis_data(self) -> dict:
        """Retrieve DOCSIS channel data from HTML tables on status page."""
        soup = self._fetch_status_page()
        sections = self._find_table_sections(soup)

        downstream = []
        if "downstream qam" in sections:
            downstream.extend(self._parse_ds_qam(sections["downstream qam"]))
        if "downstream ofdm" in sections:
            downstream.extend(self._parse_ds_ofdm(sections["downstream ofdm"]))

        upstream = []
        if "upstream qam" in sections:
            upstream.extend(self._parse_us_qam(sections["upstream qam"]))
        if "upstream ofdm" in sections:
            upstream.extend(self._parse_us_ofdm(sections["upstream ofdm"]))

        return {
            "docsis": "3.1",
            "downstream": downstream,
            "upstream": upstream,
        }

    def get_device_info(self) -> dict:
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

    def get_connection_info(self) -> dict:
        """Not applicable for standalone modem."""
        return {}

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

    def _find_table_sections(self, soup) -> dict:
        """Map <h4> heading text to the following <table> element."""
        sections = {}
        for h4 in soup.find_all("h4"):
            heading = h4.get_text(strip=True).lower()
            table = h4.find_next_sibling("table")
            if table:
                sections[heading] = table
        return sections

    # -- Downstream parsers --

    def _parse_ds_qam(self, table) -> list:
        """Parse Downstream QAM table.

        Columns: (label), DCID, Freq, Power, SNR, Modulation, Octets,
                 Correcteds, Uncorrectables
        """
        rows = table.find_all("tr")
        if len(rows) < 2:
            return []

        result = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 9:
                continue
            try:
                result.append({
                    "channelID": int(self._parse_number(cells[1])),
                    "frequency": self._format_freq(cells[2]),
                    "powerLevel": self._parse_number(cells[3]),
                    "mse": -self._parse_number(cells[4]) if cells[4] else None,
                    "mer": self._parse_number(cells[4]) if cells[4] else None,
                    "modulation": cells[5],
                    "corrErrors": int(self._parse_number(cells[7])),
                    "nonCorrErrors": int(self._parse_number(cells[8])),
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse CM3500 DS QAM row: %s", e)
        return result

    def _parse_ds_ofdm(self, table) -> list:
        """Parse Downstream OFDM table.

        Columns: (label), FFT Type, Channel Width(MHz), # Active Subcarriers,
                 First Active Subcarrier(MHz), Last Active Subcarrier(MHz),
                 Average RxMER: Pilot, PLC, Data
        """
        rows = table.find("tbody")
        if not rows:
            return []
        data_rows = rows.find_all("tr")
        if not data_rows:
            return []

        result = []
        chan_id = 200
        for row in data_rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 8:
                continue
            label = cells[0].lower()
            if "downstream" not in label:
                continue
            try:
                first_freq = self._parse_number(cells[4])
                last_freq = self._parse_number(cells[5])
                mer_data = self._parse_number(cells[8]) if len(cells) > 8 else self._parse_number(cells[7])

                result.append({
                    "channelID": chan_id,
                    "type": "OFDM",
                    "frequency": f"{int(first_freq)}-{int(last_freq)} MHz",
                    "powerLevel": 0.0,
                    "mer": mer_data,
                    "mse": None,
                    "corrErrors": 0,
                    "nonCorrErrors": 0,
                })
                chan_id += 1
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse CM3500 DS OFDM row: %s", e)
        return result

    # -- Upstream parsers --

    def _parse_us_qam(self, table) -> list:
        """Parse Upstream QAM table.

        Columns: (label), UCID, Freq, Power, Channel Type, Symbol Rate, Modulation
        """
        rows = table.find_all("tr")
        if len(rows) < 2:
            return []

        result = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 7:
                continue
            try:
                channel_type = cells[4]
                multiplex = ""
                if "ATDMA" in channel_type.upper():
                    multiplex = "ATDMA"
                elif "TDMA" in channel_type.upper():
                    multiplex = "TDMA"

                result.append({
                    "channelID": int(self._parse_number(cells[1])),
                    "frequency": self._format_freq(cells[2]),
                    "powerLevel": self._parse_number(cells[3]),
                    "modulation": cells[6],
                    "multiplex": multiplex,
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse CM3500 US QAM row: %s", e)
        return result

    def _parse_us_ofdm(self, table) -> list:
        """Parse Upstream OFDM table.

        Columns: (label), FFT Type, Channel Width(MHz), # Active Subcarriers,
                 First Active Subcarrier(MHz), Last Active Subcarrier(MHz),
                 Tx Power(dBmV)
        """
        rows = table.find("tbody")
        if not rows:
            return []
        data_rows = rows.find_all("tr")

        result = []
        chan_id = 200
        for row in data_rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 7:
                continue
            label = cells[0].lower()
            if "upstream" not in label:
                continue
            try:
                first_freq = self._parse_number(cells[4])
                last_freq = self._parse_number(cells[5])
                power = self._parse_number(cells[6])

                result.append({
                    "channelID": chan_id,
                    "type": "OFDMA",
                    "frequency": f"{int(first_freq)}-{int(last_freq)} MHz",
                    "powerLevel": power,
                    "modulation": "OFDMA",
                    "multiplex": "",
                })
                chan_id += 1
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse CM3500 US OFDM row: %s", e)
        return result

    # -- Value parsers --

    @staticmethod
    def _parse_number(value: str) -> float:
        """Parse numeric value from string with optional unit suffix."""
        if not value:
            return 0.0
        parts = value.strip().split()
        try:
            return float(parts[0])
        except (ValueError, IndexError):
            return 0.0

    @staticmethod
    def _format_freq(freq_str: str) -> str:
        """Normalize frequency string to 'NNN MHz' format."""
        if not freq_str:
            return ""
        parts = freq_str.strip().split()
        try:
            mhz = float(parts[0])
            return f"{int(mhz)} MHz"
        except (ValueError, IndexError):
            return freq_str
