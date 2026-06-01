"""Tests for authenticated Hitron CODA-4680 modem driver."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.analyzer import analyze
from app.drivers import driver_registry
from app.drivers.hitron_coda_4680 import HitronCoda4680Driver


DS_INFO = {
    "errCode": "000",
    "errMsg": "",
    "Freq_List": [
        {
            "portId": "1",
            "frequency": "663000000",
            "modulation": "QAM256",
            "signalStrength": "5.099",
            "snr": "40.946",
            "channelId": "18",
            "dsoctets": "1591166190",
            "correcteds": "5",
            "uncorrect": "33",
        },
        {
            "portId": "2",
            "frequency": "591000000",
            "modulation": "QAM256",
            "signalStrength": "4.099",
            "snr": "43.376",
            "channelId": "7",
            "dsoctets": "116416",
            "correcteds": "0",
            "uncorrect": "0",
        },
    ],
}

US_INFO = {
    "errCode": "000",
    "errMsg": "",
    "Freq_List": [
        {
            "portId": "1",
            "frequency": "32300000",
            "modulationType": "64QAM",
            "signalStrength": "42.770",
            "bandwidth": "6400000",
            "channelId": "3",
            "symbolrate": 5120,
            "preEq": [8, 1, 24, 0],
        }
    ],
}

DS_OFDM = {
    "errCode": "000",
    "errMsg": "",
    "OFDMs_List": [
        {
            "receive": 0,
            "ffttype": "4K",
            "Subcarr0freqFreq": " 275600000",
            "plclock": "YES",
            "ncplock": "YES",
            "mdc1lock": "YES",
            "plclocation": "1544",
            "occupiedbw": "283 ~ 472.95",
            "datasubcarriers": "3736",
            "plcpower": "  3.000000",
        }
    ],
}

US_OFDMA = {
    "errCode": "000",
    "errMsg": "",
    "OFDMAs_List": [
        {
            "uschindex": "0",
            "state": "OPERATE",
            "digAtten": "0.1659",
            "digAttenBo": "6.5838",
            "channelBw": "39.2000",
            "repPower": "52.6417",
            "repPower1_6": "38.7500",
            "fftVal": "2K",
        },
        {
            "uschindex": "1",
            "state": "DISABLED",
            "digAtten": "0.0000",
            "digAttenBo": "0.0000",
            "channelBw": "0.0000",
            "repPower": "0.0000",
            "repPower1_6": "0.0000",
            "fftVal": "2K",
        },
    ],
}

VERSION = {
    "errCode": "000",
    "errMsg": "",
    "modelName": "CODA-4680-TPIA",
    "vendorName": "Hitron Technologies",
    "SerialNum": "REDACTED",
    "HwVersion": "1A",
    "ApiVersion": "1.12.1",
    "SoftwareVersion": "7.2.4.5.2b8",
    "Model": "CODA-4680-TPIA (1A)",
    "ModelReport": "CODA-4680-TPIA",
}

SYS_INFO = {
    "errCode": "000",
    "errMsg": "",
    "ntAccess": "Permitted",
    "macAddr": "00:00:00:00:00:00",
    "ip": ["0.0.0.0"],
    "subMask": "255.255.255.192",
    "gw": "10.78.158.1",
    "lease": "D: 7 H: 00 M: 00 S: 00",
    "Configname": "bac10a000106b0f530913980",
    "DsDataRate": "0",
    "UsDataRate": "0",
}


def make_response(payload=None):
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    if payload is None:
        resp.text = ""
        resp.json.side_effect = ValueError("empty body")
    else:
        resp.text = json.dumps(payload)
        resp.json.return_value = payload
    return resp


def make_http_error_response(status_code=403):
    resp = MagicMock(status_code=status_code)
    error = requests.HTTPError(f"{status_code} Client Error")
    error.response = resp
    resp.raise_for_status.side_effect = error
    return resp


@pytest.fixture
def driver():
    return HitronCoda4680Driver("http://192.168.100.1", "username", "secret")


class TestLogin:
    def test_login_posts_json_model_credentials_and_accepts_empty_body(self, driver):
        with patch.object(driver._session, "post", return_value=make_response(None)) as post:
            with patch.object(driver, "_fetch_payload", return_value=VERSION) as fetch:
                driver.login()

        post.assert_called_once()
        url = post.call_args.args[0]
        assert url == "http://192.168.100.1/1/Device/Users/Login"
        assert json.loads(post.call_args.kwargs["data"]["model"]) == {
            "username": "username",
            "password": "secret",
        }
        fetch.assert_called_once_with("/1/Device/CM/Version", raise_on_error=True, allow_reauth=False)

    def test_login_accepts_empty_object_body_after_version_check(self, driver):
        with patch.object(driver._session, "post", return_value=make_response({})):
            with patch.object(driver, "_fetch_payload", return_value=VERSION) as fetch:
                driver.login()

        fetch.assert_called_once_with("/1/Device/CM/Version", raise_on_error=True, allow_reauth=False)

    def test_login_fails_when_post_login_version_check_fails(self, driver):
        with patch.object(driver._session, "post", return_value=make_response(None)):
            with patch.object(driver, "_fetch_payload", side_effect=RuntimeError("unauthorized")):
                with pytest.raises(RuntimeError, match="unauthorized"):
                    driver.login()

    def test_login_rejects_json_error_response(self, driver):
        with patch.object(driver._session, "post", return_value=make_response({"errCode": "101", "errMsg": "bad login"})):
            with pytest.raises(RuntimeError, match="bad login"):
                driver.login()

    def test_login_rejects_non_object_json_response(self, driver):
        with patch.object(driver._session, "post", return_value=make_response(["not", "an", "object"])):
            with pytest.raises(RuntimeError, match="login returned invalid JSON payload"):
                driver.login()


class TestDeviceInfo:
    def test_get_device_info_reads_version_endpoint(self, driver):
        with patch.object(driver, "_fetch_payload", return_value=VERSION):
            info = driver.get_device_info()

        assert info["manufacturer"] == "Hitron Technologies"
        assert info["model"] == "CODA-4680-TPIA"
        assert info["sw_version"] == "7.2.4.5.2b8"


class TestDocsisData:
    def test_parses_coda_4680_channel_payloads(self, driver):
        payloads = {
            "/1/Device/CM/DsInfo": DS_INFO,
            "/1/Device/CM/UsInfo": US_INFO,
            "/1/Device/CM/DsOfdm": DS_OFDM,
            "/1/Device/CM/UsOfdm": US_OFDMA,
        }
        with patch.object(driver, "_fetch_payload", side_effect=lambda path: payloads[path]):
            data = driver.get_docsis_data()

        assert len(data["channelDs"]["docsis30"]) == 2
        assert len(data["channelDs"]["docsis31"]) == 1
        assert len(data["channelUs"]["docsis30"]) == 1
        assert len(data["channelUs"]["docsis31"]) == 1

        ds = data["channelDs"]["docsis30"][0]
        assert ds == {
            "channelID": 18,
            "frequency": "663 MHz",
            "powerLevel": 5.099,
            "modulation": "256QAM",
            "mer": 40.946,
            "mse": -40.946,
            "corrErrors": 5,
            "nonCorrErrors": 33,
        }

        us = data["channelUs"]["docsis30"][0]
        assert us["channelID"] == 3
        assert us["frequency"] == "32.3 MHz"
        assert us["powerLevel"] == 42.77
        assert us["modulation"] == "64QAM"
        assert us["multiplex"] == "ATDMA"
        assert us["symbolRate"] == 5120

        ds_ofdm = data["channelDs"]["docsis31"][0]
        assert ds_ofdm["channelID"] == 0
        assert ds_ofdm["type"] == "OFDM"
        assert ds_ofdm["frequency"] == "275.6 MHz"
        assert ds_ofdm["powerLevel"] == 3.0
        assert ds_ofdm["mer"] is None
        assert ds_ofdm["corrErrors"] is None
        assert ds_ofdm["nonCorrErrors"] is None

        us_ofdma = data["channelUs"]["docsis31"][0]
        assert us_ofdma["channelID"] == 0
        assert us_ofdma["type"] == "OFDMA"
        assert us_ofdma["frequency"] == ""
        assert us_ofdma["powerLevel"] == pytest.approx(52.6417)
        assert us_ofdma["multiplex"] == "OFDMA"

    def test_ds_ofdm_unlocked_rows_are_ignored(self, driver):
        rows = [
            dict(DS_OFDM["OFDMs_List"][0], receive=0, plclock="NO"),
            dict(DS_OFDM["OFDMs_List"][0], receive=1, plclock="YES"),
        ]

        channels = driver._parse_ds_ofdm(rows)

        assert [channel["channelID"] for channel in channels] == [1]

    def test_fetch_payload_returns_empty_for_non_object_json(self, driver):
        with patch.object(driver._session, "get", return_value=make_response(["not", "an", "object"])):
            assert driver._fetch_payload("/1/Device/CM/DsInfo") == {}

    def test_fetch_payload_returns_empty_for_modem_error_code(self, driver):
        with patch.object(
            driver._session,
            "get",
            return_value=make_response({"errCode": "999", "errMsg": "temporary unavailable"}),
        ):
            assert driver._fetch_payload("/1/Device/CM/DsInfo") == {}

    @pytest.mark.parametrize("err_code", ["401", "403"])
    def test_fetch_payload_reauthenticates_once_after_auth_error_payload(self, driver, err_code):
        with patch.object(
            driver._session,
            "get",
            side_effect=[make_response({"errCode": err_code, "errMsg": "session expired"}), make_response(DS_INFO)],
        ) as get:
            with patch.object(driver, "login") as login:
                payload = driver._fetch_payload("/1/Device/CM/DsInfo")

        assert payload == DS_INFO
        login.assert_called_once_with()
        assert get.call_count == 2

    def test_fetch_payload_does_not_loop_when_auth_error_payload_retry_also_expires(self, driver):
        with patch.object(
            driver._session,
            "get",
            side_effect=[
                make_response({"errCode": "401", "errMsg": "session expired"}),
                make_response({"errCode": "401", "errMsg": "session expired"}),
            ],
        ) as get:
            with patch.object(driver, "login") as login:
                payload = driver._fetch_payload("/1/Device/CM/DsInfo")

        assert payload == {}
        login.assert_called_once_with()
        assert get.call_count == 2

    def test_fetch_payload_strict_mode_raises_when_auth_error_payload_retry_also_expires(self, driver):
        with patch.object(
            driver._session,
            "get",
            side_effect=[
                make_response({"errCode": "401", "errMsg": "session expired"}),
                make_response({"errCode": "401", "errMsg": "session expired"}),
            ],
        ) as get:
            with patch.object(driver, "login") as login:
                with pytest.raises(RuntimeError, match="/1/Device/CM/Version failed: session expired"):
                    driver._fetch_payload("/1/Device/CM/Version", raise_on_error=True)

        login.assert_called_once_with()
        assert get.call_count == 2

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_fetch_payload_reauthenticates_once_after_session_expiry(self, driver, status_code):
        with patch.object(
            driver._session,
            "get",
            side_effect=[make_http_error_response(status_code), make_response(DS_INFO)],
        ) as get:
            with patch.object(driver, "login") as login:
                payload = driver._fetch_payload("/1/Device/CM/DsInfo")

        assert payload == DS_INFO
        login.assert_called_once_with()
        assert get.call_count == 2

    def test_fetch_payload_does_not_loop_when_reauth_retry_also_expires(self, driver):
        with patch.object(
            driver._session,
            "get",
            side_effect=[make_http_error_response(403), make_http_error_response(403)],
        ) as get:
            with patch.object(driver, "login") as login:
                payload = driver._fetch_payload("/1/Device/CM/DsInfo")

        assert payload == {}
        login.assert_called_once_with()
        assert get.call_count == 2

    def test_fetch_payload_strict_mode_raises_when_reauth_retry_also_expires(self, driver):
        with patch.object(
            driver._session,
            "get",
            side_effect=[make_http_error_response(403), make_http_error_response(403)],
        ) as get:
            with patch.object(driver, "login") as login:
                with pytest.raises(RuntimeError, match="fetch /1/Device/CM/Version failed"):
                    driver._fetch_payload("/1/Device/CM/Version", raise_on_error=True)

        login.assert_called_once_with()
        assert get.call_count == 2

    def test_fetch_payload_returns_empty_when_reauth_login_fails(self, driver):
        with patch.object(driver._session, "get", return_value=make_http_error_response(403)) as get:
            with patch.object(driver, "login", side_effect=RuntimeError("bad credentials")) as login:
                payload = driver._fetch_payload("/1/Device/CM/DsInfo")

        assert payload == {}
        login.assert_called_once_with()
        get.assert_called_once()

    def test_fetch_payload_strict_mode_raises_when_reauth_login_fails(self, driver):
        with patch.object(driver._session, "get", return_value=make_http_error_response(403)) as get:
            with patch.object(driver, "login", side_effect=RuntimeError("bad credentials")) as login:
                with pytest.raises(RuntimeError, match="re-login before fetching /1/Device/CM/Version failed"):
                    driver._fetch_payload("/1/Device/CM/Version", raise_on_error=True)

        login.assert_called_once_with()
        get.assert_called_once()

    def test_analyzer_accepts_coda_4680_null_counter_payload(self, driver):
        payloads = {
            "/1/Device/CM/DsInfo": DS_INFO,
            "/1/Device/CM/UsInfo": US_INFO,
            "/1/Device/CM/DsOfdm": DS_OFDM,
            "/1/Device/CM/UsOfdm": US_OFDMA,
        }
        with patch.object(driver, "_fetch_payload", side_effect=lambda path: payloads[path]):
            analysis = analyze(driver.get_docsis_data())

        ofdm = next(ch for ch in analysis["ds_channels"] if ch["channel_family"] == "ofdm")
        ofdma = next(ch for ch in analysis["us_channels"] if ch["channel_family"] == "ofdma")
        assert ofdm["correctable_errors"] is None
        assert ofdm["uncorrectable_errors"] is None
        assert ofdm["snr"] is None
        assert ofdma["frequency"] == ""


class TestConnectionInfo:
    def test_get_connection_info_reads_docsis_sysinfo_when_available(self, driver):
        with patch.object(driver, "_fetch_payload", return_value=SYS_INFO):
            info = driver.get_connection_info()

        assert info["connection_type"] == "DOCSIS"
        assert info["status"] == "Permitted"
        assert info["wan_ip"] == "0.0.0.0"
        assert info["max_downstream_kbps"] == 0
        assert info["max_upstream_kbps"] == 0


class TestRegistry:
    def test_coda_4680_driver_is_registered_separately_from_coda_56_driver(self):
        assert driver_registry.has_driver("hitron_coda_4680")
        drivers = dict(driver_registry.get_available_drivers())
        assert drivers["hitron_coda_4680"] == "Hitron CODA-4680"
        assert drivers["hitron"] == "Hitron CODA-56"
