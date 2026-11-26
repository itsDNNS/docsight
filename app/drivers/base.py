"""Base class for modem drivers."""

from __future__ import annotations

import logging
from collections.abc import Callable

import requests

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

    def _login_with_reconnect(self, label: str, attempt: Callable[[], None], logger: logging.Logger) -> None:
        """Run ``attempt``, rebuilding ``self._session`` via ``self._new_session()`` once if the connection drops.

        Request errors become ``RuntimeError`` with the "<label> authentication failed"
        wording that the connection test classifies.
        """
        for retry in (False, True):
            try:
                return attempt()
            except requests.ConnectionError as exc:
                if retry:
                    raise RuntimeError(f"{label} authentication failed: connection refused after retry") from exc
                logger.warning("%s connection lost, retrying with fresh session", label)
                self._session.close()
                self._session = self._new_session()
            except requests.RequestException as exc:
                raise RuntimeError(f"{label} authentication failed: {exc}") from exc
