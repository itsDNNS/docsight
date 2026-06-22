"""Base class for modem drivers."""

from __future__ import annotations

from ..types import ConnectionInfo, DeviceInfo, DocsisData


class ModemDriver:
    """Shared initialization and documented API convention for modem drivers.

    Each driver manages its own authentication state (SID, cookies, etc.)
    and exposes a uniform interface for DOCSIS data access. The registry loads
    drivers by configured class path, so concrete driver behavior is validated
    when the collector calls these methods rather than at class definition time.
    """

    def __init__(self, url: str, user: str, password: str):
        self._url = url
        self._user = user
        self._password = password

    def login(self) -> None:
        """Authenticate with the modem. Called before each poll cycle."""
        raise NotImplementedError("ModemDriver.login")

    def get_docsis_data(self) -> DocsisData:
        """Retrieve raw DOCSIS channel data."""
        raise NotImplementedError("ModemDriver.get_docsis_data")

    def get_device_info(self) -> DeviceInfo:
        """Retrieve device model and firmware info."""
        raise NotImplementedError("ModemDriver.get_device_info")

    def get_connection_info(self) -> ConnectionInfo:
        """Retrieve internet connection info (speeds, type)."""
        raise NotImplementedError("ModemDriver.get_connection_info")
