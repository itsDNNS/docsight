"""FritzBox driver — wraps the existing fritzbox module."""

import logging

from .base import ModemDriver
from .. import fritzbox as fb

log = logging.getLogger("docsis.driver.fritzbox")


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
        return fb.get_docsis_data(self._url, self._sid)

    def get_device_info(self) -> dict:
        info = fb.get_device_info(self._url, self._sid)
        info.setdefault("manufacturer", "AVM")
        return info

    def get_connection_info(self) -> dict:
        return fb.get_connection_info(self._url, self._sid)
