"""Tests for SurfboardDriver HTML fallback (broken HNAP firmware)."""

import base64

import pytest
import requests
from unittest.mock import patch, MagicMock

from app.drivers.surfboard import SurfboardDriver


STATUS_HTML = """
<html><body>
<table>
<tr><td colspan="8"><strong>Downstream Bonded Channels</strong></td></tr>
<tr><th>Channel ID</th><th>Lock Status</th><th>Modulation</th><th>Frequency</th>
    <th>Power</th><th>SNR/MER</th><th>Corrected</th><th>Uncorrectables</th></tr>
<tr><td>1</td><td>Locked</td><td>256QAM</td><td>705000000 Hz</td>
    <td>0.0 dBmV</td><td>40.9 dB</td><td>31</td><td>0</td></tr>
</table>
<table>
<tr><td colspan="7"><strong>Upstream Bonded Channels</strong></td></tr>
<tr><th>Channel</th><th>Channel ID</th><th>Lock Status</th><th>US Channel Type</th>
    <th>Frequency</th><th>Width</th><th>Power</th></tr>
<tr><td>1</td><td>3</td><td>Locked</td><td>SC-QAM Upstream</td>
    <td>29200000 Hz</td><td>6400000 Hz</td><td>46.5 dBmV</td></tr>
</table>
</body></html>
"""


@pytest.fixture
def driver():
    return SurfboardDriver("https://192.168.100.1", "admin", "password")


# -- Fallback activation --


class TestHtmlFallbackActivation:
    def test_hnap_success_does_not_activate_html(self, driver):
        """Normal HNAP login works, _html_mode stays False."""
        with patch.object(driver, "_do_login"):
            driver.login()

        assert driver._html_mode is False
        assert driver._logged_in is True

    def test_hnap_conn_error_exhausted_activates_html(self, driver):
        """When HNAP exhausts retries, HTML fallback activates."""
        call_count = []

        def fail_hnap():
            call_count.append(1)
            raise requests.ConnectionError("refused")

        def html_login_ok():
            driver._html_status_cache = STATUS_HTML
            driver._logged_in = True

        with patch.object(driver, "_do_login", side_effect=fail_hnap), \
             patch.object(driver, "_html_login", side_effect=html_login_ok), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert driver._html_mode is True
        assert driver._logged_in is True

    def test_html_mode_persists_across_polls(self, driver):
        """Once _html_mode=True, subsequent login() calls use _html_login."""
        driver._html_mode = True
        driver._logged_in = False

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = STATUS_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(driver._session, "get", return_value=mock_resp) as mock_get:
            driver.login()

        assert driver._logged_in is True
        # Verify it used HTML path (GET), not HNAP (POST)
        mock_get.assert_called_once()
        url = mock_get.call_args[0][0]
        assert "/cmconnectionstatus.html?login_" in url

    def test_html_fallback_failure_raises_both_errors(self, driver):
        """When both HNAP (ConnectionError) and HTML fail, both errors are reported."""
        def fail_hnap():
            raise requests.ConnectionError("HNAP refused")

        def fail_html():
            raise RuntimeError("SURFboard HTML login failed: timeout")

        with patch.object(driver, "_do_login", side_effect=fail_hnap), \
             patch.object(driver, "_html_login", side_effect=fail_html), \
             patch("app.drivers.surfboard.time"), \
             pytest.raises(RuntimeError, match="HNAP refused.*HTML fallback also failed.*timeout"):
            driver.login()

    def test_html_fallback_failure_ssl_raises_both_errors(self, driver):
        """When both HNAP (SSLError) and HTML fail, both errors are reported."""
        def fail_hnap():
            raise requests.exceptions.SSLError("TLS handshake failure")

        def fail_html():
            raise RuntimeError("SURFboard HTML login failed: no channel data")

        with patch.object(driver, "_do_login", side_effect=fail_hnap), \
             patch.object(driver, "_html_login", side_effect=fail_html), \
             patch("app.drivers.surfboard.time"), \
             pytest.raises(RuntimeError, match="TLS error.*HTML fallback also failed.*no channel data"):
            driver.login()


# -- HTML login --


class TestHtmlLogin:
    def test_html_login_url_format(self, driver):
        """Verify URL contains login_{base64(user:password)}."""
        expected_creds = base64.b64encode(b"admin:password").decode()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = STATUS_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(driver._session, "get", return_value=mock_resp) as mock_get:
            driver._html_login()

        url = mock_get.call_args[0][0]
        assert f"login_{expected_creds}" in url
        assert url.startswith("https://192.168.100.1/cmconnectionstatus.html?")

    def test_html_login_caches_status_html(self, driver):
        """After successful HTML login, _html_status_cache is set."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = STATUS_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(driver._session, "get", return_value=mock_resp):
            driver._html_login()

        assert driver._html_status_cache == STATUS_HTML
        assert driver._logged_in is True

    def test_html_login_http_error_does_not_expose_credentials(self):
        """HTTP failures report only the response status, not request secrets."""
        credential_marker = "CODEQL_ALERT_96_CREDENTIAL_MARKER"
        credential_value = "CODEQL_ALERT_96_PASSWORD"
        encoded_credentials = base64.b64encode(
            f"{credential_marker}:{credential_value}".encode()
        ).decode()
        request_url = (
            "https://192.168.100.1/cmconnectionstatus.html"
            f"?marker={credential_marker}&login_{encoded_credentials}"
        )
        request = requests.Request("GET", request_url).prepare()
        response = requests.Response()
        response.status_code = 401
        response.request = request
        response.url = request_url
        raw_error = f"unique raw HTTP error for {request_url}"
        error = requests.HTTPError(
            raw_error, request=request, response=response
        )
        driver = SurfboardDriver(
            "https://192.168.100.1", credential_marker, credential_value
        )

        with patch.object(driver._session, "get", side_effect=error), \
             pytest.raises(RuntimeError) as exc_info:
            driver._html_login()

        error_text = str(exc_info.value)
        assert error_text == "SURFboard HTML login failed (HTTP 401)"
        assert credential_marker not in error_text
        assert encoded_credentials not in error_text
        assert request_url not in error_text
        assert raw_error not in error_text
        assert exc_info.value.__cause__ is error

    def test_html_login_connection_error_does_not_expose_message(self, driver):
        """Transport failures report the exception type without its message."""
        sensitive_marker = "CODEQL_ALERT_96_CONNECTION_SECRET"
        raw_error = f"connection refused with secret {sensitive_marker}"
        error = requests.ConnectionError(raw_error)

        with patch.object(driver._session, "get", side_effect=error), \
             pytest.raises(RuntimeError) as exc_info:
            driver._html_login()

        error_text = str(exc_info.value)
        assert error_text == "SURFboard HTML login failed: ConnectionError"
        assert sensitive_marker not in error_text
        assert raw_error not in error_text
        assert exc_info.value.__cause__ is error

    def test_html_login_retry_warning_does_not_log_response_body(
        self, driver, caplog
    ):
        """The retry warning reports size without exposing response content."""
        sensitive_marker = "CODEQL_ALERT_96_SECRET_MARKER"
        response_body = f"<html><body>{sensitive_marker}: login failed</body></html>"

        caplog.set_level("WARNING", logger="docsis.driver.surfboard")
        with patch.object(driver, "_fresh_session") as fresh_session, \
             patch.object(
                 driver,
                 "_html_login_attempt",
                 side_effect=[response_body, STATUS_HTML],
             ):
            driver._html_login()

        fresh_session.assert_called_once_with()
        assert driver._logged_in is True
        assert "non-channel response" in caplog.text
        assert "resetting session and retrying" in caplog.text
        assert f"{len(response_body)} bytes" in caplog.text
        assert sensitive_marker not in caplog.text
        assert response_body not in caplog.text

    def test_html_login_rejects_short_response_without_exposing_body(self, driver):
        """The final transient error reports size without exposing response content."""
        sensitive_marker = "CODEQL_ALERT_96_FINAL_SECRET_MARKER"
        first_body = "<html><body>Login</body></html>"
        response_body = f"<html><body>{sensitive_marker}: access denied</body></html>"

        from app.drivers.surfboard import TransientHtmlChannelPageError
        with patch.object(driver, "_fresh_session"), \
             patch.object(
                 driver,
                 "_html_login_attempt",
                 side_effect=[first_body, response_body],
             ):
            with pytest.raises(TransientHtmlChannelPageError) as exc_info:
                driver._html_login()

        error_text = str(exc_info.value)
        assert "non-channel response after retry" in error_text
        assert f"({len(response_body)} bytes)" in error_text
        assert sensitive_marker not in error_text
        assert response_body not in error_text
        assert driver._logged_in is False

    def test_html_login_rejects_response_without_downstream(self, driver):
        """HTML login rejects responses that don't contain 'downstream' after retry."""
        from app.drivers.surfboard import TransientHtmlChannelPageError
        with patch.object(driver, "_fresh_session"), \
             patch.object(driver, "_html_login_attempt", return_value="x" * 600):
            with pytest.raises(TransientHtmlChannelPageError, match="non-channel response after retry"):
                driver._html_login()

    def test_html_login_two_step_token_flow(self, driver):
        """SB8200 two-step login: first request returns token, second returns page."""
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.text = "g41RVNXNpuhbYnriIr24TOdXxInHu4o"
        token_resp.raise_for_status = MagicMock()

        page_resp = MagicMock()
        page_resp.status_code = 200
        page_resp.text = STATUS_HTML
        page_resp.raise_for_status = MagicMock()

        with patch.object(
            driver._session, "get", side_effect=[token_resp, page_resp]
        ) as mock_get:
            driver._html_login()

        assert driver._logged_in is True
        assert driver._html_status_cache == STATUS_HTML
        # Second request should use ct_ prefix + token
        second_url = mock_get.call_args_list[1][0][0]
        assert "?ct_g41RVNXNpuhbYnriIr24TOdXxInHu4o" in second_url

    def test_html_login_two_step_token_already_has_prefix(self, driver):
        """Token response that already includes ct_ prefix is not doubled."""
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.text = "ct_abcdef123456"
        token_resp.raise_for_status = MagicMock()

        page_resp = MagicMock()
        page_resp.status_code = 200
        page_resp.text = STATUS_HTML
        page_resp.raise_for_status = MagicMock()

        with patch.object(
            driver._session, "get", side_effect=[token_resp, page_resp]
        ) as mock_get:
            driver._html_login()

        second_url = mock_get.call_args_list[1][0][0]
        assert "?ct_abcdef123456" in second_url
        assert "ct_ct_" not in second_url

    def test_html_login_two_step_empty_token_fails(self, driver):
        """Two-step flow with empty token response still fails validation after retry."""
        from app.drivers.surfboard import TransientHtmlChannelPageError
        with patch.object(driver, "_fresh_session"), \
             patch.object(driver, "_html_login_attempt", return_value=""):
            with pytest.raises(TransientHtmlChannelPageError, match="non-channel response after retry"):
                driver._html_login()


# -- HTML data fetch --


class TestHtmlDataFetch:
    def test_html_mode_get_docsis_data(self, driver):
        """With _html_mode=True and cache set, returns parsed channel data."""
        driver._html_mode = True
        driver._html_status_cache = STATUS_HTML

        result = driver.get_docsis_data()

        ds30 = result["channelDs"]["docsis30"]
        us30 = result["channelUs"]["docsis30"]
        assert len(ds30) == 1
        assert ds30[0]["channelID"] == 1
        assert ds30[0]["frequency"] == "705 MHz"
        assert ds30[0]["powerLevel"] == 0.0
        assert ds30[0]["mer"] == 40.9
        assert len(us30) == 1
        assert us30[0]["channelID"] == 3
        assert us30[0]["frequency"] == "29.2 MHz"
        assert us30[0]["powerLevel"] == 46.5

    def test_html_mode_refetches_when_cache_empty(self, driver):
        """When cache is None, _html_get_docsis_data calls _html_login first."""
        driver._html_mode = True
        driver._html_status_cache = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = STATUS_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(driver._session, "get", return_value=mock_resp) as mock_get:
            result = driver.get_docsis_data()

        mock_get.assert_called_once()
        assert len(result["channelDs"]["docsis30"]) == 1
        # Cache should be consumed after fetch
        assert driver._html_status_cache is None


# -- HTML device info --


class TestHtmlDeviceInfo:
    def test_html_mode_device_info(self, driver):
        """Returns Arris/SB8200 in HTML mode."""
        driver._html_mode = True

        info = driver.get_device_info()

        assert info["manufacturer"] == "Arris"
        assert info["model"] == "SB8200"
        assert info["sw_version"] == ""


# -- Existing HNAP unchanged --


class TestExistingHnapUnchanged:
    def test_normal_hnap_login_unchanged(self, driver):
        """Verify the existing HNAP login flow still works when _do_login succeeds."""
        with patch.object(driver, "_do_login"):
            driver.login()

        assert driver._logged_in is True
        assert driver._html_mode is False

    def test_connection_error_retry_still_works(self, driver):
        """Verify HNAP connection error retry (< 3 errors) still retries without HTML."""
        attempt_count = []

        def mock_do_login():
            attempt_count.append(1)
            if len(attempt_count) < 3:
                raise requests.ConnectionError("reset")
            # Third attempt succeeds

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert len(attempt_count) == 3
        assert driver._logged_in is True
        assert driver._html_mode is False
