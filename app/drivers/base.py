"""Base class for modem drivers."""

from abc import ABC, abstractmethod


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
    def get_docsis_data(self) -> dict:
        """Retrieve raw DOCSIS channel data."""
        ...

    @abstractmethod
    def get_device_info(self) -> dict:
        """Retrieve device model and firmware info."""
        ...

    @abstractmethod
    def get_connection_info(self) -> dict:
        """Retrieve internet connection info (speeds, type)."""
        ...
