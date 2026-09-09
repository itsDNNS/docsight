from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
import requests

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


@pytest.mark.parametrize("auth_status", [None, 400, 401, 403])
def test_cga_docsis_slow_response_uses_longer_read_timeout(auth_status):
    driver, response = _driver_with_cga_payload({
        "upstream": [{
            "channelidup": "6", "CentralFrequency": "51.0 MHz",
            "power": "43.2 dBmV", "FFT": "64-qam", "ChannelType": "SC-QAM",
        }],
    })
    driver._variant = driver.VARIANT_CGA
    driver._cga_token = "old"
    driver._session.cookies.set("session", "old-session")
    auth_response = MagicMock(status_code=auth_status)
    auth_response.raise_for_status.side_effect = requests.HTTPError(response=auth_response)
    salt_response = MagicMock()
    salt_response.json.return_value = {"salt": "salt-one", "saltwebui": "salt-webui"}
    login_response = MagicMock()
    login_response.json.return_value = {"error": "ok", "token": "new"}
    responses = iter([auth_response, salt_response, login_response, MagicMock(status_code=200)]
                     if auth_status else [])

    def transport(method, url, **kwargs):
        next_response = next(responses, response)
        if next_response is response:
            # Model a slow modem response without sleeping or opening a connection.
            timeout = kwargs["timeout"]
            read_timeout = timeout[1] if isinstance(timeout, tuple) else timeout
            if read_timeout < 11.331:
                raise requests.ReadTimeout("DOCSIS response exceeded read timeout")
        return next_response

    with patch.object(driver._session, "request", side_effect=transport) as request, \
         patch("app.drivers.vodafone_station.time.time", return_value=1234.5):
        data = driver.get_docsis_data()

    calls = request.call_args_list
    docsis_calls = [call for call in calls if call.args[1].endswith("/sta_docsis_status")]
    assert len(docsis_calls) == (2 if auth_status else 1)
    for call in docsis_calls:
        assert call.args == ("GET", "http://dummy/api/v1/sta_docsis_status")
        assert call.kwargs["timeout"] == (10, 30)
        assert call.kwargs["params"] == {"_": 1234500}
    assert docsis_calls[0].kwargs["headers"]["X-CSRF-TOKEN"] == "old"
    if auth_status:
        assert len(calls) == 5
        assert [call.kwargs["timeout"] for call in calls[1:4]] == [10, 10, 10]
        assert docsis_calls[1].kwargs["headers"]["X-CSRF-TOKEN"] == "new"
        assert driver._session.cookies.get("session") is None
    else:
        assert len(calls) == 1
        assert driver._session.cookies.get("session") == "old-session"
    assert data["channelUs"]["docsis30"][0]["channelID"] == 6


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/sta_device_info"),
    ("GET", "/api/v1/session/menu"),
    ("POST", "/api/v1/session/login"),
    ("POST", "/api/v1/sta_docsis_status"),
])
def test_cga_other_requests_keep_default_timeout(method, path):
    driver, response = _driver_with_cga_payload({})
    with patch.object(driver._session, "request", return_value=response) as request:
        assert driver._cga_request(method, path) is response
    assert request.call_args.kwargs["timeout"] == 10


@pytest.mark.parametrize("auth_status", [None, 400, 401, 403])
def test_cga_docsis_read_timeout_is_surfaced_without_another_retry(auth_status):
    driver, _ = _driver_with_cga_payload({})
    driver._variant = driver.VARIANT_CGA
    driver._cga_token = "old"
    driver._session.cookies.set("session", "old-session")
    timeout = requests.ReadTimeout("read timed out")
    outcomes = [timeout]
    if auth_status:
        response = MagicMock(status_code=auth_status)
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        outcomes.insert(0, response)

    with patch.object(driver._session, "request", side_effect=outcomes) as request, \
         patch.object(driver, "_login_cga") as login:
        with pytest.raises(RuntimeError, match="CGA DOCSIS data retrieval failed.*read timed out"):
            driver.get_docsis_data()

    assert request.call_count == (2 if auth_status else 1)
    assert login.call_count == (1 if auth_status else 0)
    assert driver._cga_token is None
    assert not driver._session.cookies
    assert all(call.kwargs["timeout"] == (10, 30) for call in request.call_args_list)


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
