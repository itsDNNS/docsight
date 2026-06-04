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


def make_response(
    payload=None,
    *,
    status_code=200,
    content_type="applation/json",
    headers=None,
    unparsed_headers="",
):
    resp = MagicMock(status_code=status_code)
    resp.headers = {"Content-Type": content_type}
    if headers:
        resp.headers.update(headers)
    resp.raise_for_status = MagicMock()
    if unparsed_headers:
        msg = MagicMock()
        msg.get_payload.return_value = unparsed_headers
        original_response = MagicMock()
        original_response.msg = msg
        resp.raw = MagicMock()
        resp.raw._original_response = original_response
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
    def test_removed_diagnostics_env_flag_does_not_enable_temporary_logging(self, monkeypatch, caplog):
        # Keep the removed env name split so the repo no longer reintroduces the
        # deleted product constant as a grep-visible feature flag.
        env_name = "DOCSIGHT_SERCOM_" + "DM1000_DIAGNOSTICS"
        monkeypatch.setenv(env_name, "1")
        driver = SercomDM1000Driver("http://192.168.100.1", "technician", "secret")

        with patch.object(driver._session, "post", return_value=make_response("<html>ok</html>", content_type="text/html")):
            with patch.object(driver._session, "get", return_value=make_response("<html>status</html>", content_type="text/html")):
                with patch.object(driver, "_fetch_payload", return_value=DS_INFO):
                    driver.login()

        assert "Sercom DM1000 diagnostic" not in caplog.text

    def test_login_fetches_login_page_posts_base64_form_and_verifies_protected_endpoint(self, driver):
        with patch.object(driver._session, "post", return_value=make_response("<html>ok</html>", content_type="text/html")) as post:
            with patch.object(driver._session, "get", return_value=make_response("<html>status</html>", content_type="text/html")) as get:
                with patch.object(driver, "_fetch_payload", return_value=DS_INFO) as fetch:
                    driver.login()

        get.assert_any_call(
            "http://192.168.100.1/login.html",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
                "Referer": "http://192.168.100.1/login.html",
                "Upgrade-Insecure-Requests": "1",
                "X-Requested-With": None,
            },
            timeout=15,
        )
        post.assert_called_once()
        assert post.call_args.args[0] == "http://192.168.100.1/setup.cgi"
        assert post.call_args.kwargs["headers"] == {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Origin": "http://192.168.100.1",
            "Referer": "http://192.168.100.1/login.html",
            "Upgrade-Insecure-Requests": "1",
            "X-Requested-With": None,
        }
        assert post.call_args.kwargs["allow_redirects"] is False
        payload = post.call_args.kwargs["data"]
        assert payload["login_user"] == "technician"
        assert payload["pws"] == "c2VjcmV0"
        assert payload["passwd"] == "c2VjcmV0"
        assert payload["todo"] == "login"
        assert payload["this_file"] == "login.html"
        assert fetch.call_args_list[0].args == ("Pd_info",)
        assert fetch.call_args_list[0].kwargs == {
            "raise_on_error": False,
            "allow_reauth": False,
            "referer": "http://192.168.100.1/setup.cgi",
        }
        assert fetch.call_args_list[1].args == ("RF_DS_param",)
        assert fetch.call_args_list[1].kwargs == {"raise_on_error": True, "allow_reauth": False}

    def test_login_retries_with_raw_password_when_base64_attempt_is_rejected(self, driver):
        posts = []

        def post(*args, **kwargs):
            posts.append(kwargs["data"].copy())
            return make_response("<html>login</html>", content_type="text/html")

        fetch_results = [
            {},
            RuntimeError("Sercom DM1000 fetch RF_DS_param redirected to login (malformed header Location: login.html)"),
            {},
            DS_INFO,
        ]

        def fetch(*args, **kwargs):
            result = fetch_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(driver._session, "post", side_effect=post):
            with patch.object(driver._session, "get", return_value=make_response("<html>status</html>", content_type="text/html")):
                with patch.object(driver, "_fetch_payload", side_effect=fetch):
                    driver.login()

        assert [payload["pws"] for payload in posts] == ["c2VjcmV0", "secret"]
        assert [payload["passwd"] for payload in posts] == ["c2VjcmV0", "secret"]

    def test_login_primes_pd_info_before_loading_status_page_and_probing_rf_json(self, driver):
        calls = []

        def fetch(todo, **kwargs):
            calls.append(("fetch", todo, kwargs))
            return DS_INFO

        def load_status():
            calls.append(("status",))

        with patch.object(driver._session, "post", return_value=make_response("<html>ok</html>", content_type="text/html")):
            with patch.object(driver, "_load_login_page"):
                with patch.object(driver, "_fetch_payload", side_effect=fetch):
                    with patch.object(driver, "_load_status_page", side_effect=load_status):
                        driver.login()

        assert calls == [
            (
                "fetch",
                "Pd_info",
                {
                    "raise_on_error": False,
                    "allow_reauth": False,
                    "referer": "http://192.168.100.1/setup.cgi",
                },
            ),
            ("status",),
            ("fetch", "RF_DS_param", {"raise_on_error": True, "allow_reauth": False}),
        ]

    def test_load_status_page_uses_captured_browser_navigation_headers(self, driver):
        with patch.object(driver._session, "get", return_value=make_response("<html>status</html>", content_type="text/html")) as get:
            driver._load_status_page()

        get.assert_called_once_with(
            "http://192.168.100.1/status.html",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
                "Referer": "http://192.168.100.1/setup.cgi",
                "Upgrade-Insecure-Requests": "1",
                "X-Requested-With": None,
            },
            timeout=15,
        )

    def test_session_uses_browser_like_headers_from_capture(self, driver):
        headers = driver._session.headers
        assert "Mozilla/5.0" in headers["User-Agent"]
        assert headers["Accept-Language"] == "en-GB,en-US;q=0.9,en;q=0.8"

    def test_login_fails_when_status_page_navigation_fails(self, driver):
        error = requests.HTTPError("500 Server Error")
        status_response = make_response("boom", status_code=500, content_type="text/plain")
        status_response.raise_for_status.side_effect = error
        with patch.object(driver._session, "post", return_value=make_response("<html>ok</html>", content_type="text/html")):
            with patch.object(driver, "_load_login_page"):
                with patch.object(driver, "_fetch_payload", return_value=DS_INFO):
                    with patch.object(driver._session, "get", return_value=status_response):
                        with pytest.raises(RuntimeError, match="status page load failed"):
                            driver.login()

    def test_login_fails_when_post_login_probe_fails(self, driver):
        with patch.object(driver._session, "post", return_value=make_response("<html>login</html>", content_type="text/html")):
            with patch.object(driver._session, "get", return_value=make_response("<html>status</html>", content_type="text/html")):
                with patch.object(driver, "_fetch_payload", side_effect=RuntimeError("login page returned")):
                    with pytest.raises(RuntimeError, match="login page returned"):
                        driver.login()


class TestFetchPayload:
    def test_raw_unparsed_header_payload_preserves_legacy_non_string_stringification(self):
        resp = MagicMock()
        msg = MagicMock()
        msg.get_payload.return_value = ["Location: login.html"]
        original_response = MagicMock(msg=msg)
        resp.raw = MagicMock(_original_response=original_response)

        assert SercomDM1000Driver._raw_unparsed_header_payload(resp) == "['Location: login.html']"

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

    def test_fetch_payload_strict_mode_reports_sercom_login_redirect_from_headers(self, driver):
        response = make_response(None, headers={"Location": "login.html"})
        with patch.object(driver._session, "get", return_value=response):
            with pytest.raises(RuntimeError, match="redirected to login"):
                driver._fetch_payload("RF_DS_param", raise_on_error=True, allow_reauth=False)

    def test_fetch_payload_strict_mode_reports_sercom_login_redirect_from_well_formed_redirect(self, driver):
        response = make_response(None, status_code=302, headers={"Location": "/login.html"})
        with patch.object(driver._session, "get", return_value=response):
            with pytest.raises(RuntimeError, match="redirected to login"):
                driver._fetch_payload("RF_DS_param", raise_on_error=True, allow_reauth=False)

    def test_fetch_payload_strict_mode_reports_sercom_login_redirect_from_malformed_headers(self, driver):
        response = make_response(
            None,
            unparsed_headers="pragma :no-cache\r\nX-Frame-Options: DENY\r\nLocation: login.html\r\n\r\n",
        )
        with patch.object(driver._session, "get", return_value=response):
            with pytest.raises(RuntimeError, match="redirected to login"):
                driver._fetch_payload("RF_DS_param", raise_on_error=True, allow_reauth=False)

    def test_fetch_payload_does_not_emit_removed_diagnostics_when_env_name_is_set(self, driver, monkeypatch, caplog):
        # Keep the removed env name split so the repo no longer reintroduces the
        # deleted product constant as a grep-visible feature flag.
        env_name = "DOCSIGHT_SERCOM_" + "DM1000_DIAGNOSTICS"
        monkeypatch.setenv(env_name, "1")
        response = make_response(
            None,
            unparsed_headers="pragma :no-cache\r\nX-Frame-Options: DENY\r\nLocation: login.html\r\n\r\n",
        )

        with patch.object(driver._session, "get", return_value=response):
            with pytest.raises(RuntimeError, match="redirected to login"):
                driver._fetch_payload("RF_DS_param", raise_on_error=True, allow_reauth=False)

        assert "Sercom DM1000 diagnostic" not in caplog.text

    def test_fetch_payload_accepts_referer_override_for_post_login_pd_info_prime(self, driver):
        with patch.object(driver._session, "get", return_value=make_response(DS_INFO)) as get:
            assert driver._fetch_payload("Pd_info", referer="http://192.168.100.1/setup.cgi") == DS_INFO

        get.assert_called_once_with(
            "http://192.168.100.1/setup.cgi",
            params={"todo": "Pd_info"},
            headers={"Referer": "http://192.168.100.1/setup.cgi"},
            allow_redirects=False,
            timeout=30,
        )

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
