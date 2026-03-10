"""Hitron CODA modem driver for DOCSight.

The Hitron CODA-56 (and likely other CODA models) is a DOCSIS 3.1 cable modem
with a Backbone.js web UI.  Channel data is served as JSON from four ASP
endpoints — no authentication required.

Endpoints:
- /data/dsinfo.asp      — DS SC-QAM channels (DOCSIS 3.0)
- /data/usinfo.asp      — US SC-QAM channels (DOCSIS 3.0)
- /data/dsofdminfo.asp  — DS OFDM channels (DOCSIS 3.1)
- /data/usofdminfo.asp  — US OFDMA channels (DOCSIS 3.1)
- /data/getCMInit.asp   — Provisioning status
"""

import logging
import ssl
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from .base import ModemDriver

log = logging.getLogger("docsis.driver.hitron")

_DS_MODULATION = {
    0: "16QAM",
    1: "64QAM",
    2: "256QAM",
    3: "1024QAM",
    4: "32QAM",
    5: "128QAM",
    6: "QPSK",
}


class _LegacyTLSAdapter(HTTPAdapter):
    """Allow weak certificate keys for CODA modems that use HTTPS.

    Some CODA-56 units serve HTTPS with certificates using short keys
    that modern OpenSSL rejects by default.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


class HitronDriver(ModemDriver):
    """Driver for Hitron CODA DOCSIS 3.1 cable modems.

    No authentication required.  All data is fetched as JSON arrays from
    ASP endpoints with a cache-buster query parameter.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False
        self._session.mount("https://", _LegacyTLSAdapter())
        self._session.timeout = 30

    def login(self) -> None:
        """No authentication required — verify connectivity."""
        try:
            r = self._session.get(
                f"{self._url}/data/getCMInit.asp?_={self._cache_bust()}",
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            if data and data[0].get("networkAccess") == "Permitted":
                log.info("Hitron connectivity OK")
            else:
                log.warning("Hitron reachable but network access not permitted")
        except requests.RequestException as e:
            raise RuntimeError(f"Hitron connection failed: {e}")

    def get_docsis_data(self) -> dict:
        """Retrieve DOCSIS channel data from all four endpoints."""
        ds30 = self._fetch_ds_scqam()
        us30 = self._fetch_us_scqam()
        ds31 = self._fetch_ds_ofdm()
        us31 = self._fetch_us_ofdma()

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> dict:
        """Return static device info (model not available via API)."""
        return {
            "manufacturer": "Hitron",
            "model": "CODA-56",
            "sw_version": "",
        }

    def get_connection_info(self) -> dict:
        """Hitron CODA is a standalone modem — no connection info."""
        return {}

    # -- Data fetchers --

    def _fetch_json(self, path: str) -> list:
        """Fetch a JSON array from an ASP endpoint."""
        try:
            r = self._session.get(
                f"{self._url}{path}?_={self._cache_bust()}",
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.warning("Hitron fetch %s failed: %s", path, e)
            return []

    def _fetch_ds_scqam(self) -> list:
        """Parse downstream SC-QAM channels (DOCSIS 3.0)."""
        channels = []
        for ch in self._fetch_json("/data/dsinfo.asp"):
            try:
                mod_code = int(ch.get("modulation", -1))
                modulation = _DS_MODULATION.get(mod_code, f"Unknown({mod_code})")
                channels.append({
                    "channelID": int(ch["channelId"]),
                    "frequency": self._hz_to_mhz(ch["frequency"]),
                    "powerLevel": float(ch["signalStrength"]),
                    "modulation": modulation,
                    "mer": float(ch["snr"]),
                    "mse": -float(ch["snr"]),
                    "corrErrors": int(ch["correcteds"]),
                    "nonCorrErrors": int(ch["uncorrect"]),
                })
            except (ValueError, KeyError, TypeError) as e:
                log.warning("Failed to parse Hitron DS row: %s", e)
        return channels

    def _fetch_us_scqam(self) -> list:
        """Parse upstream SC-QAM channels (DOCSIS 3.0)."""
        channels = []
        for ch in self._fetch_json("/data/usinfo.asp"):
            try:
                channels.append({
                    "channelID": int(ch["channelId"]),
                    "frequency": self._hz_to_mhz(ch["frequency"]),
                    "powerLevel": float(ch["signalStrength"]),
                    "modulation": ch.get("modtype", ""),
                    "multiplex": ch.get("scdmaMode", ""),
                })
            except (ValueError, KeyError, TypeError) as e:
                log.warning("Failed to parse Hitron US row: %s", e)
        return channels

    def _fetch_ds_ofdm(self) -> list:
        """Parse downstream OFDM channels (DOCSIS 3.1)."""
        channels = []
        for ch in self._fetch_json("/data/dsofdminfo.asp"):
            try:
                plc_lock = ch.get("plclock", "").strip().upper()
                if plc_lock != "YES":
                    continue
                channels.append({
                    "channelID": int(ch["receive"]),
                    "type": "OFDM",
                    "frequency": self._hz_to_mhz(ch.get("Subcarr0freqFreq", "0")),
                    "powerLevel": float(ch["plcpower"]),
                    "modulation": "OFDM",
                    "mer": float(ch["SNR"]),
                    "mse": None,
                    "corrErrors": int(ch["correcteds"]),
                    "nonCorrErrors": int(ch["uncorrect"]),
                })
            except (ValueError, KeyError, TypeError) as e:
                log.warning("Failed to parse Hitron DS OFDM row: %s", e)
        return channels

    def _fetch_us_ofdma(self) -> list:
        """Parse upstream OFDMA channels (DOCSIS 3.1)."""
        channels = []
        for ch in self._fetch_json("/data/usofdminfo.asp"):
            try:
                state = ch.get("state", "").strip().upper()
                if state != "OPERATE":
                    continue
                channels.append({
                    "channelID": int(ch["uschindex"]),
                    "type": "OFDMA",
                    "frequency": self._hz_to_mhz(ch.get("frequency", "0")),
                    "powerLevel": float(ch["repPower"]),
                    "modulation": "OFDMA",
                    "multiplex": "",
                })
            except (ValueError, KeyError, TypeError) as e:
                log.warning("Failed to parse Hitron US OFDMA row: %s", e)
        return channels

    # -- Helpers --

    @staticmethod
    def _cache_bust() -> str:
        return str(int(time.time() * 1000))

    @staticmethod
    def _hz_to_mhz(hz_str: str) -> str:
        """Convert '591000000' to '591 MHz'."""
        try:
            hz = float(str(hz_str).strip())
            mhz = hz / 1_000_000
            if mhz == int(mhz):
                return f"{int(mhz)} MHz"
            return f"{mhz:.1f} MHz"
        except (ValueError, TypeError):
            return str(hz_str)
