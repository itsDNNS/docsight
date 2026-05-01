"""Regression tests for driver modulation normalization."""

from unittest.mock import patch

from bs4 import BeautifulSoup

import pytest

from app.drivers.ch7465 import CH7465Driver
from app.drivers.tc4400 import TC4400Driver
from app.drivers.vodafone_station import VodafoneStationDriver
from app.drivers.utils import normalize_modulation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        (" 256QAM ", "256QAM"),
        ("256qam", "256QAM"),
        ("256-qam", "256QAM"),
        ("256 qam", "256QAM"),
        ("qam256", "256QAM"),
        ("qam_256", "256QAM"),
        ("64 qam", "64QAM"),
        ("4096-qam", "4096QAM"),
        ("qpsk", "QPSK"),
        ("ofdm", "OFDM"),
        ("ofdma", "OFDMA"),
        ("atdma", "ATDMA"),
        ("tdma", "TDMA"),
        ("mystery mode", "MYSTERY MODE"),
    ],
)
def test_shared_modulation_normalization(raw, expected):
    assert normalize_modulation(raw) == expected


@pytest.mark.parametrize("driver", [CH7465Driver, TC4400Driver, VodafoneStationDriver])
def test_driver_helpers_use_canonical_modulation_labels(driver):
    assert driver._normalize_modulation("256-qam") == "256QAM"
    assert driver._normalize_modulation("64 qam") == "64QAM"
    assert driver._normalize_modulation("qpsk") == "QPSK"
    assert driver._normalize_modulation("ofdm") == "OFDM"
    assert driver._normalize_modulation("ofdma") == "OFDMA"


def test_tc4400_downstream_ofdm_type_is_uppercase():
    table = BeautifulSoup(
        """
        <table>
          <tr>
            <th>Channel ID</th><th>Lock Status</th><th>Channel Type</th>
            <th>Modulation</th><th>Frequency</th><th>Power</th><th>SNR</th>
            <th>Corrected</th><th>Uncorrected</th>
          </tr>
          <tr>
            <td>193</td><td>Locked</td><td>OFDM</td><td></td>
            <td>957000000 Hz</td><td>0.1 dBmV</td><td>43.0 dB</td>
            <td>7</td><td>0</td>
          </tr>
        </table>
        """,
        "html.parser",
    ).find("table")

    driver = TC4400Driver("http://192.168.100.1", "user", "pass")
    channels = driver._parse_downstream(table)

    assert channels[0]["type"] == "OFDM"
    assert channels[0]["mse"] is None


def test_tc4400_downstream_sc_qam_type_is_canonical():
    table = BeautifulSoup(
        """
        <table>
          <tr>
            <th>Channel ID</th><th>Lock Status</th><th>Channel Type</th>
            <th>Modulation</th><th>Frequency</th><th>Power</th><th>SNR</th>
            <th>Corrected</th><th>Uncorrected</th>
          </tr>
          <tr>
            <td>1</td><td>Locked</td><td>SC-QAM</td><td>256-qam</td>
            <td>602000000 Hz</td><td>2.0 dBmV</td><td>39.5 dB</td>
            <td>1</td><td>0</td>
          </tr>
        </table>
        """,
        "html.parser",
    ).find("table")

    driver = TC4400Driver("http://192.168.100.1", "user", "pass")
    channels = driver._parse_downstream(table)

    assert channels[0]["type"] == "256QAM"
    assert channels[0]["mse"] == -39.5


def test_vodafone_cga_docsis31_types_are_uppercase():
    class Response:
        def json(self):
            return {
                "data": {
                    "downstream": [],
                    "upstream": [],
                    "ofdm_downstream": [
                        {
                            "channelid_ofdm": "193",
                            "CentralFrequency_ofdm": "957000000",
                            "power_ofdm": "0.1",
                            "SNR_ofdm": "43.0",
                        }
                    ],
                    "ofdma_upstream": [
                        {
                            "channelidup": "41",
                            "CentralFrequency": "36200000",
                            "power": "43.8",
                        }
                    ],
                }
            }

    driver = VodafoneStationDriver("http://192.168.100.1", "user", "pass")

    with patch.object(driver, "_cga_request", return_value=Response()):
        data = driver._get_docsis_cga()

    assert data["channelDs"]["docsis31"][0]["type"] == "OFDM"
    assert data["channelUs"]["docsis31"][0]["type"] == "OFDMA"
