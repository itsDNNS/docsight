"""Tests for builtin modem driver behavior used by collectors."""

"""Tests for the unified Collector Architecture."""

import os
import tempfile
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.collectors.base import Collector, CollectorResult
from app.collectors.modem import ModemCollector
from app.modules.speedtest.collector import SpeedtestCollector
from app.modules.bqm.collector import BQMCollector
from app.drivers.base import ModemDriver
from app.drivers.fritzbox import FritzBoxDriver
from app.drivers.ch7465 import CH7465Driver
from app.drivers.ch7465_play import CH7465PlayDriver


class TestFritzBoxDriver:
    @patch("app.drivers.fritzbox.fb")
    def test_login(self, mock_fb):
        mock_fb.login.return_value = "abc123"
        d = FritzBoxDriver("http://fritz.box", "admin", "pass")
        d.login()
        assert d._sid == "abc123"
        mock_fb.login.assert_called_once_with("http://fritz.box", "admin", "pass")

    @patch("app.drivers.fritzbox.fb")
    def test_get_docsis_data(self, mock_fb):
        mock_fb.login.return_value = "sid1"
        mock_fb.get_docsis_data.return_value = {"channelUs": {"docsis31": []}}
        d = FritzBoxDriver("http://fritz.box", "admin", "pass")
        d.login()
        result = d.get_docsis_data()
        mock_fb.get_docsis_data.assert_called_once_with("http://fritz.box", "sid1")

    @patch("app.drivers.fritzbox.fb")
    def test_us31_power_compensated(self, mock_fb):
        """Fritz!Box DOCSIS 3.1 upstream power is 6 dB too low; driver adds +6."""
        mock_fb.login.return_value = "sid1"
        mock_fb.get_docsis_data.return_value = {
            "channelUs": {
                "docsis30": [{"channelID": 1, "powerLevel": "44.0"}],
                "docsis31": [{"channelID": 2, "powerLevel": "38.0"}],
            },
        }
        d = FritzBoxDriver("http://fritz.box", "admin", "pass")
        d.login()
        result = d.get_docsis_data()
        # 3.0 channel unchanged
        assert result["channelUs"]["docsis30"][0]["powerLevel"] == "44.0"
        # 3.1 channel compensated: 38.0 + 6.0 = 44.0
        assert result["channelUs"]["docsis31"][0]["powerLevel"] == "44.0"

    def test_compensate_no_us31(self):
        """No crash when channelUs or docsis31 is missing."""
        FritzBoxDriver._compensate_us31_power({})
        FritzBoxDriver._compensate_us31_power({"channelUs": {}})
        FritzBoxDriver._compensate_us31_power({"channelUs": {"docsis30": []}})

    @patch("app.drivers.fritzbox.fb")
    def test_get_device_info(self, mock_fb):
        mock_fb.login.return_value = "sid1"
        mock_fb.get_device_info.return_value = {"model": "6690", "sw_version": "7.57"}
        d = FritzBoxDriver("http://fritz.box", "admin", "pass")
        d.login()
        result = d.get_device_info()
        assert result["model"] == "6690"

    @patch("app.drivers.fritzbox.fb")
    def test_get_connection_info(self, mock_fb):
        mock_fb.login.return_value = "sid1"
        mock_fb.get_connection_info.return_value = {"max_downstream_kbps": 1000000}
        d = FritzBoxDriver("http://fritz.box", "admin", "pass")
        d.login()
        result = d.get_connection_info()
        assert result["max_downstream_kbps"] == 1000000


# ── CH7465Driver Tests ──


class TestCH7465Driver:
    @patch("app.drivers.ch7465.requests.Session")
    def test_login_sends_username_when_provided(self, mock_session_cls):
        """Login payload includes Username when user is non-empty."""
        d = CH7465Driver("http://192.168.100.1", "admin", "pass")
        d._session.get.return_value = MagicMock(status_code=200)
        d._is_play = False  # pre-set to skip detection
        d._set_data = MagicMock(return_value="successSID=abc123")

        d.login()

        payload = d._set_data.call_args[0][1]
        assert "Username" in payload
        assert payload["Username"] == "admin"
        assert "Password" in payload

    @patch("app.drivers.ch7465.requests.Session")
    def test_login_omits_username_when_empty(self, mock_session_cls):
        """Login payload omits Username for non-Play firmware with empty user."""
        d = CH7465Driver("http://192.168.100.1", "", "pass")
        d._session.get.return_value = MagicMock(status_code=200)
        d._is_play = False  # pre-set to skip detection
        d._set_data = MagicMock(return_value="successSID=abc123")

        d.login()

        payload = d._set_data.call_args[0][1]
        assert "Username" not in payload
        assert "Password" in payload

    @patch("app.drivers.ch7465.requests.Session")
    def test_detect_play_firmware(self, mock_session_cls):
        """Play firmware detected via ConfigVenderModel containing 'PLAY'."""
        d = CH7465Driver("http://192.168.0.1", "", "pass")
        d._get_data = MagicMock(return_value="<root><ConfigVenderModel>CH7465PLAY</ConfigVenderModel></root>")

        assert d._detect_play_firmware() is True

    @patch("app.drivers.ch7465.requests.Session")
    def test_detect_non_play_firmware(self, mock_session_cls):
        """Standard firmware (e.g. CH7465LG) is not detected as Play."""
        d = CH7465Driver("http://192.168.100.1", "admin", "pass")
        d._get_data = MagicMock(return_value="<root><ConfigVenderModel>CH7465LG</ConfigVenderModel></root>")

        assert d._detect_play_firmware() is False

    @patch("app.drivers.ch7465.requests.Session")
    def test_detect_play_firmware_on_error(self, mock_session_cls):
        """Detection defaults to False on network errors."""
        d = CH7465Driver("http://192.168.0.1", "", "pass")
        d._get_data = MagicMock(side_effect=Exception("timeout"))

        assert d._detect_play_firmware() is False

    @patch("app.drivers.ch7465.requests.Session")
    def test_play_login_sends_plaintext_password(self, mock_session_cls):
        """Play firmware login: Username='NULL', plaintext password (no SHA256)."""
        d = CH7465Driver("http://192.168.0.1", "", "mypassword")
        d._session.get.return_value = MagicMock(status_code=200)
        d._detect_play_firmware = MagicMock(return_value=True)
        d._set_data = MagicMock(return_value="successfulSID=xyz789")

        d.login()

        payload = d._set_data.call_args[0][1]
        assert payload["Username"] == "NULL"
        assert payload["Password"] == "mypassword"  # plaintext, not SHA256

    @patch("app.drivers.ch7465.requests.Session")
    def test_standard_login_sends_sha256_password(self, mock_session_cls):
        """Standard firmware login: SHA256 hashed password."""
        import hashlib
        d = CH7465Driver("http://192.168.100.1", "admin", "mypassword")
        d._session.get.return_value = MagicMock(status_code=200)
        d._is_play = False
        d._set_data = MagicMock(return_value="successSID=abc123")

        d.login()

        payload = d._set_data.call_args[0][1]
        expected_hash = hashlib.sha256(b"mypassword").hexdigest()
        assert payload["Password"] == expected_hash
        assert payload["Username"] == "admin"

    @patch("app.drivers.ch7465.requests.Session")
    def test_play_detection_cached(self, mock_session_cls):
        """Firmware detection only runs once, then cached."""
        d = CH7465Driver("http://192.168.0.1", "", "pass")
        d._session.get.return_value = MagicMock(status_code=200)
        d._detect_play_firmware = MagicMock(return_value=True)
        d._set_data = MagicMock(return_value="successfulSID=xyz789")

        d.login()
        d.login()

        assert d._detect_play_firmware.call_count == 1

    @patch("app.drivers.ch7465.requests.Session")
    def test_token_included_in_get_data(self, mock_session_cls):
        """sessionToken cookie is echoed back as POST param in _get_data."""
        d = CH7465Driver("http://192.168.100.1", "admin", "pass")
        d._session.cookies.get = MagicMock(side_effect=lambda k, default="": "tok123" if k == "sessionToken" else default)
        d._session.post.return_value = MagicMock(status_code=200, text="<root/>")

        from app.drivers.ch7465 import Query
        d._get_data(Query.GLOBAL_SETTINGS)

        post_data = d._session.post.call_args[1]["data"]
        assert post_data["token"] == "tok123"

    @patch("app.drivers.ch7465.requests.Session")
    def test_token_included_in_set_data(self, mock_session_cls):
        """sessionToken cookie is echoed back as POST param in _set_data."""
        d = CH7465Driver("http://192.168.100.1", "admin", "pass")
        d._session.cookies.get = MagicMock(side_effect=lambda k, default="": "tok456" if k == "sessionToken" else default)
        d._session.post.return_value = MagicMock(status_code=200, text="ok")

        from app.drivers.ch7465 import Action
        d._set_data(Action.LOGIN, {"Password": "hash"})

        post_data = d._session.post.call_args[1]["data"]
        assert post_data["token"] == "tok456"


# ── CH7465PlayDriver Tests ──


class TestCH7465PlayDriver:
    @patch("weakref.finalize")
    @patch("app.drivers.ch7465.requests.Session")
    def test_init_registers_only_base_finalizer(self, mock_session_cls, mock_finalize):
        """Play driver keeps the base cleanup finalizer instead of adding a second one."""
        mock_finalizer = MagicMock()
        mock_finalize.return_value = mock_finalizer

        d = CH7465PlayDriver("http://192.168.0.1", "", "mypassword")

        assert d._is_play is True
        assert mock_finalize.call_count == 1
        assert d._finalizer is mock_finalizer
        assert d._finalizer.atexit is True

    @patch("app.drivers.ch7465.requests.Session")
    def test_login_sends_plaintext_password(self, mock_session_cls):
        """Play firmware login sends plaintext password (not SHA256)."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "mypassword")
        d._session.get.return_value = MagicMock(status_code=200)
        d._set_data = MagicMock(return_value="successfulSID=xyz789")

        d.login()

        payload = d._set_data.call_args[0][1]
        assert payload["Password"] == "mypassword"  # plaintext, not SHA256

    @patch("app.drivers.ch7465.requests.Session")
    def test_login_always_sends_username_null(self, mock_session_cls):
        """Play firmware login always sends Username='NULL'."""
        d = CH7465PlayDriver("http://192.168.0.1", "anything", "pass")
        d._session.get.return_value = MagicMock(status_code=200)
        d._set_data = MagicMock(return_value="successSID=abc123")

        d.login()

        payload = d._set_data.call_args[0][1]
        assert payload["Username"] == "NULL"

    @patch("app.drivers.ch7465.requests.Session")
    def test_token_included_in_get_data(self, mock_session_cls):
        """sessionToken cookie is always included in _get_data POST params."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "pass")
        d._session.cookies.get = MagicMock(side_effect=lambda k, default="": "tok123" if k == "sessionToken" else default)
        d._session.post.return_value = MagicMock(status_code=200, text="<root/>")

        from app.drivers.ch7465_play import Query
        d._get_data(Query.GLOBAL_SETTINGS)

        post_data = d._session.post.call_args[1]["data"]
        assert post_data["token"] == "tok123"

    @patch("app.drivers.ch7465.requests.Session")
    def test_token_included_in_set_data(self, mock_session_cls):
        """sessionToken cookie is always included in _set_data POST params."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "pass")
        d._session.cookies.get = MagicMock(side_effect=lambda k, default="": "tok456" if k == "sessionToken" else default)
        d._session.post.return_value = MagicMock(status_code=200, text="ok")

        from app.drivers.ch7465_play import Action
        d._set_data(Action.LOGIN, {"Password": "pw"})

        post_data = d._session.post.call_args[1]["data"]
        assert post_data["token"] == "tok456"

    @patch("app.drivers.ch7465.requests.Session")
    def test_login_failure_raises(self, mock_session_cls):
        """Login raises RuntimeError on auth failure."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "wrongpass")
        d._session.get.return_value = MagicMock(status_code=200)
        d._set_data = MagicMock(return_value="KDGloginincorrect")
        d._get_login_fail_count = MagicMock(return_value=30)

        with pytest.raises(RuntimeError, match="password incorrect"):
            d.login()


# ── ModemCollector Tests ──


class TestLoadDriver:
    def test_load_fritzbox_driver(self):
        from app.drivers import load_driver
        driver = load_driver("fritzbox", "http://fritz.box", "admin", "pass")
        assert isinstance(driver, FritzBoxDriver)

    def test_unknown_driver_raises(self):
        from app.drivers import load_driver
        with pytest.raises(ValueError, match="Unknown modem_type"):
            load_driver("nonexistent", "http://x", "u", "p")

    def test_default_is_fritzbox(self):
        from app.drivers import driver_registry
        assert driver_registry.has_driver("fritzbox")

    @pytest.mark.parametrize("bad_type", [
        "../../etc/passwd",
        "__import__('os')",
        "",
        "fritzbox; import os",
        "../drivers/fritzbox",
    ])
    def test_malicious_modem_type_rejected(self, bad_type):
        from app.drivers import load_driver
        with pytest.raises(ValueError, match="Unknown modem_type"):
            load_driver(bad_type, "http://x", "u", "p")


# ── ModemCollector Error Path Tests (E2) ──

