from typing import Any, cast
from unittest.mock import MagicMock, patch

from app.analyzer import analyze
from app.drivers.vodafone_station import VodafoneStationDriver


def _driver_with_cga_payload(payload):
    driver = VodafoneStationDriver(url="http://dummy", user="admin", password="admin")
    response = MagicMock()
    response.json.return_value = {"error": "ok", "data": payload}
    return driver, response


def test_cga_ofdma_upstream_uses_fft_modulation_while_preserving_ofdma_family():
    driver, response = _driver_with_cga_payload({
        "ofdma_upstream": [
            {
                "channelidup": "6",
                "CentralFrequency": "51.0 MHz",
                "power": "43.2 dBmV",
                "ChannelType": "OFDMA",
                "FFT": "64-qam",
                "RangingStatus": "Completed",
            }
        ]
    })

    with patch.object(driver, "_cga_request", return_value=response):
        docsis_data = driver._get_docsis_cga()

    docsis_payload = cast(dict[str, Any], docsis_data)
    raw_channel = docsis_payload["channelUs"]["docsis31"][0]
    assert raw_channel["type"] == "OFDMA"
    assert raw_channel["modulation"] == "64QAM"

    analysis = cast(dict[str, Any], analyze(docsis_data))
    analyzed_channel = analysis["us_channels"][0]
    assert analyzed_channel["channel_family"] == "ofdma"
    assert analyzed_channel["modulation"] == "64QAM"


def test_cga_ofdma_upstream_falls_back_to_ofdma_when_fft_is_missing():
    driver, response = _driver_with_cga_payload({
        "ofdma_upstream": [
            {
                "channelidup": "6",
                "CentralFrequency": "51.0 MHz",
                "power": "43.2 dBmV",
                "ChannelType": "OFDMA",
            }
        ]
    })

    with patch.object(driver, "_cga_request", return_value=response):
        docsis_data = driver._get_docsis_cga()

    docsis_payload = cast(dict[str, Any], docsis_data)
    raw_channel = docsis_payload["channelUs"]["docsis31"][0]
    assert raw_channel["type"] == "OFDMA"
    assert raw_channel["modulation"] == "OFDMA"

    analysis = cast(dict[str, Any], analyze(docsis_data))
    analyzed_channel = analysis["us_channels"][0]
    assert analyzed_channel["channel_family"] == "ofdma"
    assert analyzed_channel["modulation"] == "OFDMA"
