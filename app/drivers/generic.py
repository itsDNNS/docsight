"""Generic driver for non-DOCSIS / no-modem mode."""

from .base import ModemDriver


class GenericDriver(ModemDriver):
    """No-op driver that returns empty but structurally valid data.

    Allows all modem-agnostic features (Speedtest, BQM, Smokeping,
    BNetzA, Weather, Journal) to work standalone.
    """

    def login(self) -> None:
        pass

    def get_docsis_data(self) -> dict:
        return {
            "channelDs": {"docsis30": [], "docsis31": []},
            "channelUs": {"docsis30": [], "docsis31": []},
        }

    def get_device_info(self) -> dict:
        return {
            "model": "Generic Router",
            "sw_version": "N/A",
            "manufacturer": "N/A",
        }

    def get_connection_info(self) -> dict:
        return {}
