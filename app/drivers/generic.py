"""Generic driver for non-DOCSIS / no-modem mode."""

from __future__ import annotations

from .base import ModemDriver
from .formats.boundaries import parse_generic_no_docsis
from ..types import DocsisData, DeviceInfo, ConnectionInfo


class GenericDriver(ModemDriver):
    """No-op driver that returns empty but structurally valid data.

    Allows all modem-agnostic features (Speedtest, BQM, Smokeping,
    BNetzA, Weather, Journal) to work standalone.
    """

    FORMAT_FAMILIES = ("generic_no_docsis",)

    def login(self) -> None:
        pass

    def get_docsis_data(self) -> DocsisData:
        return parse_generic_no_docsis().value

    def get_device_info(self) -> DeviceInfo:
        return {
            "model": "Generic Router",
            "sw_version": "N/A",
            "manufacturer": "N/A",
        }

    def get_connection_info(self) -> ConnectionInfo:
        return {}
