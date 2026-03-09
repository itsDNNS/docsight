"""Arris SB6190 driver for DOCSight.

DOCSIS 3.0 modem with HTTPS CGI interface. Authentication uses a
Base64-encoded credentials POST to /cgi-bin/adv_pwd_cgi with a random
CSRF nonce. Channel data is on /cgi-bin/status in standard (non-transposed)
HTML tables where each row is one channel. Device info is on /cgi-bin/swinfo.
"""

import base64
import logging
import random
import ssl
import urllib3
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from .base import ModemDriver

log = logging.getLogger("docsis.driver.sb6190")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _LegacyTLSAdapter(HTTPAdapter):
    """Allow weak DH keys for the SB6190's TLS configuration.

    The SB6190 ships with a certificate using a 1024 DH key that modern
    OpenSSL rejects by default. This adapter lowers the security level for
    connections to the modem only.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


class SB6190Driver(ModemDriver):
    """Driver for Arris SB6190 DOCSIS 3.0 cable modem.

    Uses HTTPS with a self-signed certificate. Authentication posts
    Base64-encoded credentials to /cgi-bin/adv_pwd_cgi. Channel data
    is scraped from /cgi-bin/status where each table row is one channel.
    """

    def __init__(self, url, user, password):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False
        adapter = _LegacyTLSAdapter()
        self._session.mount("https://", adapter)

    def login(self) -> None:
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
        log.info("SB6190 login OK")

    def get_docsis_data(self) -> dict:
        try:
            r = self._session.get(f"{self._url}/cgi-bin/status", timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"SB6190 DOCSIS data retrieval failed: {e}")

        soup = BeautifulSoup(r.text, "html.parser")
        ds_table = us_table = None
        for table in soup.find_all("table"):
            th = table.find("th")
            if not th:
                continue
            text = th.get_text(strip=True).lower()
            if "downstream bonded" in text:
                ds_table = table
            elif "upstream bonded" in text:
                us_table = table

        return {
            "channelDs": {"docsis30": self._parse_downstream(ds_table), "docsis31": []},
            "channelUs": {"docsis30": self._parse_upstream(us_table), "docsis31": []},
        }

    def get_device_info(self) -> dict:
        try:
            r = self._session.get(f"{self._url}/cgi-bin/swinfo", timeout=30)
            r.raise_for_status()
        except requests.RequestException:
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
        return {
            "manufacturer": "Arris",
            "model": "SB6190",
            "sw_version": info.get("sw_version", ""),
        }

    def get_connection_info(self) -> dict:
        return {}

    # -- Parsers --

    def _parse_downstream(self, table) -> list:
        """Parse downstream table: each row = one channel.

        Columns: Channel | Lock Status | Modulation | Channel ID |
                 Frequency | Power | SNR | Corrected | Uncorrectables
        """
        if not table:
            return []
        result = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 9 or not cells[3].isdigit():
                continue
            try:
                snr = self._parse_number(cells[6])
                result.append({
                    "channelID": int(cells[3]),
                    "frequency": self._normalize_mhz(cells[4]),
                    "powerLevel": self._parse_number(cells[5]),
                    "mer": snr,
                    "mse": -snr if snr else None,
                    "modulation": cells[2],
                    "corrErrors": int(self._parse_number(cells[7])),
                    "nonCorrErrors": int(self._parse_number(cells[8])),
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse SB6190 DS channel: %s", e)
        return result

    def _parse_upstream(self, table) -> list:
        """Parse upstream table: each row = one channel.

        Columns: Channel | Lock Status | US Channel Type | Channel ID |
                 Symbol Rate | Frequency | Power
        """
        if not table:
            return []
        result = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 7 or not cells[3].isdigit():
                continue
            try:
                result.append({
                    "channelID": int(cells[3]),
                    "frequency": self._normalize_mhz(cells[5]),
                    "powerLevel": self._parse_number(cells[6]),
                    "modulation": cells[2],
                    "multiplex": cells[2],
                })
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse SB6190 US channel: %s", e)
        return result

    # -- Value helpers --

    @staticmethod
    def _normalize_mhz(freq_str: str) -> str:
        """Normalize 'X.XX MHz' to 'X MHz' or 'X.Y MHz'."""
        parts = freq_str.strip().split()
        try:
            mhz = float(parts[0])
            if mhz == int(mhz):
                return f"{int(mhz)} MHz"
            return f"{mhz:.1f} MHz"
        except (ValueError, IndexError):
            return freq_str

    @staticmethod
    def _parse_number(val_str: str) -> float:
        """Parse '10.50 dBmV' or '40.95 dB' to float."""
        if not val_str:
            return 0.0
        try:
            return float(val_str.strip().split()[0])
        except (ValueError, IndexError):
            return 0.0
