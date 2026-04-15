"""Base class for modem drivers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import ConnectionInfo, DeviceInfo, DocsisData


class ModemDriver(ABC):
    """Abstract base class for modem data retrieval.

    Each driver manages its own authentication state (SID, cookies, etc.)
    and exposes a uniform interface for DOCSIS data access.
    """

    def __init__(self, url: str, user: str, password: str):
        self._url = url
        self._user = user
        self._password = password

    @abstractmethod
    def login(self) -> None:
        """Authenticate with the modem. Called before each poll cycle."""
        ...

    @abstractmethod
    def get_docsis_data(self) -> DocsisData:
        """Retrieve raw DOCSIS channel data."""
        ...

    @abstractmethod
    def get_device_info(self) -> DeviceInfo:
        """Retrieve device model and firmware info."""
        ...

    @abstractmethod
    def get_connection_info(self) -> ConnectionInfo:
        """Retrieve internet connection info (speeds, type)."""
        ...
