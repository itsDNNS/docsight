from typing import Any, cast
from unittest.mock import MagicMock, patch

from app.analyzer import analyze
from app.drivers.vodafone_station import VodafoneStationDriver
from app.drivers.utils import pbkdf2_sha256


def _driver_with_cga_payload(payload):
    driver = VodafoneStationDriver(url="http://dummy", user="admin", password="admin")
    response = MagicMock()
    response.json.return_value = {"error": "ok", "data": payload}
    return driver, response


def test_cga_double_pbkdf2_hash_contract():
    # Reference vectors generated with hashlib.pbkdf2_hmac("sha256", ...).
    hash1 = pbkdf2_sha256(b"admin", b"salt-one").hex()
    hash2 = pbkdf2_sha256(hash1.encode("utf-8"), b"salt-webui").hex()

    assert hash1 == "6b081300747b39b79512fd1953f40054"
    assert hash2 == "c2b69842ff6750b1e83368f092e4a405"


def test_cga_login_posts_double_pbkdf2_hash():
    driver = VodafoneStationDriver(url="http://dummy", user="admin", password="admin")

    salt_response = MagicMock()
    salt_response.raise_for_status = MagicMock()
    salt_response.json.return_value = {"salt": "salt-one", "saltwebui": "salt-webui"}

    login_response = MagicMock()
    login_response.raise_for_status = MagicMock()
    login_response.json.return_value = {"error": "ok", "token": "token-123"}

    menu_response = MagicMock(status_code=200)

    with patch.object(driver._session, "post", side_effect=[salt_response, login_response]) as mock_post, \
         patch.object(driver._session, "get", return_value=menu_response):
        driver._login_cga()

    assert mock_post.call_args_list[0].kwargs["data"]["password"] == "seeksalthash"
    assert mock_post.call_args_list[1].kwargs["data"]["password"] == (
        "c2b69842ff6750b1e83368f092e4a405"
    )
    assert driver._cga_token == "token-123"


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
