"""Arris/Motorola SB6141 driver for DOCSight.

The SB6141 is a DOCSIS 3.0 cable modem with a simple HTML web UI and no
authentication. Channel data is on /cmSignalData.htm in transposed tables
(metrics as rows, channels as columns). Error counters are in a separate
"Signal Status (Codewords)" table on the same page.

Device info is on /cmHelpData.htm as plain text with <BR> separators.

This driver may also work with other Motorola/Arris SB6xxx modems
(SB6121, SB6183) that share the same web UI format.
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import ModemDriver

log = logging.getLogger("docsis.driver.sb6141")

# SB6141 sends malformed HTTP headers (space before colon in Cache-Control),
# which triggers noisy urllib3 HeaderParsingError warnings on every request.
logging.getLogger("urllib3.connection").setLevel(logging.ERROR)


class SB6141Driver(ModemDriver):
    """Driver for Arris/Motorola SB6141 DOCSIS 3.0 cable modem.

    No authentication required. DOCSIS data is scraped from transposed
    HTML tables where each row is a metric and each column is a channel.
    """

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

    def get_docsis_data(self) -> dict:
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

    def get_device_info(self) -> dict:
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

    def get_connection_info(self) -> dict:
        """Standalone modem, no connection info."""
        return {}

    # -- Transposed table parsers --

    def _parse_downstream(self, ds_table, cw_table) -> list:
        """Parse transposed downstream + codewords tables.

        In the SB6141 tables, each row is a metric and each column is a
        channel. The first cell of each row is the metric label.
        """
        if not ds_table:
            return []

        ds_rows = self._extract_transposed_rows(ds_table)
        channel_ids = self._get_row_values(ds_rows, "channel id")
        frequencies = self._get_row_values(ds_rows, "frequency")
        snrs = self._get_row_values(ds_rows, "signal to noise")
        modulations = self._get_row_values(ds_rows, "modulation")
        powers = self._get_row_values(ds_rows, "power level")

        # Get error counts from codewords table
        corrected = []
        uncorrected = []
        if cw_table:
            cw_rows = self._extract_transposed_rows(cw_table)
            corrected = self._get_row_values(cw_rows, "correctable")
            uncorrected = self._get_row_values(cw_rows, "uncorrectable")

        num_channels = len(channel_ids)
        result = []

        for i in range(num_channels):
            try:
                channel_id = int(channel_ids[i])
                freq = self._parse_freq_hz(frequencies[i] if i < len(frequencies) else "")
                snr = self._parse_number(snrs[i] if i < len(snrs) else "")
                power = self._parse_number(powers[i] if i < len(powers) else "")
                mod = modulations[i].strip() if i < len(modulations) else ""
                corr = int(self._parse_number(corrected[i])) if i < len(corrected) else 0
                uncorr = int(self._parse_number(uncorrected[i])) if i < len(uncorrected) else 0

                result.append({
                    "channelID": channel_id,
                    "frequency": freq,
                    "powerLevel": power,
                    "mer": snr,
                    "mse": -snr if snr else None,
                    "modulation": mod,
                    "corrErrors": corr,
                    "nonCorrErrors": uncorr,
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse SB6141 DS channel %d: %s", i, e)

        return result

    def _parse_upstream(self, us_table) -> list:
        """Parse transposed upstream table."""
        if not us_table:
            return []

        us_rows = self._extract_transposed_rows(us_table)
        channel_ids = self._get_row_values(us_rows, "channel id")
        frequencies = self._get_row_values(us_rows, "frequency")
        powers = self._get_row_values(us_rows, "power level")
        modulations = self._get_row_values(us_rows, "modulation")

        num_channels = len(channel_ids)
        result = []

        for i in range(num_channels):
            try:
                channel_id = int(channel_ids[i])
                freq = self._parse_freq_hz(frequencies[i] if i < len(frequencies) else "")
                power = self._parse_number(powers[i] if i < len(powers) else "")

                # Upstream modulation can have multiple BR-separated entries
                # like "[3] QPSK\n[3] 64QAM". Take the last (highest) one.
                raw_mod = modulations[i] if i < len(modulations) else ""
                mod = self._extract_upstream_modulation(raw_mod)

                result.append({
                    "channelID": channel_id,
                    "frequency": freq,
                    "powerLevel": power,
                    "modulation": mod,
                    "multiplex": "SC-QAM",
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse SB6141 US channel %d: %s", i, e)

        return result

    # -- Table helpers --

    @staticmethod
    def _extract_transposed_rows(table) -> list:
        """Extract rows from a transposed table.

        Returns list of (label, [values]) tuples, skipping the header row.
        TRs may be inside a TBODY element, so we search recursively.
        """
        rows = []
        for tr in table.find_all("tr"):
            # Skip header rows (contain TH elements)
            if tr.find("th"):
                continue
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            values = [td.get_text(strip=True) for td in cells[1:]]
            rows.append((label, values))
        return rows

    @staticmethod
    def _get_row_values(rows: list, keyword: str) -> list:
        """Find a row by keyword in the label and return its values."""
        keyword = keyword.lower()
        for label, values in rows:
            if keyword in label.lower():
                return values
        return []

    @staticmethod
    def _extract_upstream_modulation(raw: str) -> str:
        """Extract modulation from upstream field.

        Input may be "[3] QPSK [3] 64QAM" (BR tags become spaces).
        Returns the last/highest modulation without the bracket prefix.
        """
        if not raw:
            return ""
        # Split on common separators and find modulation entries
        parts = re.split(r'[\n\r]+', raw.strip())
        last_mod = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Remove bracket prefix like "[3] "
            cleaned = re.sub(r'^\[\d+\]\s*', '', part)
            if cleaned:
                last_mod = cleaned
        return last_mod

    # -- Value parsers --

    @staticmethod
    def _parse_freq_hz(freq_str: str) -> str:
        """Convert '465000000 Hz' to '465 MHz'."""
        if not freq_str:
            return ""
        parts = freq_str.strip().split()
        try:
            hz = float(parts[0])
            mhz = hz / 1_000_000
            if mhz == int(mhz):
                return f"{int(mhz)} MHz"
            return f"{mhz:.1f} MHz"
        except (ValueError, IndexError):
            return freq_str

    @staticmethod
    def _parse_number(val_str: str) -> float:
        """Parse '35 dB' or '3 dBmV' or '5.120 Msym/sec' to float."""
        if not val_str:
            return 0.0
        parts = val_str.strip().split()
        try:
            return float(parts[0])
        except (ValueError, IndexError):
            return 0.0
