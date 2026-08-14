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

from __future__ import annotations

import logging
import time

import requests

from .base import ModemDriver
from .formats.hitron import (
    parse_coda56_ds_ofdm,
    parse_coda56_ds_scqam,
    parse_coda56_us_ofdma,
    parse_coda56_us_scqam,
    parse_hitron_coda56_json,
    parse_hitron_ofdma_power,
)
from .formats.primitives import hz_to_mhz
from .format_compat import unwrap_hitron
from ..types import DocsisData, DeviceInfo, ConnectionInfo, RawChannel
from .utils import make_legacy_tls_adapter

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


class HitronDriver(ModemDriver):
    """Driver for Hitron CODA DOCSIS 3.1 cable modems.

    No authentication required.  All data is fetched as JSON arrays from
    ASP endpoints with a cache-buster query parameter.
    """

    FORMAT_FAMILIES = ("hitron_coda56_json",)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False
        self._session.mount("https://", make_legacy_tls_adapter(sec_level=1))
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

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from all four endpoints."""
        return parse_hitron_coda56_json({
            "downstream": self._fetch_json("/data/dsinfo.asp"),
            "upstream": self._fetch_json("/data/usinfo.asp"),
            "downstream_ofdm": self._fetch_json("/data/dsofdminfo.asp"),
            "upstream_ofdma": self._fetch_json("/data/usofdminfo.asp"),
        }).value

    def get_device_info(self) -> DeviceInfo:
        """Return static device info (model not available via API)."""
        return {
            "manufacturer": "Hitron",
            "model": "CODA-56",
            "sw_version": "",
        }

    def get_connection_info(self) -> ConnectionInfo:
        """Hitron CODA is a standalone modem — no connection info."""
        return {}

    # -- Data fetchers --

    def _fetch_json(self, path: str) -> list[dict[str, str]]:
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

    def _fetch_ds_scqam(self) -> list[RawChannel]:
        return parse_coda56_ds_scqam(self._fetch_json("/data/dsinfo.asp")).value

    def _fetch_us_scqam(self) -> list[RawChannel]:
        return parse_coda56_us_scqam(self._fetch_json("/data/usinfo.asp")).value

    def _fetch_ds_ofdm(self) -> list[RawChannel]:
        return parse_coda56_ds_ofdm(self._fetch_json("/data/dsofdminfo.asp")).value

    def _fetch_us_ofdma(self) -> list[RawChannel]:
        return unwrap_hitron(parse_coda56_us_ofdma(self._fetch_json("/data/usofdminfo.asp")), log)

    @staticmethod
    def _ofdma_power_1_6(row: dict[str, str]) -> float | None:
        return parse_hitron_ofdma_power(row)

    @staticmethod
    def _cache_bust() -> str:
        return str(int(time.time() * 1000))

    @staticmethod
    def _hz_to_mhz(hz_str: str) -> str:
        return hz_to_mhz(hz_str)
