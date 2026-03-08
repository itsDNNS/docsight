"""Tests for Arris SURFboard HNAP modem driver."""

import hashlib
import hmac

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from app.drivers.surfboard import SurfboardDriver


# -- Embedded channel strings from real S34 HAR capture --

DS_RAW = (
    "1^Locked^256QAM^43^705000000^ 0.0^40.9^31^0^"
    "|+|2^Locked^256QAM^44^711000000^ 0.1^41.0^25^0^"
    "|+|3^Locked^256QAM^45^717000000^ 0.2^41.1^18^0^"
    "|+|4^Locked^256QAM^46^723000000^ 0.3^41.2^12^0^"
    "|+|5^Locked^256QAM^47^729000000^ 0.4^41.3^8^0^"
    "|+|6^Locked^256QAM^48^735000000^ 0.5^41.4^5^0^"
    "|+|7^Locked^256QAM^49^741000000^ 0.6^41.5^3^0^"
    "|+|8^Locked^256QAM^50^747000000^ 0.7^41.6^2^0^"
    "|+|9^Locked^256QAM^51^753000000^ 0.8^41.7^1^0^"
    "|+|10^Locked^256QAM^52^759000000^ 0.9^41.8^0^0^"
    "|+|11^Locked^256QAM^53^765000000^ 1.0^41.9^0^0^"
    "|+|12^Locked^256QAM^54^771000000^ 1.1^42.0^0^0^"
    "|+|13^Locked^256QAM^55^777000000^ 1.2^42.1^0^0^"
    "|+|14^Locked^256QAM^56^783000000^ 1.3^42.2^0^0^"
    "|+|15^Locked^256QAM^57^789000000^ 1.4^42.3^0^0^"
    "|+|16^Locked^256QAM^58^795000000^ 1.5^42.4^0^0^"
    "|+|17^Locked^256QAM^27^555000000^-0.1^40.8^35^1^"
    "|+|18^Locked^256QAM^28^561000000^-0.2^40.7^40^2^"
    "|+|19^Locked^256QAM^29^567000000^-0.3^40.6^45^3^"
    "|+|20^Locked^256QAM^30^573000000^-0.4^40.5^50^4^"
    "|+|21^Locked^256QAM^31^579000000^-0.5^40.4^55^5^"
    "|+|22^Locked^256QAM^32^585000000^-0.6^40.3^60^6^"
    "|+|23^Locked^256QAM^33^591000000^-0.7^40.2^65^7^"
    "|+|24^Locked^256QAM^34^597000000^-0.8^40.1^70^8^"
    "|+|25^Locked^256QAM^35^603000000^-0.9^40.0^75^9^"
    "|+|26^Locked^256QAM^36^609000000^-1.0^39.9^80^10^"
    "|+|27^Locked^256QAM^37^615000000^-1.1^39.8^85^11^"
    "|+|28^Locked^256QAM^38^621000000^-1.2^39.7^90^12^"
    "|+|29^Locked^256QAM^39^627000000^-1.3^39.6^95^13^"
    "|+|30^Locked^256QAM^40^633000000^-1.4^39.5^100^14^"
    "|+|31^Locked^256QAM^41^639000000^-1.5^39.4^105^15^"
    "|+|32^Locked^256QAM^42^645000000^-1.6^39.3^110^16^"
    "|+|33^Locked^OFDM PLC^193^957000000^ 0.1^43.0^2467857853^7894^"
)

US_RAW = (
    "1^Locked^SC-QAM^3^6400000^29200000^46.5^"
    "|+|2^Locked^SC-QAM^4^6400000^35600000^45.0^"
    "|+|3^Locked^SC-QAM^2^6400000^22800000^44.5^"
    "|+|4^Locked^SC-QAM^1^6400000^16400000^44.0^"
    "|+|5^Locked^OFDMA^41^44400000^36200000^43.8^"
)

HNAP_DS_RESPONSE = {
    "GetMultipleHNAPsResponse": {
        "GetCustomerStatusDownstreamChannelInfoResponse": {
            "CustomerConnDownstreamChannel": DS_RAW,
            "GetCustomerStatusDownstreamChannelInfoResult": "OK",
        },
        "GetCustomerStatusUpstreamChannelInfoResponse": {
            "CustomerConnUpstreamChannel": US_RAW,
            "GetCustomerStatusUpstreamChannelInfoResult": "OK",
        },
    }
}

HNAP_DEVICE_RESPONSE = {
    "GetMultipleHNAPsResponse": {
        "GetCustomerStatusConnectionInfoResponse": {
            "StatusSoftwareModelName": "S34",
            "StatusSoftwareSfVer": "2.5.0.1-2-GA",
            "GetCustomerStatusConnectionInfoResult": "OK",
        },
    }
}

HNAP_LOGIN_PHASE1 = {
    "LoginResponse": {
        "Challenge": "ABCDEF1234567890",
        "Cookie": "SESS_12345",
        "PublicKey": "PUB_KEY_9876",
        "LoginResult": "OK",
    }
}

HNAP_LOGIN_PHASE2 = {
    "LoginResponse": {
        "LoginResult": "OK",
    }
}


@pytest.fixture
def driver():
    return SurfboardDriver("https://192.168.100.1", "admin", "password")


@pytest.fixture
def mock_hnap(driver):
    """Patch _hnap_post to return channel data."""
    def side_effect(action, body, auth=True):
        if action == "GetMultipleHNAPs":
            keys = body.get("GetMultipleHNAPs", {})
            if "GetCustomerStatusDownstreamChannelInfo" in keys:
                return HNAP_DS_RESPONSE
            if "GetCustomerStatusConnectionInfo" in keys:
                return HNAP_DEVICE_RESPONSE
        return {}

    with patch.object(driver, "_hnap_post", side_effect=side_effect):
        yield driver


# -- Driver instantiation --

class TestDriverInit:
    def test_stores_credentials(self):
        d = SurfboardDriver("https://192.168.100.1", "admin", "pass123")
        assert d._url == "https://192.168.100.1"
        assert d._user == "admin"
        assert d._password == "pass123"

    def test_https_upgrade(self):
        d = SurfboardDriver("http://192.168.100.1", "admin", "pass")
        assert d._url == "https://192.168.100.1"

    def test_https_preserved(self):
        d = SurfboardDriver("https://10.0.0.1", "admin", "pass")
        assert d._url == "https://10.0.0.1"

    def test_ssl_verify_disabled(self):
        d = SurfboardDriver("https://192.168.100.1", "admin", "pass")
        assert d._session.verify is False

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("surfboard", "https://192.168.100.1", "admin", "pass")
        assert isinstance(d, SurfboardDriver)


# -- Login --

class TestLogin:
    def test_login_two_phase_flow(self, driver):
        """Login calls _hnap_post twice: request then login."""
        calls = []

        def mock_post(action, body, auth=True):
            calls.append((action, body.get("Login", {}).get("Action"), auth))
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert len(calls) == 2
        assert calls[0] == ("Login", "request", False)
        assert calls[1] == ("Login", "login", False)

    def test_login_derives_private_key(self, driver):
        """PrivateKey = HMAC-SHA256(PublicKey+password, Challenge).upper()"""
        def mock_post(action, body, auth=True):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        expected_key = hmac.new(
            ("PUB_KEY_9876" + "password").encode(),
            "ABCDEF1234567890".encode(),
            hashlib.sha256,
        ).hexdigest().upper()
        assert driver._private_key == expected_key

    def test_login_sends_correct_password(self, driver):
        """LoginPassword = HMAC-SHA256(PrivateKey, Challenge).upper()"""
        sent_passwords = []

        def mock_post(action, body, auth=True):
            login_data = body.get("Login", {})
            if login_data.get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            sent_passwords.append(login_data.get("LoginPassword"))
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        private_key = hmac.new(
            ("PUB_KEY_9876" + "password").encode(),
            "ABCDEF1234567890".encode(),
            hashlib.sha256,
        ).hexdigest().upper()
        expected_pw = hmac.new(
            private_key.encode(),
            "ABCDEF1234567890".encode(),
            hashlib.sha256,
        ).hexdigest().upper()
        assert sent_passwords[0] == expected_pw

    def test_login_sets_cookie(self, driver):
        def mock_post(action, body, auth=True):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert driver._cookie == "SESS_12345"

    def test_login_failure_raises(self, driver):
        def mock_post(action, body, auth=True):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return {"LoginResponse": {"LoginResult": "FAILED"}}

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            with pytest.raises(RuntimeError, match="SURFboard login failed: FAILED"):
                driver.login()

    def test_login_no_challenge_raises(self, driver):
        def mock_post(action, body, auth=True):
            return {"LoginResponse": {"Challenge": "", "PublicKey": "", "Cookie": ""}}

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            with pytest.raises(RuntimeError, match="no challenge received"):
                driver.login()

    def test_login_retries_on_connection_error(self, driver):
        import requests as req

        attempt_count = []

        def mock_do_login():
            attempt_count.append(1)
            if len(attempt_count) == 1:
                raise req.ConnectionError("reset")
            # Second attempt succeeds
            driver._private_key = "KEY"
            driver._cookie = "COOKIE"

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert len(attempt_count) == 2

    def test_login_skipped_when_already_logged_in(self, driver):
        """login() is a no-op when session is already active."""
        driver._logged_in = True
        calls = []

        with patch.object(driver, "_do_login", side_effect=lambda: calls.append(1)):
            driver.login()

        assert calls == []

    def test_login_forced_after_session_invalidation(self, driver):
        """login() re-authenticates when _logged_in is False."""
        driver._logged_in = False

        def mock_post(action, body, auth=True):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert driver._logged_in is True


# -- HNAP Auth header --

class TestHnapAuth:
    def test_auth_header_format(self, driver):
        """HNAP_AUTH = <uppercase_hex> <timestamp>"""
        driver._private_key = "TESTKEY123"

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.123
            driver._hnap_post("GetMultipleHNAPs", {"GetMultipleHNAPs": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            hnap_auth = headers["HNAP_AUTH"]

            parts = hnap_auth.split(" ")
            assert len(parts) == 2
            auth_hash, timestamp = parts
            # Hash is uppercase hex (64 chars for SHA256)
            assert len(auth_hash) == 64
            assert auth_hash == auth_hash.upper()
            assert auth_hash.isalnum()

    def test_auth_includes_quoted_uri_in_hmac(self, driver):
        """The SOAPACTION URI (with surrounding quotes) is part of the HMAC input."""
        driver._private_key = "TESTKEY123"

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0
            driver._hnap_post("GetMultipleHNAPs", {"GetMultipleHNAPs": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})

            ts = str(int(1700000000.0 * 1000) % 2_000_000_000_000)
            soap_action = '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"'
            expected_hash = hmac.new(
                "TESTKEY123".encode(),
                (ts + soap_action).encode(),
                hashlib.sha256,
            ).hexdigest().upper()

            assert headers["HNAP_AUTH"] == f"{expected_hash} {ts}"

    def test_soap_action_header_set(self, driver):
        driver._private_key = "TESTKEY123"

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post:
            driver._hnap_post("GetMultipleHNAPs", {"GetMultipleHNAPs": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert headers["SOAPACTION"] == '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"'

    def test_login_action_uses_login_uri(self, driver):
        mock_response = MagicMock()
        mock_response.json.return_value = HNAP_LOGIN_PHASE1
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post:
            driver._hnap_post("Login", {"Login": {}}, auth=False)

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert headers["SOAPACTION"] == '"http://purenetworks.com/HNAP1/Login"'

    def test_no_auth_header_when_auth_false(self, driver):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post:
            driver._hnap_post("Login", {"Login": {}}, auth=False)

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert "HNAP_AUTH" not in headers


# -- Downstream SC-QAM --

class TestDownstreamSCQAM:
    def test_channel_count(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32

    def test_first_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 43
        assert ch["frequency"] == "705 MHz"
        assert ch["powerLevel"] == 0.0
        assert ch["mer"] == 40.9
        assert ch["mse"] == -40.9
        assert ch["modulation"] == "256QAM"
        assert ch["corrErrors"] == 31
        assert ch["nonCorrErrors"] == 0

    def test_leading_space_power_parsed(self, mock_hnap):
        """Power values with leading space (' 0.0') parse correctly."""
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["powerLevel"] == 0.0

    def test_negative_power(self, mock_hnap):
        """Channels with negative power values."""
        data = mock_hnap.get_docsis_data()
        # Channel 17 (index 16) has power -0.1
        ch = data["channelDs"]["docsis30"][16]
        assert ch["powerLevel"] == -0.1

    def test_frequency_conversion(self, mock_hnap):
        """Hz values are converted to MHz."""
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["frequency"] == "705 MHz"
        # 29.2 MHz would be fractional
        freqs = [ch["frequency"] for ch in data["channelDs"]["docsis30"]]
        assert all("MHz" in f for f in freqs)

    def test_last_channel(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][-1]
        assert ch["channelID"] == 42
        assert ch["frequency"] == "645 MHz"


# -- Downstream OFDM --

class TestDownstreamOFDM:
    def test_ofdm_in_docsis31(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelDs"]["docsis31"]) == 1

    def test_ofdm_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis31"][0]
        assert ch["channelID"] == 193
        assert ch["type"] == "OFDM"
        assert ch["frequency"] == "957 MHz"
        assert ch["powerLevel"] == 0.1
        assert ch["mer"] == 43.0
        assert ch["mse"] is None
        assert ch["corrErrors"] == 2467857853
        assert ch["nonCorrErrors"] == 7894


# -- Upstream SC-QAM --

class TestUpstreamSCQAM:
    def test_locked_count(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelUs"]["docsis30"]) == 4

    def test_first_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["channelID"] == 3
        assert ch["frequency"] == "29.2 MHz"
        assert ch["powerLevel"] == 46.5
        assert ch["modulation"] == "SC-QAM"
        assert ch["multiplex"] == "SC-QAM"

    def test_all_upstream_channel_ids(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ids = [ch["channelID"] for ch in data["channelUs"]["docsis30"]]
        assert ids == [3, 4, 2, 1]


# -- Upstream OFDMA --

class TestUpstreamOFDMA:
    def test_ofdma_in_docsis31(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelUs"]["docsis31"]) == 1

    def test_ofdma_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelUs"]["docsis31"][0]
        assert ch["channelID"] == 41
        assert ch["type"] == "OFDMA"
        assert ch["frequency"] == "36.2 MHz"
        assert ch["powerLevel"] == 43.8
        assert ch["modulation"] == "OFDMA"
        assert ch["multiplex"] == ""


# -- Device info --

class TestDeviceInfo:
    def test_model_name(self, mock_hnap):
        info = mock_hnap.get_device_info()
        assert info["manufacturer"] == "Arris"
        assert info["model"] == "S34"

    def test_sw_version(self, mock_hnap):
        info = mock_hnap.get_device_info()
        assert info["sw_version"] == "2.5.0.1-2-GA"

    def test_connection_info_empty(self, driver):
        assert driver.get_connection_info() == {}

    def test_device_info_fallback_on_error(self, driver):
        with patch.object(driver, "_hnap_post", side_effect=Exception("network")):
            info = driver.get_device_info()
            assert info["manufacturer"] == "Arris"
            assert info["model"] == ""

    def test_device_info_error_invalidates_session(self, driver):
        """get_device_info failure marks session as dead so get_docsis_data re-auths."""
        driver._logged_in = True
        with patch.object(driver, "_hnap_post", side_effect=Exception("500")):
            driver.get_device_info()
        assert driver._logged_in is False


class TestDataFetchRetry:
    def test_retry_on_http_500(self, driver):
        """get_docsis_data retries with fresh login on HTTP 500."""
        import requests as req

        calls = []

        def mock_fetch():
            calls.append(1)
            if len(calls) == 1:
                resp = MagicMock()
                resp.status_code = 500
                raise req.HTTPError(response=resp)
            return {
                "channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []},
            }

        def mock_login_post(action, body, auth=True):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_fetch_docsis_data", side_effect=mock_fetch), \
             patch.object(driver, "_hnap_post", side_effect=mock_login_post):
            data = driver.get_docsis_data()

        assert len(calls) == 2
        assert "channelDs" in data

    def test_no_retry_on_success(self, mock_hnap):
        """Successful data fetch does not trigger retry logic."""
        data = mock_hnap.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32


# -- Value helpers --

class TestValueHelpers:
    def test_hz_to_mhz_integer(self):
        assert SurfboardDriver._hz_to_mhz(705000000) == "705 MHz"

    def test_hz_to_mhz_decimal(self):
        assert SurfboardDriver._hz_to_mhz(29200000) == "29.2 MHz"

    def test_hz_to_mhz_zero(self):
        assert SurfboardDriver._hz_to_mhz(0) == "0 MHz"

    def test_hz_to_mhz_fractional(self):
        assert SurfboardDriver._hz_to_mhz(36200000) == "36.2 MHz"

    def test_normalize_modulation(self):
        assert SurfboardDriver._normalize_modulation("256QAM") == "256QAM"
        assert SurfboardDriver._normalize_modulation(" OFDM PLC ") == "OFDM PLC"
        assert SurfboardDriver._normalize_modulation("") == ""


# -- Empty / edge cases --

class TestEdgeCases:
    def test_empty_downstream(self, driver):
        with patch.object(driver, "_hnap_post", return_value={
            "GetMultipleHNAPsResponse": {
                "GetCustomerStatusDownstreamChannelInfoResponse": {"CustomerConnDownstreamChannel": ""},
                "GetCustomerStatusUpstreamChannelInfoResponse": {"CustomerConnUpstreamChannel": ""},
            }
        }):
            data = driver.get_docsis_data()
            assert data["channelDs"]["docsis30"] == []
            assert data["channelDs"]["docsis31"] == []
            assert data["channelUs"]["docsis30"] == []
            assert data["channelUs"]["docsis31"] == []

    def test_unlocked_channels_skipped(self, driver):
        raw = "1^Not Locked^256QAM^99^705000000^0.0^40.9^0^0^"
        with patch.object(driver, "_hnap_post", return_value={
            "GetMultipleHNAPsResponse": {
                "GetCustomerStatusDownstreamChannelInfoResponse": {"CustomerConnDownstreamChannel": raw},
                "GetCustomerStatusUpstreamChannelInfoResponse": {"CustomerConnUpstreamChannel": ""},
            }
        }):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 0

    def test_malformed_channel_skipped(self, driver):
        raw = "1^Locked^256QAM^43^"  # Too few fields
        with patch.object(driver, "_hnap_post", return_value={
            "GetMultipleHNAPsResponse": {
                "GetCustomerStatusDownstreamChannelInfoResponse": {"CustomerConnDownstreamChannel": raw},
                "GetCustomerStatusUpstreamChannelInfoResponse": {"CustomerConnUpstreamChannel": ""},
            }
        }):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 0


# -- Analyzer integration --

class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_hnap):
        """Verify SURFboard output feeds cleanly into the analyzer."""
        from app.analyzer import analyze
        data = mock_hnap.get_docsis_data()
        result = analyze(data)

        # 32 SC-QAM + 1 OFDM = 33 downstream
        assert result["summary"]["ds_total"] == 33
        # 4 SC-QAM + 1 OFDMA = 5 upstream
        assert result["summary"]["us_total"] == 5
        assert result["summary"]["health"] in ("good", "tolerated", "marginal", "poor", "critical")
        assert len(result["ds_channels"]) == 33
        assert len(result["us_channels"]) == 5

    def test_qam_channels_labeled_docsis30(self, mock_hnap):
        from app.analyzer import analyze
        data = mock_hnap.get_docsis_data()
        result = analyze(data)

        qam_ids = {ch["channelID"] for ch in data["channelDs"]["docsis30"]}
        qam_ds = [c for c in result["ds_channels"] if c["channel_id"] in qam_ids]
        assert len(qam_ds) == 32
        for ch in qam_ds:
            assert ch["docsis_version"] == "3.0"

    def test_ofdm_channels_labeled_docsis31(self, mock_hnap):
        from app.analyzer import analyze
        data = mock_hnap.get_docsis_data()
        result = analyze(data)

        ofdm_ids = {ch["channelID"] for ch in data["channelDs"]["docsis31"]}
        ofdm_ds = [c for c in result["ds_channels"] if c["channel_id"] in ofdm_ids]
        assert len(ofdm_ds) == 1
        for ch in ofdm_ds:
            assert ch["docsis_version"] == "3.1"


