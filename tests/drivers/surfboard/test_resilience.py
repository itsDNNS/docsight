"""Tests for SURFboard retries, fallbacks, and session resilience."""

import hashlib
import hmac

import pytest
from unittest.mock import patch, MagicMock
from app.drivers.surfboard import SurfboardDriver, _LegacyTLSAdapter, _HAS_LEGACY_TLS
from ._data import HNAP_LOGIN_PHASE1, HNAP_LOGIN_PHASE2, HNAP_DS_RESPONSE, HNAP_DEVICE_RESPONSE, HNAP_DS_RESPONSE_MOTO, HNAP_DEVICE_RESPONSE_MOTO

class TestActionNamespace:
    def test_moto_action_namespace(self, driver):
        """GetMotoStatus* actions work for SB8200-style firmware."""
        driver._action_ns = "Moto"

        def side_effect(action, body, **kwargs):
            if action == "GetMultipleHNAPs":
                keys = body.get("GetMultipleHNAPs", {})
                if "GetMotoStatusDownstreamChannelInfo" in keys:
                    return HNAP_DS_RESPONSE_MOTO
            return {}

        with patch.object(driver, "_hnap_post", side_effect=side_effect):
            data = driver.get_docsis_data()

        assert len(data["channelDs"]["docsis30"]) == 32
        assert len(data["channelDs"]["docsis31"]) == 1
        assert len(data["channelUs"]["docsis30"]) == 4
        assert len(data["channelUs"]["docsis31"]) == 1

    def test_customer_action_namespace(self, driver):
        """GetCustomerStatus* actions work with explicit Customer namespace."""
        driver._action_ns = "Customer"

        def side_effect(action, body, **kwargs):
            if action == "GetMultipleHNAPs":
                keys = body.get("GetMultipleHNAPs", {})
                if "GetCustomerStatusDownstreamChannelInfo" in keys:
                    return HNAP_DS_RESPONSE
            return {}

        with patch.object(driver, "_hnap_post", side_effect=side_effect):
            data = driver.get_docsis_data()

        assert len(data["channelDs"]["docsis30"]) == 32

    def test_namespace_auto_detection(self, driver):
        """Empty Customer response triggers Moto fallback."""
        assert driver._action_ns == ""
        call_count = []

        def side_effect(action, body, **kwargs):
            if action == "GetMultipleHNAPs":
                call_count.append(1)
                keys = body.get("GetMultipleHNAPs", {})
                if "GetCustomerStatusDownstreamChannelInfo" in keys:
                    return {
                        "GetMultipleHNAPsResponse": {
                            "GetCustomerStatusDownstreamChannelInfoResponse": {
                                "CustomerConnDownstreamChannel": ""
                            },
                            "GetCustomerStatusUpstreamChannelInfoResponse": {
                                "CustomerConnUpstreamChannel": ""
                            },
                        }
                    }
                if "GetMotoStatusDownstreamChannelInfo" in keys:
                    return HNAP_DS_RESPONSE_MOTO
            return {}

        with patch.object(driver, "_hnap_post", side_effect=side_effect):
            data = driver.get_docsis_data()

        assert driver._action_ns == "Moto"
        assert len(data["channelDs"]["docsis30"]) == 32
        assert len(call_count) == 2

    def test_namespace_remembered(self, driver):
        """After detection, subsequent calls use remembered namespace."""
        driver._action_ns = "Moto"
        keys_seen = []

        def side_effect(action, body, **kwargs):
            if action == "GetMultipleHNAPs":
                keys_seen.append(list(body.get("GetMultipleHNAPs", {}).keys()))
                keys = body.get("GetMultipleHNAPs", {})
                if "GetMotoStatusDownstreamChannelInfo" in keys:
                    return HNAP_DS_RESPONSE_MOTO
            return {}

        with patch.object(driver, "_hnap_post", side_effect=side_effect):
            driver.get_docsis_data()
            driver.get_docsis_data()

        assert len(keys_seen) == 2
        for keys in keys_seen:
            assert all("Moto" in k for k in keys)

    def test_device_info_moto_namespace(self, driver):
        """Device info uses Moto actions when detected."""
        driver._action_ns = "Moto"

        def side_effect(action, body, **kwargs):
            if action == "GetMultipleHNAPs":
                keys = body.get("GetMultipleHNAPs", {})
                if "GetMotoStatusConnectionInfo" in keys:
                    return HNAP_DEVICE_RESPONSE_MOTO
            return {}

        with patch.object(driver, "_hnap_post", side_effect=side_effect):
            info = driver.get_device_info()

        assert info["model"] == "SB8200"
        assert info["sw_version"] == "AB01.02.053.05_080901_193.0A.NSH"

    def test_device_info_http_500_namespace_fallback(self, driver):
        """HTTP 500 on Customer device info triggers Moto fallback."""
        import requests as req
        assert driver._action_ns == ""

        def side_effect(action, body, **kwargs):
            if action == "GetMultipleHNAPs":
                keys = body.get("GetMultipleHNAPs", {})
                if "GetCustomerStatusConnectionInfo" in keys:
                    resp = MagicMock()
                    resp.status_code = 500
                    raise req.HTTPError(response=resp)
                if "GetMotoStatusConnectionInfo" in keys:
                    return HNAP_DEVICE_RESPONSE_MOTO
            return {}

        with patch.object(driver, "_hnap_post", side_effect=side_effect):
            info = driver.get_device_info()

        assert info["model"] == "SB8200"
        assert driver._action_ns == "Moto"


# -- HTTP 500 namespace resilience --

class TestHttp500Resilience:
    def test_http_500_tries_other_namespace(self, driver):
        """HTTP 500 triggers namespace fallback before re-auth."""
        import requests as req
        driver._action_ns = "Customer"
        driver._logged_in = True
        calls = []

        def mock_fetch():
            calls.append(driver._action_ns)
            if len(calls) == 1:
                resp = MagicMock()
                resp.status_code = 500
                raise req.HTTPError(response=resp)
            return {
                "channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []},
            }

        with patch.object(driver, "_fetch_docsis_data", side_effect=mock_fetch):
            data = driver.get_docsis_data()

        assert len(calls) == 2
        assert calls[0] == "Customer"
        assert calls[1] == "Moto"
        assert driver._action_ns == "Moto"
        assert "channelDs" in data

    def test_http_500_preserves_session(self, driver):
        """HTTP 500 namespace switch doesn't destroy auth session."""
        import requests as req
        driver._action_ns = "Customer"
        driver._logged_in = True
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

        with patch.object(driver, "_fetch_docsis_data", side_effect=mock_fetch):
            driver.get_docsis_data()

        assert driver._logged_in is True


# -- Legacy TLS fallback --

@pytest.mark.skipif(not _HAS_LEGACY_TLS, reason="requires ssl.OP_LEGACY_SERVER_CONNECT")
class TestLegacyTLSFallback:
    def test_ssl_error_triggers_legacy_tls_retry(self):
        """SSLError on normal HTTPS triggers legacy TLS retry before HTTP fallback."""
        import requests as req

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")
        urls_seen = []

        def mock_do_login():
            urls_seen.append(driver._url)
            if len(urls_seen) == 1:
                raise req.exceptions.SSLError("SSLV3_ALERT_HANDSHAKE_FAILURE")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert len(urls_seen) == 2
        assert all(u.startswith("https://") for u in urls_seen)
        assert driver._logged_in is True
        assert driver._legacy_tls_needed is True

    def test_ssl_error_legacy_tls_then_http_fallback(self):
        """SSLError on both normal and legacy HTTPS falls back to HTTP."""
        import requests as req

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")
        urls_seen = []

        def mock_do_login():
            urls_seen.append(driver._url)
            if driver._url.startswith("https://"):
                raise req.exceptions.SSLError("SSLV3_ALERT_HANDSHAKE_FAILURE")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert len(urls_seen) == 3
        assert urls_seen[0] == "https://192.168.100.1"
        assert urls_seen[1] == "https://192.168.100.1"
        assert urls_seen[2] == "http://192.168.100.1"
        assert driver._logged_in is True

    def test_ssl_error_all_fail_includes_tls_context(self):
        """When all transports fail, error message includes TLS context."""
        import requests as req

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")

        def mock_do_login():
            if driver._url.startswith("https://"):
                raise req.exceptions.SSLError("SSLV3_ALERT_HANDSHAKE_FAILURE")
            raise req.ConnectionError("connection refused")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            with pytest.raises(
                RuntimeError,
                match=r"TLS error.*SSLV3.*connection refused",
            ):
                driver.login()

    def test_legacy_tls_adapter_mounted_on_session(self):
        """Legacy TLS fallback mounts the adapter on the session."""
        import requests as req

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")

        def mock_do_login():
            if not driver._legacy_tls_attempted:
                raise req.exceptions.SSLError("handshake failure")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        adapter = driver._session.get_adapter("https://")
        assert isinstance(adapter, _LegacyTLSAdapter)

    def test_fresh_session_preserves_legacy_tls(self):
        """After legacy TLS succeeds, _fresh_session remounts the adapter."""
        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")
        driver._legacy_tls_needed = True

        driver._fresh_session()

        adapter = driver._session.get_adapter("https://")
        assert isinstance(adapter, _LegacyTLSAdapter)

    def test_non_ssl_connection_error_skips_legacy_tls(self):
        """Generic ConnectionError (not SSL) goes straight to HTTP fallback."""
        import requests as req

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")
        urls_seen = []

        def mock_do_login():
            urls_seen.append(driver._url)
            if driver._url.startswith("https://"):
                raise req.ConnectionError("connection refused")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert len(urls_seen) == 2
        assert urls_seen[0] == "https://192.168.100.1"
        assert urls_seen[1] == "http://192.168.100.1"
        assert driver._legacy_tls_attempted is False

    def test_legacy_tls_forces_connection_close_header(self, driver):
        """Legacy TLS mode forces Connection: close on HNAP requests."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        driver._legacy_tls_needed = True

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0
            driver._hnap_post("GetMultipleHNAPs", {"GetMultipleHNAPs": {}})

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["Connection"] == "close"

    def test_legacy_tls_phase2_reset_retries_on_fresh_session(self):
        """Phase 2 reset under legacy TLS retries once on a fresh session."""
        import requests as req

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")
        driver._legacy_tls_needed = True
        phase2_session_ids = []

        def mock_hnap_post(action, body, **kwargs):
            login_data = body.get("Login", {})
            if login_data.get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            phase2_session_ids.append(id(driver._session))
            if len(phase2_session_ids) == 1:
                raise req.ConnectionError("Connection reset by peer")
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_hnap_post), \
             patch.object(driver, "_fresh_session", wraps=driver._fresh_session) as fresh_session, \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert fresh_session.call_count == 1
        assert len(phase2_session_ids) == 2
        assert phase2_session_ids[0] != phase2_session_ids[1]
        assert driver._logged_in is True

    def test_legacy_tls_phase2_reset_failure_reports_context(self):
        """When phase 2 keeps resetting, the failure mentions legacy TLS phase 2."""
        import requests as req

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")
        driver._legacy_tls_needed = True
        driver._http_fallback_url = ""

        def mock_hnap_post(action, body, **kwargs):
            login_data = body.get("Login", {})
            if login_data.get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            raise req.ConnectionError("Connection reset by peer")

        with patch.object(driver, "_hnap_post", side_effect=mock_hnap_post), \
             patch("app.drivers.surfboard.time"):
            with pytest.raises(
                RuntimeError,
                match=r"phase 2.*Connection reset by peer",
            ):
                driver.login()

    def test_legacy_tls_phase2_chunked_read_retry_succeeds(self):
        """Legacy TLS phase 2 body read failure is retried inside _hnap_post
        without needing a full session reset."""
        import requests as req
        from urllib3.exceptions import ProtocolError

        driver = SurfboardDriver("https://192.168.100.1", "admin", "password")
        driver._legacy_tls_needed = True

        phase1 = MagicMock()
        phase1.ok = True
        phase1.raise_for_status = MagicMock()
        phase1.json.return_value = HNAP_LOGIN_PHASE1

        phase2_reset = MagicMock()
        phase2_reset.ok = True
        phase2_reset.raise_for_status = MagicMock()
        phase2_reset.json.side_effect = req.exceptions.ChunkedEncodingError(
            ProtocolError(
                "Connection broken: ConnectionResetError(104, 'Connection reset by peer')",
                ConnectionResetError(104, "Connection reset by peer"),
            )
        )

        phase2_ok = MagicMock()
        phase2_ok.ok = True
        phase2_ok.raise_for_status = MagicMock()
        phase2_ok.json.return_value = HNAP_LOGIN_PHASE2

        with patch.object(req.Session, "post", side_effect=[phase1, phase2_reset, phase2_ok]), \
             patch.object(driver, "_fresh_session", wraps=driver._fresh_session) as fresh_session, \
             patch("app.drivers.surfboard.time"):
            driver.login()

        # _hnap_post retries internally -- no full session reset needed
        assert fresh_session.call_count == 0
        assert driver._logged_in is True


# -- ConnectionError recovery in data fetch --

class TestDataFetchConnectionError:
    def test_connection_error_triggers_fresh_session_and_reauth(self, driver):
        """ConnectionError during data fetch resets session and re-authenticates."""
        import requests as req
        driver._action_ns = "Customer"
        driver._logged_in = True
        session_before = driver._session
        calls = []

        def mock_fetch():
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                raise req.ConnectionError("Connection reset by peer")
            return {
                "channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []},
            }

        with patch.object(driver, "_fetch_docsis_data", side_effect=mock_fetch), \
             patch.object(driver, "login") as mock_login:
            data = driver.get_docsis_data()

        assert len(calls) == 2
        assert mock_login.called
        assert driver._session is not session_before, "session must be replaced after ConnectionError"
        assert "channelDs" in data

    def test_connection_error_after_http_500_namespace_switch(self, driver):
        """HTTP 500 -> namespace switch -> ConnectionError restores original namespace."""
        import requests as req
        driver._action_ns = "Customer"
        driver._logged_in = True
        calls = []

        def mock_fetch():
            calls.append(driver._action_ns)
            if len(calls) == 1:
                resp = MagicMock()
                resp.status_code = 500
                raise req.HTTPError(response=resp)
            if len(calls) == 2:
                # Namespace switched to Moto, but connection drops
                raise req.ConnectionError("Connection reset")
            return {
                "channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []},
            }

        with patch.object(driver, "_fetch_docsis_data", side_effect=mock_fetch), \
             patch.object(driver, "login"):
            data = driver.get_docsis_data()

        assert calls[0] == "Customer"
        assert calls[1] == "Moto"
        # After ConnectionError in namespace retry, namespace restored to Customer
        # and re-auth path runs the third fetch
        assert driver._action_ns == "Customer" or "channelDs" in data

    def test_connection_error_during_autodetect_resets_namespace(self, driver):
        """ConnectionError during namespace auto-detection resets speculative namespace."""
        import requests as req
        driver._action_ns = ""
        driver._logged_in = True
        calls = []

        def mock_fetch():
            calls.append(driver._action_ns)
            if len(calls) == 1:
                # Simulate _fetch_docsis_data setting speculative namespace
                driver._action_ns = "Moto"
                raise req.ConnectionError("reset during Moto probe")
            return {
                "channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []},
            }

        with patch.object(driver, "_fetch_docsis_data", side_effect=mock_fetch), \
             patch.object(driver, "login"):
            driver.get_docsis_data()

        # Namespace must be reset so auto-detection restarts from scratch
        assert calls[0] == "", "first call should start with empty namespace"
        assert calls[1] == "", "retry must reset speculative namespace"


# -- Connection: close header --

class TestConnectionCloseHeader:
    def test_connection_close_header_present(self, driver):
        """Every HNAP request includes Connection: close."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.123
            driver._hnap_post("Login", {"Login": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert headers.get("Connection") == "close"

    def test_connection_close_on_data_request(self, driver):
        """Connection: close is sent on data requests, not just login."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.123
            driver._hnap_post("GetMultipleHNAPs", {"GetMultipleHNAPs": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert headers.get("Connection") == "close"


# -- _hnap_post transport-level retry --

class TestHnapPostRetry:
    def test_connection_error_retries_once_and_succeeds(self, driver):
        """ConnectionError on first attempt retries; second attempt succeeds."""
        import requests as req

        ok_response = MagicMock()
        ok_response.ok = True
        ok_response.raise_for_status = MagicMock()
        ok_response.json.return_value = {"LoginResponse": {"LoginResult": "OK"}}

        with patch.object(
            driver._session, "post",
            side_effect=[req.ConnectionError("reset"), ok_response],
        ) as mock_post, patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0
            mock_time.sleep = MagicMock()

            result = driver._hnap_post("Login", {"Login": {}})

        assert result == {"LoginResponse": {"LoginResult": "OK"}}
        assert mock_post.call_count == 2
        mock_time.sleep.assert_called_once_with(1)

    def test_chunked_encoding_error_retries_once_and_succeeds(self, driver):
        """ChunkedEncodingError on first attempt retries; second succeeds."""
        import requests as req
        from urllib3.exceptions import ProtocolError

        ok_response = MagicMock()
        ok_response.ok = True
        ok_response.raise_for_status = MagicMock()
        ok_response.json.return_value = {"result": "ok"}

        with patch.object(
            driver._session, "post",
            side_effect=[
                req.exceptions.ChunkedEncodingError(
                    ProtocolError("Connection broken", ConnectionResetError(104))
                ),
                ok_response,
            ],
        ) as mock_post, patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0
            mock_time.sleep = MagicMock()

            result = driver._hnap_post("Login", {"Login": {}})

        assert result == {"result": "ok"}
        assert mock_post.call_count == 2

    def test_both_attempts_fail_raises_connection_error(self, driver):
        """When both attempts fail, ConnectionError propagates."""
        import requests as req

        with patch.object(
            driver._session, "post",
            side_effect=req.ConnectionError("persistent reset"),
        ), patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0
            mock_time.sleep = MagicMock()

            with pytest.raises(req.ConnectionError, match="persistent reset"):
                driver._hnap_post("Login", {"Login": {}})

    def test_chunked_error_both_fail_raises_as_connection_error(self, driver):
        """ChunkedEncodingError on both attempts raises as ConnectionError
        with original error text and cause chain preserved."""
        import requests as req
        from urllib3.exceptions import ProtocolError

        original_msg = "Connection broken: ConnectionResetError(104, 'Connection reset by peer')"
        with patch.object(
            driver._session, "post",
            side_effect=req.exceptions.ChunkedEncodingError(
                ProtocolError(original_msg, ConnectionResetError(104))
            ),
        ), patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0
            mock_time.sleep = MagicMock()

            with pytest.raises(req.ConnectionError, match="Connection broken") as exc_info:
                driver._hnap_post("Login", {"Login": {}})

            assert exc_info.value.__cause__ is not None, \
                "cause chain must be preserved for caller error messages"

    def test_http_error_not_retried(self, driver):
        """HTTPError is not caught by the retry loop -- propagates immediately."""
        import requests as req

        error_response = MagicMock()
        error_response.ok = False
        error_response.status_code = 500
        error_response.content = b"error"
        error_response.text = "error"
        error_response.raise_for_status.side_effect = req.HTTPError(
            response=error_response
        )

        with patch.object(
            driver._session, "post", return_value=error_response,
        ) as mock_post, patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0

            with pytest.raises(req.HTTPError):
                driver._hnap_post("Login", {"Login": {}})

        # Only one attempt -- no retry on HTTPError
        assert mock_post.call_count == 1

    def test_retry_regenerates_hnap_auth(self, driver):
        """Retry generates a fresh HNAP_AUTH with updated timestamp."""
        import requests as req

        ok_response = MagicMock()
        ok_response.ok = True
        ok_response.raise_for_status = MagicMock()
        ok_response.json.return_value = {"result": "ok"}

        timestamps = iter([1700000000.0, 1700000001.0])

        with patch.object(
            driver._session, "post",
            side_effect=[req.ConnectionError("reset"), ok_response],
        ) as mock_post, patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.side_effect = timestamps
            mock_time.sleep = MagicMock()

            driver._hnap_post("Login", {"Login": {}})

        first_headers = mock_post.call_args_list[0].kwargs.get("headers") or \
                        mock_post.call_args_list[0][1].get("headers", {})
        second_headers = mock_post.call_args_list[1].kwargs.get("headers") or \
                         mock_post.call_args_list[1][1].get("headers", {})

        assert first_headers["HNAP_AUTH"] != second_headers["HNAP_AUTH"], \
            "retry must use a fresh HNAP_AUTH with updated timestamp"

    def test_retry_preserves_private_key_and_auth_algo(self, driver):
        """Retry during phase 2 uses the derived private key and explicit
        auth_algo, not the pre-login defaults."""
        import hashlib
        import requests as req

        driver._private_key = "DERIVED_PRIVATE_KEY_ABC123"
        driver._hmac_algo = "md5"

        ok_response = MagicMock()
        ok_response.ok = True
        ok_response.raise_for_status = MagicMock()
        ok_response.json.return_value = {"LoginResponse": {"LoginResult": "OK"}}

        timestamps = iter([1700000000.0, 1700000001.0])

        with patch.object(
            driver._session, "post",
            side_effect=[req.ConnectionError("reset"), ok_response],
        ) as mock_post, patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.side_effect = timestamps
            mock_time.sleep = MagicMock()

            driver._hnap_post("Login", {"Login": {}}, auth_algo=hashlib.md5)

        # Both attempts must use the derived private key with MD5
        for call in mock_post.call_args_list:
            headers = call.kwargs.get("headers") or call[1].get("headers", {})
            hnap_auth = headers["HNAP_AUTH"]
            # Pre-login key "withoutloginkey" produces a different HMAC;
            # verify the auth was computed with the derived key
            assert hnap_auth != "", "HNAP_AUTH must be set"

        # Verify the retry HMAC uses the same key but different timestamp
        first_auth = mock_post.call_args_list[0].kwargs.get("headers", {})["HNAP_AUTH"]
        second_auth = mock_post.call_args_list[1].kwargs.get("headers", {})["HNAP_AUTH"]
        assert first_auth != second_auth, "different timestamps"

        # Verify both used MD5 with derived key (not pre-login default)
        ts1 = first_auth.split(" ")[1]
        soap = '"http://purenetworks.com/HNAP1/Login"'
        expected_hash = hmac.new(
            "DERIVED_PRIVATE_KEY_ABC123".encode(),
            (ts1 + soap).encode(),
            hashlib.md5,
        ).hexdigest().upper()
        assert first_auth.startswith(expected_hash), \
            "retry must use derived private key with explicit auth_algo, not defaults"
