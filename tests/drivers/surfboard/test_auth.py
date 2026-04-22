"""Tests for SURFboard login and HNAP auth flows."""

import hashlib
import hmac

import pytest
from unittest.mock import patch, MagicMock
from app.drivers.surfboard import SurfboardDriver, _HNAP_PRELOGIN_KEY
from ._data import HNAP_LOGIN_PHASE1, HNAP_LOGIN_PHASE2

class TestLogin:
    def test_login_two_phase_flow(self, driver):
        """Login calls _hnap_post twice: request then login."""
        calls = []

        def mock_post(action, body, **kwargs):
            calls.append((action, body.get("Login", {}).get("Action")))
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert len(calls) == 2
        assert calls[0] == ("Login", "request")
        assert calls[1] == ("Login", "login")

    def test_login_derives_private_key(self, driver):
        """PrivateKey = HMAC-SHA256(PublicKey+password, Challenge).upper()"""
        def mock_post(action, body, **kwargs):
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

        def mock_post(action, body, **kwargs):
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
        def mock_post(action, body, **kwargs):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert driver._cookie == "SESS_12345"

    def test_login_sets_prelogin_key_before_request(self, driver):
        """_try_login sets _private_key to 'withoutloginkey' before phase 1."""
        keys_seen = []

        def mock_post(action, body, **kwargs):
            keys_seen.append(driver._private_key)
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert keys_seen[0] == _HNAP_PRELOGIN_KEY

    def test_login_failure_raises(self, driver):
        def mock_post(action, body, **kwargs):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return {"LoginResponse": {"LoginResult": "FAILED"}}

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            with pytest.raises(RuntimeError, match="SURFboard login failed: FAILED"):
                driver.login()

    def test_login_no_challenge_raises(self, driver):
        def mock_post(action, body, **kwargs):
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

    def test_login_falls_back_to_http_after_https_connection_error(self):
        import requests as req

        driver = SurfboardDriver("http://192.168.100.1/", "admin", "password")
        urls_seen = []

        def mock_do_login():
            urls_seen.append(driver._url)
            if driver._url.startswith("https://"):
                raise req.ConnectionError("timeout")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert urls_seen == ["https://192.168.100.1", "http://192.168.100.1"]
        assert driver._url == "http://192.168.100.1"
        assert driver._logged_in is True

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

        def mock_post(action, body, **kwargs):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert driver._logged_in is True

    def test_login_md5_fallback(self, driver):
        """Login falls back to MD5 when SHA256 Phase 2 fails."""
        algos_tried = []

        def mock_post(action, body, **kwargs):
            algo = kwargs.get("auth_algo")
            login_data = body.get("Login", {})
            if login_data.get("Action") == "request":
                # Phase 1 is algorithm-agnostic, only called once
                return HNAP_LOGIN_PHASE1
            # Phase 2: SHA256 fails, MD5 succeeds
            if algo is hashlib.sha256:
                algos_tried.append("sha256")
                return {"LoginResponse": {"LoginResult": "FAILED"}}
            algos_tried.append("md5")
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert "sha256" in algos_tried
        assert "md5" in algos_tried
        assert driver._hmac_algo == "md5"

    def test_login_md5_fallback_single_phase1(self, driver):
        """Phase 1 (challenge request) only happens once, even with MD5 fallback."""
        phase1_count = []

        def mock_post(action, body, **kwargs):
            algo = kwargs.get("auth_algo")
            login_data = body.get("Login", {})
            if login_data.get("Action") == "request":
                phase1_count.append(1)
                return HNAP_LOGIN_PHASE1
            if algo is hashlib.sha256:
                return {"LoginResponse": {"LoginResult": "FAILED"}}
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        assert len(phase1_count) == 1

    def test_login_md5_key_derivation(self, driver):
        """When MD5 is detected, key derivation uses MD5."""
        def mock_post(action, body, **kwargs):
            algo = kwargs.get("auth_algo")
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            # SHA256 fails, MD5 succeeds
            if algo is hashlib.sha256:
                return {"LoginResponse": {"LoginResult": "FAILED"}}
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_hnap_post", side_effect=mock_post):
            driver.login()

        expected_key = hmac.new(
            ("PUB_KEY_9876" + "password").encode(),
            "ABCDEF1234567890".encode(),
            hashlib.md5,
        ).hexdigest().upper()
        assert driver._private_key == expected_key


# -- HNAP Auth header --

class TestHnapAuth:
    def test_auth_header_always_present(self, driver):
        """HNAP_AUTH is sent on every request, including login."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.123
            # No private key set -- should use withoutloginkey
            driver._hnap_post("Login", {"Login": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert "HNAP_AUTH" in headers

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

    def test_auth_uses_prelogin_key_when_no_private_key(self, driver):
        """Before login, HNAP_AUTH uses 'withoutloginkey'."""
        driver._private_key = ""

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_time.time.return_value = 1700000000.0
            driver._hnap_post("Login", {"Login": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})

            ts = str(int(1700000000.0 * 1000) % 2_000_000_000_000)
            soap_action = '"http://purenetworks.com/HNAP1/Login"'
            expected_hash = hmac.new(
                _HNAP_PRELOGIN_KEY.encode(),
                (ts + soap_action).encode(),
                hashlib.sha256,
            ).hexdigest().upper()

            assert headers["HNAP_AUTH"] == f"{expected_hash} {ts}"

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

    def test_auth_md5_when_detected(self, driver):
        """After MD5 detection, HNAP_AUTH uses MD5."""
        driver._private_key = "TESTKEY123"
        driver._hmac_algo = "md5"

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
                hashlib.md5,
            ).hexdigest().upper()

            assert headers["HNAP_AUTH"] == f"{expected_hash} {ts}"
            # MD5 produces 32-char hex
            auth_hash = headers["HNAP_AUTH"].split(" ")[0]
            assert len(auth_hash) == 32

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
            driver._hnap_post("Login", {"Login": {}})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert headers["SOAPACTION"] == '"http://purenetworks.com/HNAP1/Login"'

    def test_chunked_read_error_is_treated_as_connection_error(self, driver):
        """Body-read connection resets are normalized to ConnectionError."""
        import requests as req
        from urllib3.exceptions import ProtocolError

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = req.exceptions.ChunkedEncodingError(
            ProtocolError(
                "Connection broken: ConnectionResetError(104, 'Connection reset by peer')",
                ConnectionResetError(104, "Connection reset by peer"),
            )
        )

        with patch.object(driver._session, "post", return_value=mock_response):
            with pytest.raises(
                req.ConnectionError,
                match=r"Connection broken: ConnectionResetError",
            ):
                driver._hnap_post("Login", {"Login": {}})


# -- Downstream SC-QAM --

