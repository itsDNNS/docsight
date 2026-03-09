"""Netgear CM3000 driver for DOCSight.

The CM3000 is a standalone DOCSIS 3.1 cable modem by Netgear. It embeds
all channel data as pipe-delimited JavaScript variables on the
/DocsisStatus.htm page -- no HTML tables, no XHR calls.

Five JS functions each contain a ``var tagValueList = '...'`` string:
- InitDsTableTagValue()      -- DS SC-QAM (32 channels, 9 fields each)
- InitUsTableTagValue()      -- US ATDMA  (8 channels, 7 fields each)
- InitDsOfdmTableTagValue()  -- DS OFDM   (2 channels, 11 fields each)
- InitUsOfdmaTableTagValue() -- US OFDMA  (2 channels, 6 fields each)
- InitTagValue()             -- system/device info

Auth is HTTP Basic Auth (standard for Netgear Nighthawk modems).
"""

import logging
import re

import requests

from .base import ModemDriver

log = logging.getLogger("docsis.driver.cm3000")

_STATUS_PATH = "/DocsisStatus.htm"

# Match the single-quoted live tagValueList in each function.
# Commented-out examples use double quotes or /* */ blocks, so
# targeting single quotes skips them reliably.
_RE_DS_QAM = re.compile(
    r"function\s+InitDsTableTagValue\s*\(\)\s*\{[^}]*?"
    r"var\s+tagValueList\s*=\s*'([^']+)';",
    re.DOTALL,
)
_RE_US_ATDMA = re.compile(
    r"function\s+InitUsTableTagValue\s*\(\)\s*\{[^}]*?"
    r"var\s+tagValueList\s*=\s*'([^']+)';",
    re.DOTALL,
)
_RE_DS_OFDM = re.compile(
    r"function\s+InitDsOfdmTableTagValue\s*\(\)\s*\{[^}]*?"
    r"var\s+tagValueList\s*=\s*'([^']+)';",
    re.DOTALL,
)
_RE_US_OFDMA = re.compile(
    r"function\s+InitUsOfdmaTableTagValue\s*\(\)\s*\{[^}]*?"
    r"var\s+tagValueList\s*=\s*'([^']+)';",
    re.DOTALL,
)
_RE_SYS_INFO = re.compile(
    r"function\s+InitTagValue\s*\(\)\s*\{[^}]*?"
    r"var\s+tagValueList\s*=\s*'([^']+)';",
    re.DOTALL,
)
_LOGIN_MARKERS = (
    "login.htm",
    "login.html",
    "window.location.replace",
    "sessionstorage.getitem('privatekey')",
    "sessionstorage.getitem(\"privatekey\")",
)

# Fields per channel for each section (after the leading count value).
_DS_QAM_FIELDS = 9   # num|lock|mod|chID|freq|power|snr|corrErr|uncorrErr
_US_ATDMA_FIELDS = 7  # num|lock|type|chID|symbolRate|freq|power
_DS_OFDM_FIELDS = 11  # num|lock|profiles|chID|freq|power|snr|subcarriers|corrErr|uncorrErr|unknown
_US_OFDMA_FIELDS = 6  # num|lock|profiles|chID|freq|power


class CM3000Driver(ModemDriver):
    """Driver for Netgear CM3000 DOCSIS 3.1 cable modem.

    Authentication uses HTTP Basic Auth (IP-based session).
    DOCSIS data is extracted from JavaScript variables on /DocsisStatus.htm.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.auth = (user, password)
        self._status_html = None

    def login(self) -> None:
        """Establish session and verify DocsisStatus.htm is actually readable.

        Retries once with a fresh session if the modem drops a stale
        TCP connection (common after container restarts).
        """
        for attempt in range(2):
            try:
                r = self._session.get(f"{self._url}{_STATUS_PATH}", timeout=30)
                r.raise_for_status()
                self._ensure_status_page(r.text)
                self._status_html = r.text
                log.info("CM3000 auth OK")
                return
            except requests.ConnectionError:
                if attempt == 0:
                    log.warning("CM3000 connection lost, retrying with fresh session")
                    self._session.close()
                    self._session = requests.Session()
                    self._session.auth = (self._user, self._password)
                    self._status_html = None
                    continue
                raise RuntimeError("CM3000 authentication failed: connection refused after retry")
            except requests.RequestException as e:
                raise RuntimeError(f"CM3000 authentication failed: {e}")

    def get_docsis_data(self) -> dict:
        """Retrieve DOCSIS channel data from JavaScript on status page.

        Returns pre-split format so the analyzer correctly labels
        QAM channels as DOCSIS 3.0 and OFDM/OFDMA channels as 3.1.
        """
        html = self._fetch_status_page()

        ds30 = self._parse_ds_qam(html)
        us30 = self._parse_us_atdma(html)
        ds31 = self._parse_ds_ofdm(html)
        us31 = self._parse_us_ofdma(html)

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> dict:
        """Extract device info from InitTagValue()."""
        try:
            html = self._fetch_status_page()
            m = _RE_SYS_INFO.search(html)
            if not m:
                return {"manufacturer": "Netgear", "model": "CM3000", "sw_version": ""}

            fields = m.group(1).split("|")
            result = {
                "manufacturer": "Netgear",
                "model": "CM3000",
                "sw_version": "",
            }

            # Uptime is at index 14: "23 days 09:26:24"
            if len(fields) > 14:
                uptime = self._parse_uptime(fields[14])
                if uptime is not None:
                    result["uptime_seconds"] = uptime

            return result
        except Exception:
            return {"manufacturer": "Netgear", "model": "CM3000", "sw_version": ""}

    def get_connection_info(self) -> dict:
        """Standalone modem -- no connection info available."""
        return {}

    # -- Internal helpers --

    def _fetch_status_page(self) -> str:
        """Fetch the raw HTML of /DocsisStatus.htm.

        Reuses the validated HTML captured during login when available.
        """
        if self._status_html is not None:
            html = self._status_html
            self._status_html = None
            return html

        try:
            r = self._session.get(
                f"{self._url}{_STATUS_PATH}",
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"CM3000 status page retrieval failed: {e}")
        self._ensure_status_page(r.text)
        return r.text

    @staticmethod
    def _ensure_status_page(html: str) -> None:
        """Reject login/placeholder pages that would otherwise parse as zero channels."""
        if not html:
            raise RuntimeError("CM3000 returned an empty status page")

        lower_html = html.lower()
        if any(marker in lower_html for marker in _LOGIN_MARKERS):
            raise RuntimeError(
                "CM3000 authentication failed: modem returned a login page instead "
                "of DocsisStatus.htm after authentication"
            )

        has_sys_info = _RE_SYS_INFO.search(html) is not None
        has_channel_data = any(
            regex.search(html) for regex in (_RE_DS_QAM, _RE_US_ATDMA, _RE_DS_OFDM, _RE_US_OFDMA)
        )
        if not has_sys_info or not has_channel_data:
            raise RuntimeError(
                "CM3000 status page did not contain the expected DOCSIS data blocks"
            )

    # -- Channel parsers --

    def _parse_ds_qam(self, html: str) -> list:
        """Parse downstream SC-QAM channels from InitDsTableTagValue().

        Per channel (9 fields):
        num | lock | modulation | channelID | frequency | power | snr | corrErrors | uncorrErrors
        """
        m = _RE_DS_QAM.search(html)
        if not m:
            return []

        channels = self._split_channels(m.group(1), _DS_QAM_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "frequency": self._hz_to_mhz(ch[4]),
                    "powerLevel": float(ch[5]),
                    "mer": float(ch[6]),
                    "mse": -float(ch[6]),
                    "modulation": self._normalize_modulation(ch[2]),
                    "corrErrors": int(ch[7]),
                    "nonCorrErrors": int(ch[8]),
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 DS QAM channel: %s", e)
        return result

    def _parse_us_atdma(self, html: str) -> list:
        """Parse upstream ATDMA channels from InitUsTableTagValue().

        Per channel (7 fields):
        num | lock | type | channelID | symbolRate | frequency | power
        """
        m = _RE_US_ATDMA.search(html)
        if not m:
            return []

        channels = self._split_channels(m.group(1), _US_ATDMA_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "frequency": self._hz_to_mhz(ch[5]),
                    "powerLevel": self._parse_number(ch[6]),
                    "modulation": self._normalize_modulation(ch[2]),
                    "multiplex": ch[2].upper() if ch[2] else "",
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 US ATDMA channel: %s", e)
        return result

    def _parse_ds_ofdm(self, html: str) -> list:
        """Parse downstream OFDM channels from InitDsOfdmTableTagValue().

        Per channel (11 fields):
        num | lock | profiles | channelID | frequency | power | snr | subcarriers | corrErrors | uncorrErrors | unknown
        """
        m = _RE_DS_OFDM.search(html)
        if not m:
            return []

        channels = self._split_channels(m.group(1), _DS_OFDM_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "type": "OFDM",
                    "frequency": self._hz_to_mhz(ch[4]),
                    "powerLevel": self._parse_number(ch[5]),
                    "mer": self._parse_number(ch[6]),
                    "mse": None,
                    "corrErrors": int(ch[8]),
                    "nonCorrErrors": int(ch[9]),
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 DS OFDM channel: %s", e)
        return result

    def _parse_us_ofdma(self, html: str) -> list:
        """Parse upstream OFDMA channels from InitUsOfdmaTableTagValue().

        Per channel (6 fields):
        num | lock | profiles | channelID | frequency | power
        """
        m = _RE_US_OFDMA.search(html)
        if not m:
            return []

        channels = self._split_channels(m.group(1), _US_OFDMA_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "type": "OFDMA",
                    "frequency": self._hz_to_mhz(ch[4]),
                    "powerLevel": self._parse_number(ch[5]),
                    "modulation": "OFDMA",
                    "multiplex": "",
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 US OFDMA channel: %s", e)
        return result

    # -- Value parsers --

    @staticmethod
    def _split_channels(raw: str, fields_per_channel: int) -> list[list[str]]:
        """Split a pipe-delimited tagValueList into per-channel field lists.

        The first value is the channel count, followed by repeating groups
        of ``fields_per_channel`` fields.
        """
        parts = raw.split("|")
        # First element is the count -- skip it
        data = parts[1:]
        # Remove trailing empty element from trailing pipe
        if data and data[-1] == "":
            data = data[:-1]

        channels = []
        for i in range(0, len(data), fields_per_channel):
            chunk = data[i : i + fields_per_channel]
            if len(chunk) == fields_per_channel:
                channels.append(chunk)
        return channels

    @staticmethod
    def _hz_to_mhz(freq_str: str) -> str:
        """Convert frequency string from Hz to MHz format.

        '495000000 Hz' -> '495 MHz'
        '0' -> '0 MHz'
        """
        parts = freq_str.strip().split()
        try:
            hz = float(parts[0])
            mhz = hz / 1_000_000
            # Use int if it's a whole number, otherwise one decimal
            if mhz == int(mhz):
                return f"{int(mhz)} MHz"
            return f"{mhz:.1f} MHz"
        except (ValueError, IndexError):
            return freq_str

    @staticmethod
    def _parse_number(value: str) -> float:
        """Parse numeric value from string with optional unit suffix.

        '43.3 dBmV' -> 43.3
        '-0.32 dBmV' -> -0.32
        '41.8 dB' -> 41.8
        """
        if not value:
            return 0.0
        parts = value.strip().split()
        try:
            return float(parts[0])
        except (ValueError, IndexError):
            return 0.0

    @staticmethod
    def _normalize_modulation(mod: str) -> str:
        """Normalize modulation string.

        'QAM256' -> 'QAM256'
        'ATDMA' -> 'ATDMA'
        We preserve the original format since the CM3500 driver does the same.
        """
        return mod.strip() if mod else ""

    @staticmethod
    def _parse_uptime(uptime_str: str) -> int | None:
        """Parse uptime string to seconds.

        '23 days 09:26:24' -> 2020784
        """
        m = re.match(r"(\d+)\s+days?\s+(\d+):(\d+):(\d+)", uptime_str.strip())
        if m:
            return (
                int(m.group(1)) * 86400
                + int(m.group(2)) * 3600
                + int(m.group(3)) * 60
                + int(m.group(4))
            )
        return None
