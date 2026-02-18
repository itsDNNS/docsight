"""FritzBox driver — wraps the existing fritzbox module."""

import logging

from .base import ModemDriver
from .. import fritzbox as fb

log = logging.getLogger("docsis.driver.fritzbox")

# Fritz!Box displays DOCSIS 3.1 upstream power 6 dB lower than the actual
# value.  We compensate here so that the analyzer can use real VFKD thresholds
# that work identically for every modem.
_FRITZBOX_US31_POWER_OFFSET = 6.0


class FritzBoxDriver(ModemDriver):
    """Driver for AVM FritzBox cable modems.

    Manages SID-based authentication. The SID is refreshed on every
    login() call to avoid session expiry issues.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._sid: str | None = None

    def login(self) -> None:
        self._sid = fb.login(self._url, self._user, self._password)

    def get_docsis_data(self) -> dict:
        data = fb.get_docsis_data(self._url, self._sid)
        self._compensate_us31_power(data)
        return data

    @staticmethod
    def _compensate_us31_power(data: dict) -> None:
        """Add +6 dB to DOCSIS 3.1 upstream power to correct Fritz!Box display bug."""
        us31 = data.get("channelUs", {}).get("docsis31", [])
        for ch in us31:
            try:
                raw = float(ch.get("powerLevel", 0))
                ch["powerLevel"] = str(round(raw + _FRITZBOX_US31_POWER_OFFSET, 1))
            except (TypeError, ValueError):
                pass

    def get_device_info(self) -> dict:
        info = fb.get_device_info(self._url, self._sid)
        info.setdefault("manufacturer", "AVM")
        return info

    def get_connection_info(self) -> dict:
        return fb.get_connection_info(self._url, self._sid)
