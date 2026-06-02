"""Tests for the authenticated Sercom DM1000 modem driver."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.analyzer import analyze
from app.drivers import driver_registry
from app.drivers.sercom_dm1000 import SercomDM1000Driver


DS_INFO = {
    "nodes": [
        {
            "numD": "1",
            "DCIDD": "7",
            "FreqD": "591000000",
            "SNRD": "38.983261",
            "qamD": "256QAM",
            "octetsD": "-1688606920",
            "correctedsD": "41",
            "uncorrectedsD": "2",
            "PowerD": "8.800003",
        },
        {
            "numD": "2",
            "DCIDD": "8",
            "FreqD": "597000000",
            "SNRD": "38.605377",
            "qamD": "256QAM",
            "octetsD": "-1689299334",
            "correctedsD": "64",
            "uncorrectedsD": "12",
            "PowerD": "8.800003",
        },
    ]
}

DS_OFDM = {
    "nodes": [
        {
            "num": "0",
            "fftType": "4K",
            "OFDMFreq": "275600000",
            "PLC": "YES",
            "NCP": "YES",
            "MDC1": "YES",
            "PLC_power": "10.300003",
            "AV_Pilot": "45",
            "AV_PLC": "40",
            "AV_Data": "39",
        },
        {
            "num": "1",
            "fftType": "4K",
            "OFDMFreq": "827600000",
            "PLC": "YES",
            "NCP": "YES",
            "MDC1": "NO",
            "PLC_power": "4.599998",
            "AV_Pilot": "44",
            "AV_PLC": "39",
            "AV_Data": "38",
        },
    ]
}

US_INFO = {
    "nodes": [
        {
            "num": "0",
            "Freq": "21.100000",
            "rate": "    2.56",
            "modulation": "64QAM",
            "channelType": "DOCSIS 3.0",
            "rep_power": "35.260300",
            "upstream": "5",
        },
        {
            "num": "4",
            "Freq": "9.961089",
            "rate": " Invalid",
            "modulation": "QAM_NONE",
            "channelType": "DOCSIS 3.0",
            "rep_power": "-inf",
            "upstream": "---",
        },
    ]
}

US_OFDMA = {
    "nodes": [
        {"name": "CH", "index1": "0", "index2": "1"},
        {"name": "Power", "index1": "ON", "index2": "OFF"},
        {"name": "STATE", "index1": "    RNG3", "index2": "DISABLED"},
        {"name": "BW (sc s*fft)", "index1": "39.200001", "index2": "0.000000"},
        {"name": "rep power", "index1": "51.141663", "index2": "0.000000"},
        {"name": "rep power1_6", "index1": "37.250000", "index2": "0.000000"},
        {"name": "FFT SIZE", "index1": "2K", "index2": "2K"},
        {"name": "Center Freq SC0", "index1": "42.000000", "index2": "0.000000"},
        {"name": "bit Loading", "index1": "8", "index2": "0"},
    ]
}


def make_response(payload=None, *, status_code=200, content_type="applation/json"):
    resp = MagicMock(status_code=status_code)
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = MagicMock()
    if payload is None:
        resp.text = ""
        resp.json.side_effect = ValueError("empty body")
    else:
        resp.text = json.dumps(payload) if not isinstance(payload, str) else payload
        if isinstance(payload, str):
            resp.json.side_effect = ValueError("not json")
        else:
            resp.json.return_value = payload
    return resp


def make_http_error_response(status_code=403):
    resp = make_response({"error": "expired"}, status_code=status_code)
    error = requests.HTTPError(f"{status_code} Client Error")
    error.response = resp
    resp.raise_for_status.side_effect = error
    return resp


@pytest.fixture
def driver():
    return SercomDM1000Driver("http://192.168.100.1", "technician", "secret")


class TestLogin:
    def test_login_posts_captured_sercom_form_and_verifies_protected_endpoint(self, driver):
        with patch.object(driver._session, "post", return_value=make_response("<html>ok</html>", content_type="text/html")) as post:
            with patch.object(driver, "_fetch_payload", return_value=DS_INFO) as fetch:
                driver.login()

        post.assert_called_once()
        assert post.call_args.args[0] == "http://192.168.100.1/setup.cgi"
        payload = post.call_args.kwargs["data"]
        assert payload["login_user"] == "technician"
        assert payload["pws"] == "secret"
        assert payload["passwd"] == "secret"
        assert payload["todo"] == "login"
        assert payload["this_file"] == "login.html"
        fetch.assert_called_once_with("RF_DS_param", raise_on_error=True, allow_reauth=False)

    def test_login_fails_when_post_login_probe_fails(self, driver):
        with patch.object(driver._session, "post", return_value=make_response("<html>login</html>", content_type="text/html")):
            with patch.object(driver, "_fetch_payload", side_effect=RuntimeError("login page returned")):
                with pytest.raises(RuntimeError, match="login page returned"):
                    driver.login()


class TestFetchPayload:
    def test_fetch_payload_accepts_sercom_json_mime_typo(self, driver):
        with patch.object(driver._session, "get", return_value=make_response(DS_INFO, content_type="applation/json")):
            assert driver._fetch_payload("RF_DS_param") == DS_INFO

    def test_fetch_payload_returns_empty_for_html_login_page_in_best_effort_mode(self, driver):
        with patch.object(driver._session, "get", return_value=make_response("<html>login</html>", content_type="text/html")):
            with patch.object(driver, "login", side_effect=RuntimeError("bad credentials")):
                assert driver._fetch_payload("RF_DS_param") == {}

    def test_fetch_payload_strict_mode_raises_for_html_login_page(self, driver):
        with patch.object(driver._session, "get", return_value=make_response("<html>login</html>", content_type="text/html")):
            with pytest.raises(RuntimeError, match="returned an HTML login page"):
                driver._fetch_payload("RF_DS_param", raise_on_error=True, allow_reauth=False)

    def test_fetch_payload_reauthenticates_once_after_session_expiry(self, driver):
        with patch.object(driver._session, "get", side_effect=[make_http_error_response(403), make_response(DS_INFO)]) as get:
            with patch.object(driver, "login") as login:
                assert driver._fetch_payload("RF_DS_param") == DS_INFO

        login.assert_called_once_with()
        assert get.call_count == 2

    def test_fetch_payload_returns_empty_for_non_object_json(self, driver):
        with patch.object(driver._session, "get", return_value=make_response(["not", "object"])):
            assert driver._fetch_payload("RF_DS_param") == {}

    def test_fetch_payload_retries_html_login_page_only_once(self, driver):
        with patch.object(
            driver._session,
            "get",
            side_effect=[
                make_response("<html>login</html>", content_type="text/html"),
                make_response("<html>login</html>", content_type="text/html"),
            ],
        ) as get:
            with patch.object(driver, "login") as login:
                assert driver._fetch_payload("RF_DS_param") == {}

        login.assert_called_once_with()
        assert get.call_count == 2

    def test_fetch_payload_returns_empty_for_sercom_error_code(self, driver, caplog):
        with patch.object(
            driver._session,
            "get",
            return_value=make_response({"errCode": "101", "errMsg": "not authenticated"}),
        ):
            assert driver._fetch_payload("RF_DS_param") == {}

        assert "not authenticated" in caplog.text


class TestDocsisData:
    def test_parses_sercom_dm1000_channel_payloads(self, driver):
        payloads = {
            "RF_DS_param": DS_INFO,
            "RF_DS_31_param": DS_OFDM,
            "RF_US_param": US_INFO,
            "RF_US_31_param": US_OFDMA,
        }
        with patch.object(driver, "_fetch_payload", side_effect=lambda todo: payloads[todo]):
            data = driver.get_docsis_data()

        assert len(data["channelDs"]["docsis30"]) == 2
        assert len(data["channelDs"]["docsis31"]) == 1
        assert len(data["channelUs"]["docsis30"]) == 1
        assert len(data["channelUs"]["docsis31"]) == 1

        ds = data["channelDs"]["docsis30"][0]
        assert ds == {
            "channelID": 7,
            "frequency": "591 MHz",
            "powerLevel": pytest.approx(8.800003),
            "modulation": "256QAM",
            "mer": pytest.approx(38.983261),
            "mse": pytest.approx(-38.983261),
            "corrErrors": 41,
            "nonCorrErrors": 2,
        }

        ds_ofdm = data["channelDs"]["docsis31"][0]
        assert ds_ofdm["channelID"] == 0
        assert ds_ofdm["type"] == "OFDM"
        assert ds_ofdm["frequency"] == "275.6 MHz"
        assert ds_ofdm["powerLevel"] == pytest.approx(10.300003)
        assert ds_ofdm["mer"] == pytest.approx(39.0)
        assert ds_ofdm["corrErrors"] is None
        assert ds_ofdm["nonCorrErrors"] is None

        us = data["channelUs"]["docsis30"][0]
        assert us["channelID"] == 5
        assert us["frequency"] == "21.1 MHz"
        assert us["powerLevel"] == pytest.approx(35.2603)
        assert us["modulation"] == "64QAM"
        assert us["multiplex"] == "ATDMA"
        assert us["symbolRate"] == 2560

        us_ofdma = data["channelUs"]["docsis31"][0]
        assert us_ofdma["channelID"] == 0
        assert us_ofdma["type"] == "OFDMA"
        assert us_ofdma["frequency"] == "42 MHz"
        assert us_ofdma["powerLevel"] == pytest.approx(37.25)
        assert us_ofdma["powerLevel"] != pytest.approx(51.141663)
        assert us_ofdma["profile_modulation"] == "256QAM"

    def test_us_ofdma_without_rep_power_1_6_keeps_power_unsupported(self, driver, caplog):
        rows = [dict(row) for row in US_OFDMA["nodes"] if row["name"] != "rep power1_6"]

        channels = driver._parse_us_ofdma(rows)

        assert len(channels) == 1
        assert channels[0]["powerLevel"] is None
        assert "rep power1_6" in caplog.text

    @pytest.mark.parametrize(
        ("plc", "mdc1", "av_data", "av_plc", "expected_count"),
        [
            ("NO", "YES", "39", "40", 0),
            ("YES", "NO", "39", "40", 0),
            ("YES", "YES", "", "", 0),
            ("YES", "YES", "", "40", 1),
        ],
    )
    def test_ds_ofdm_requires_plc_mdc1_and_numeric_mer(self, driver, plc, mdc1, av_data, av_plc, expected_count):
        row = dict(DS_OFDM["nodes"][0], PLC=plc, MDC1=mdc1, AV_Data=av_data, AV_PLC=av_plc)

        channels = driver._parse_ds_ofdm([row])

        assert len(channels) == expected_count
        if channels:
            assert channels[0]["mer"] == pytest.approx(40.0)

    def test_us_scqam_rejects_inactive_rows(self, driver):
        inactive = {
            "Freq": "9.961089",
            "rate": " Invalid",
            "modulation": "QAM_NONE",
            "rep_power": "-inf",
            "upstream": "---",
        }

        assert driver._parse_us_scqam([inactive]) == []

    def test_us_ofdma_skips_disabled_and_zero_frequency_columns(self, driver):
        zero_frequency = [
            dict(row, index1="0.000000") if row["name"] == "Center Freq SC0" else dict(row)
            for row in US_OFDMA["nodes"]
        ]

        assert driver._parse_us_ofdma(zero_frequency) == []
        assert len(driver._parse_us_ofdma(US_OFDMA["nodes"])) == 1

    @pytest.mark.parametrize(
        ("bits", "expected"),
        [("0", None), ("2", "QPSK"), ("8", "256QAM"), ("13", None), (None, None)],
    )
    def test_profile_modulation_from_bit_loading(self, driver, bits, expected):
        assert driver._profile_modulation_from_bits(bits) == expected

    def test_analyzer_accepts_sercom_dm1000_payload(self, driver):
        payloads = {
            "RF_DS_param": DS_INFO,
            "RF_DS_31_param": DS_OFDM,
            "RF_US_param": US_INFO,
            "RF_US_31_param": US_OFDMA,
        }
        with patch.object(driver, "_fetch_payload", side_effect=lambda todo: payloads[todo]):
            analysis = analyze(driver.get_docsis_data())

        assert len(analysis["ds_channels"]) == 3
        assert len(analysis["us_channels"]) == 2
        ofdma = next(ch for ch in analysis["us_channels"] if ch["channel_family"] == "ofdma")
        assert ofdma["power"] == pytest.approx(37.25)
        assert ofdma["profile_modulation"] == "256QAM"


class TestDeviceInfo:
    def test_get_device_info_uses_safe_static_fallback_when_pd_info_is_unavailable(self, driver):
        with patch.object(driver, "_fetch_payload", return_value={}):
            info = driver.get_device_info()

        assert info == {"manufacturer": "Sercom", "model": "DM1000", "sw_version": ""}


class TestRegistry:
    def test_sercom_dm1000_driver_is_registered(self):
        assert driver_registry.has_driver("sercom_dm1000")
        drivers = dict(driver_registry.get_available_drivers())
        assert drivers["sercom_dm1000"] == "Sercom DM1000"
