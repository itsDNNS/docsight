"""Regression tests for driver modulation normalization."""

from unittest.mock import patch

from bs4 import BeautifulSoup

import pytest

from app.drivers.formats.html_rows import parse_tc4400_html
from app.drivers.vodafone_station import VodafoneStationDriver


def _tc4400_downstream(headers: str, row: str) -> list:
    table = BeautifulSoup(f"<table><tr>{headers}</tr><tr>{row}</tr></table>", "html.parser").find("table")
    return parse_tc4400_html(table, None).value["downstream"]


@pytest.mark.parametrize(
    ("row", "expected_type", "expected_mse"),
    [
        ("<td>193</td><td>Locked</td><td>OFDM</td><td></td><td>957000000 Hz</td><td>0.1 dBmV</td><td>43.0 dB</td>", "OFDM", None),
        ("<td>1</td><td>Locked</td><td>SC-QAM</td><td>256-qam</td><td>602000000 Hz</td><td>2.0 dBmV</td><td>39.5 dB</td>", "256QAM", -39.5),
    ],
)
def test_tc4400_downstream_type_is_canonical(row, expected_type, expected_mse):
    headers = "<th>Channel ID</th><th>Lock Status</th><th>Channel Type</th><th>Modulation</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Corrected</th><th>Uncorrected</th>"
    channels = _tc4400_downstream(headers, row + "<td>1</td><td>0</td>")

    assert channels[0]["type"] == expected_type
    assert channels[0]["mse"] == expected_mse


@pytest.mark.parametrize(
    ("headers", "row"),
    [
        ("<th>Channel ID</th><th>Channel Index</th>", "<td>7</td><td>3</td>"),
        ("<th>Channel Index</th><th>Channel ID</th>", "<td>3</td><td>7</td>"),
    ],
)
def test_tc4400_column_mapping_always_prefers_explicit_channel_id(headers, row):
    channels = _tc4400_downstream(
        headers + "<th>Lock Status</th><th>Frequency</th>", row + "<td>Locked</td><td>591000000 Hz</td>"
    )

    assert channels[0]["channelID"] == "7"


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
