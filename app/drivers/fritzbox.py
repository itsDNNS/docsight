"""FritzBox driver — wraps the existing fritzbox module."""

from __future__ import annotations

import logging

from .base import ModemDriver
from .formats.fritzbox import parse_fritzbox_data_lua
from ..types import DocsisData, DeviceInfo, ConnectionInfo
from .. import fritzbox as fb

log = logging.getLogger("docsis.driver.fritzbox")

class FritzBoxDriver(ModemDriver):
    """Driver for AVM FritzBox cable modems.

    Manages SID-based authentication. The SID is refreshed on every
    login() call to avoid session expiry issues.
    """

    FORMAT_FAMILIES = ("fritzbox_data_lua",)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._sid: str | None = None

    def login(self) -> None:
        self._sid = fb.login(self._url, self._user, self._password)

    def get_docsis_data(self) -> DocsisData:
        return parse_fritzbox_data_lua(fb.get_docsis_data(self._url, self._sid)).value

    @staticmethod
    def _compensate_us31_power(data: DocsisData) -> None:
        data.update(parse_fritzbox_data_lua(data).value)

    def get_device_info(self) -> DeviceInfo:
        info = fb.get_device_info(self._url, self._sid)
        info.setdefault("manufacturer", "AVM")
        return info

    def get_connection_info(self) -> ConnectionInfo:
        return fb.get_connection_info(self._url, self._sid)
