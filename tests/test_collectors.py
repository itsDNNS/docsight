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


# ── CollectorResult Tests ──


class TestCollectorResult:
    def test_defaults(self):
        r = CollectorResult(source="test")
        assert r.source == "test"
        assert r.data is None
        assert r.success is True
        assert r.error is None
        assert r.timestamp > 0

    def test_failure(self):
        r = CollectorResult(source="test", success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"


# ── Collector ABC Tests ──


class ConcreteCollector(Collector):
    name = "test"

    def __init__(self, poll_interval=60):
        super().__init__(poll_interval)
        self.call_count = 0

    def collect(self):
        self.call_count += 1
        return CollectorResult(source=self.name)


class TestCollectorABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            Collector(60)

    def test_initial_state(self):
        c = ConcreteCollector(120)
        assert c.name == "test"
        assert c.poll_interval_seconds == 120
        assert c._consecutive_failures == 0
        assert c._last_poll == 0.0
        assert c.is_enabled() is True

    def test_should_poll_initially(self):
        c = ConcreteCollector()
        assert c.should_poll() is True

    def test_should_not_poll_right_after_success(self):
        c = ConcreteCollector(60)
        c.record_success()
        assert c.should_poll() is False

    def test_penalty_zero_on_no_failures(self):
        c = ConcreteCollector()
        assert c.penalty_seconds == 0

    def test_penalty_exponential_backoff(self):
        c = ConcreteCollector()
        c._consecutive_failures = 1
        assert c.penalty_seconds == 30
        c._consecutive_failures = 2
        assert c.penalty_seconds == 60
        c._consecutive_failures = 3
        assert c.penalty_seconds == 120
        c._consecutive_failures = 4
        assert c.penalty_seconds == 240

    def test_penalty_capped_at_max(self):
        c = ConcreteCollector()
        c._consecutive_failures = 100
        assert c.penalty_seconds == 3600

    def test_effective_interval_includes_penalty(self):
        c = ConcreteCollector(60)
        assert c.effective_interval == 60
        c._consecutive_failures = 1
        assert c.effective_interval == 90  # 60 + 30

    def test_record_success_resets_failures(self):
        c = ConcreteCollector()
        c._consecutive_failures = 5
        c.record_success()
        assert c._consecutive_failures == 0
        assert c._last_poll > 0

    def test_record_failure_increments(self):
        c = ConcreteCollector()
        c.record_failure()
        assert c._consecutive_failures == 1
        c.record_failure()
        assert c._consecutive_failures == 2
        assert c._last_poll > 0

    def test_should_poll_respects_interval(self):
        c = ConcreteCollector(1)
        c.record_success()
        assert c.should_poll() is False
        time.sleep(1.1)
        assert c.should_poll() is True


# ── ModemDriver ABC Tests ──


class TestModemDriverABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ModemDriver("http://modem", "user", "pass")

    def test_concrete_driver_stores_credentials(self):
        class DummyDriver(ModemDriver):
            def login(self): pass
            def get_docsis_data(self): return {}
            def get_device_info(self): return {}
            def get_connection_info(self): return {}

        d = DummyDriver("http://modem", "admin", "secret")
        assert d._url == "http://modem"
        assert d._user == "admin"
        assert d._password == "secret"


# ── FritzBoxDriver Tests ──


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
    @patch("app.drivers.ch7465_play.requests.Session")
    def test_login_sends_plaintext_password(self, mock_session_cls):
        """Play firmware login sends plaintext password (not SHA256)."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "mypassword")
        d._session.get.return_value = MagicMock(status_code=200)
        d._set_data = MagicMock(return_value="successfulSID=xyz789")

        d.login()

        payload = d._set_data.call_args[0][1]
        assert payload["Password"] == "mypassword"  # plaintext, not SHA256

    @patch("app.drivers.ch7465_play.requests.Session")
    def test_login_always_sends_username_null(self, mock_session_cls):
        """Play firmware login always sends Username='NULL'."""
        d = CH7465PlayDriver("http://192.168.0.1", "anything", "pass")
        d._session.get.return_value = MagicMock(status_code=200)
        d._set_data = MagicMock(return_value="successSID=abc123")

        d.login()

        payload = d._set_data.call_args[0][1]
        assert payload["Username"] == "NULL"

    @patch("app.drivers.ch7465_play.requests.Session")
    def test_token_included_in_get_data(self, mock_session_cls):
        """sessionToken cookie is always included in _get_data POST params."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "pass")
        d._session.cookies.get = MagicMock(side_effect=lambda k, default="": "tok123" if k == "sessionToken" else default)
        d._session.post.return_value = MagicMock(status_code=200, text="<root/>")

        from app.drivers.ch7465_play import Query
        d._get_data(Query.GLOBAL_SETTINGS)

        post_data = d._session.post.call_args[1]["data"]
        assert post_data["token"] == "tok123"

    @patch("app.drivers.ch7465_play.requests.Session")
    def test_token_included_in_set_data(self, mock_session_cls):
        """sessionToken cookie is always included in _set_data POST params."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "pass")
        d._session.cookies.get = MagicMock(side_effect=lambda k, default="": "tok456" if k == "sessionToken" else default)
        d._session.post.return_value = MagicMock(status_code=200, text="ok")

        from app.drivers.ch7465_play import Action
        d._set_data(Action.LOGIN, {"Password": "pw"})

        post_data = d._session.post.call_args[1]["data"]
        assert post_data["token"] == "tok456"

    @patch("app.drivers.ch7465_play.requests.Session")
    def test_login_failure_raises(self, mock_session_cls):
        """Login raises RuntimeError on auth failure."""
        d = CH7465PlayDriver("http://192.168.0.1", "", "wrongpass")
        d._session.get.return_value = MagicMock(status_code=200)
        d._set_data = MagicMock(return_value="KDGloginincorrect")
        d._get_login_fail_count = MagicMock(return_value=30)

        with pytest.raises(RuntimeError, match="password incorrect"):
            d.login()


# ── ModemCollector Tests ──


class TestModemCollector:
    def _make_collector(self, mqtt_pub=None):
        driver = MagicMock()
        driver.get_device_info.return_value = {"model": "6690", "sw_version": "7.57"}
        driver.get_connection_info.return_value = {
            "max_downstream_kbps": 1000000,
            "max_upstream_kbps": 50000,
            "connection_type": "Cable",
        }
        driver.get_docsis_data.return_value = {"some": "data"}

        analyzer_fn = MagicMock(return_value={
            "ds_channels": [],
            "us_channels": [],
            "summary": {},
        })

        event_detector = MagicMock()
        event_detector.check.return_value = []

        storage = MagicMock()
        storage.get_latest_spike_timestamp.return_value = None
        web = MagicMock()

        c = ModemCollector(
            driver=driver,
            analyzer_fn=analyzer_fn,
            event_detector=event_detector,
            storage=storage,
            mqtt_pub=mqtt_pub,
            web=web,
            poll_interval=60,
        )
        return c, driver, analyzer_fn, event_detector, storage, web

    def test_collect_full_pipeline(self):
        c, driver, analyzer_fn, event_detector, storage, web = self._make_collector()
        result = c.collect()

        assert result.success is True
        assert result.source == "modem"
        driver.login.assert_called_once()
        driver.get_device_info.assert_called_once()
        driver.get_connection_info.assert_called_once()
        driver.get_docsis_data.assert_called_once()
        analyzer_fn.assert_called_once()
        storage.save_snapshot.assert_called_once()
        event_detector.check.assert_called_once()
        assert web.update_state.call_count >= 3  # device_info, connection_info, analysis

    def test_collect_caches_device_info(self):
        c, driver, *_ = self._make_collector()
        c.collect()
        c.collect()
        # device_info and connection_info only fetched once
        assert driver.get_device_info.call_count == 1
        assert driver.get_connection_info.call_count == 1

    def test_collect_with_events(self):
        c, _, _, event_detector, storage, _ = self._make_collector()
        event_detector.check.return_value = [{"type": "power_change"}]
        c.collect()
        storage.save_events_with_ids.assert_called_once()

    def test_collect_with_mqtt(self):
        mqtt = MagicMock()
        c, *_ = self._make_collector(mqtt_pub=mqtt)
        c.collect()
        mqtt.publish_discovery.assert_called_once()
        mqtt.publish_channel_discovery.assert_called_once()
        mqtt.publish_data.assert_called_once()

    def test_collect_mqtt_discovery_only_once(self):
        mqtt = MagicMock()
        c, *_ = self._make_collector(mqtt_pub=mqtt)
        c.collect()
        c.collect()
        assert mqtt.publish_discovery.call_count == 1
        assert mqtt.publish_data.call_count == 2

    def test_collect_no_mqtt(self):
        c, *_ = self._make_collector(mqtt_pub=None)
        result = c.collect()
        assert result.success is True

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "modem"


class TestModemCollectorSpikeSuppression:
    """Verify spike suppression is called in the collector pipeline."""

    def test_modem_collector_calls_spike_suppression(self):
        """ModemCollector calls apply_spike_suppression after analyze."""
        mock_driver = MagicMock(spec=ModemDriver)
        mock_driver.get_docsis_data.return_value = {"channelDs": {"docsis30": []}, "channelUs": {"docsis30": []}}
        mock_driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        mock_driver.get_connection_info.return_value = None

        mock_storage = MagicMock()
        mock_storage.get_latest_spike_timestamp.return_value = None
        mock_web = MagicMock()
        mock_web._state = {}

        fake_analysis = {
            "summary": {"health": "good", "health_issues": [], "ds_total": 0, "us_total": 0},
            "ds_channels": [],
            "us_channels": [],
        }
        mock_analyzer = MagicMock(return_value=fake_analysis)

        collector = ModemCollector(
            driver=mock_driver,
            analyzer_fn=mock_analyzer,
            event_detector=MagicMock(),
            storage=mock_storage,
            mqtt_pub=None,
            web=mock_web,
            poll_interval=60,
        )

        with patch("app.collectors.modem.apply_spike_suppression") as mock_suppress:
            collector.collect()
            mock_suppress.assert_called_once_with(fake_analysis, None)


# ── SpeedtestCollector Tests ──


class TestSpeedtestCollector:
    def _make_collector(self, configured=True):
        config_mgr = MagicMock()
        config_mgr.is_speedtest_configured.return_value = configured
        config_mgr.get.side_effect = lambda k, *a: {
            "speedtest_tracker_url": "http://speed:8999",
            "speedtest_tracker_token": "tok",
        }.get(k, a[0] if a else None)

        storage = MagicMock()
        # Provide a real temp db_path so SpeedtestStorage can init
        storage.db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        web = MagicMock()

        c = SpeedtestCollector(config_mgr=config_mgr, storage=storage, web=web, poll_interval=300)
        return c, config_mgr, storage, web

    def test_is_enabled_true(self):
        c, *_ = self._make_collector(configured=True)
        assert c.is_enabled() is True

    def test_is_enabled_false(self):
        c, *_ = self._make_collector(configured=False)
        assert c.is_enabled() is False

    @patch("app.modules.speedtest.collector.SpeedtestClient")
    def test_collect_initializes_client(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_latest_with_error.return_value = ([{"id": 1, "download_mbps": 100}], None)
        mock_client.get_results.return_value = []
        mock_cls.return_value = mock_client

        c, *_ = self._make_collector()
        c.collect()
        mock_cls.assert_called_once_with("http://speed:8999", "tok")

    @patch("app.modules.speedtest.collector.SpeedtestClient")
    def test_collect_updates_web_state(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_latest_with_error.return_value = ([{"id": 1}], None)
        mock_client.get_results.return_value = []
        mock_cls.return_value = mock_client

        c, _, _, web = self._make_collector()
        c.collect()
        web.update_state.assert_called_once()

    @patch("app.modules.speedtest.collector.SpeedtestClient")
    def test_collect_fetch_failure_returns_error(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_latest_with_error.return_value = ([], "ConnectionError: refused")
        mock_cls.return_value = mock_client

        c, _, _, web = self._make_collector()
        result = c.collect()
        assert result.success is False
        assert "ConnectionError" in result.error
        web.update_state.assert_not_called()

    @patch("app.modules.speedtest.collector.SpeedtestClient")
    def test_collect_delta_cache(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_latest_with_error.return_value = ([], None)
        mock_client.get_results.return_value = [
            {"id": 1, "timestamp": "2025-01-01T00:00:00Z", "download_mbps": 100,
             "upload_mbps": 10, "download_human": "", "upload_human": "",
             "ping_ms": 5, "jitter_ms": 1, "packet_loss_pct": 0},
            {"id": 2, "timestamp": "2025-01-01T01:00:00Z", "download_mbps": 200,
             "upload_mbps": 20, "download_human": "", "upload_human": "",
             "ping_ms": 5, "jitter_ms": 1, "packet_loss_pct": 0},
        ]
        mock_cls.return_value = mock_client

        c, _, storage, _ = self._make_collector()
        c.collect()
        # Verify results were saved to the module's internal storage
        assert c._storage.get_speedtest_count() == 2

    @patch("app.modules.speedtest.collector.SpeedtestClient")
    def test_collect_delta_cache_failure_does_not_crash(self, mock_cls):
        """Delta cache failure should not prevent a successful collect result."""
        mock_client = MagicMock()
        mock_client.get_latest_with_error.return_value = ([{"id": 1}], None)
        mock_client.get_results.side_effect = Exception("API timeout")
        mock_cls.return_value = mock_client

        c, _, storage, web = self._make_collector()
        result = c.collect()
        assert result.success is True
        web.update_state.assert_called_once()

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "speedtest"


# ── BackupCollector Tests ──


class TestBackupCollector:
    def _make_collector(self, configured=True, interval_hours=24, backups=None):
        config_mgr = MagicMock()
        config_mgr.is_backup_configured.return_value = configured
        config_mgr.data_dir = "/data"
        config_mgr.get.side_effect = lambda k, *a: {
            "backup_path": "/backup",
            "backup_interval_hours": interval_hours,
            "backup_retention": 5,
        }.get(k, a[0] if a else None)

        from app.modules.backup.collector import BackupCollector
        with patch("app.modules.backup.backup.list_backups", return_value=backups or []):
            c = BackupCollector(config_mgr=config_mgr)
        return c, config_mgr

    def test_name(self):
        c, _ = self._make_collector()
        assert c.name == "backup"

    def test_is_enabled(self):
        c, _ = self._make_collector(configured=True)
        assert c.is_enabled() is True
        c2, _ = self._make_collector(configured=False)
        assert c2.is_enabled() is False

    def test_interval_from_config(self):
        c, _ = self._make_collector(interval_hours=168)
        assert c._poll_interval_seconds == 168 * 3600

    def test_seed_last_poll_from_disk(self):
        """_last_poll is seeded from newest backup file on init."""
        from datetime import datetime, timedelta
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
        backups = [{"filename": "docsight_backup_test.tar.gz", "size": 100, "modified": two_hours_ago}]
        c, _ = self._make_collector(backups=backups)
        # _last_poll should be close to 2h ago, not 0
        assert c._last_poll > 0
        age = time.time() - c._last_poll
        assert 7000 < age < 7400  # ~2h in seconds

    def test_seed_no_backups_leaves_last_poll_zero(self):
        """No backups on disk → _last_poll stays 0, first backup runs immediately."""
        c, _ = self._make_collector(backups=[])
        assert c._last_poll == 0.0

    def test_should_poll_false_after_seed(self):
        """Container restart with recent backup → should_poll() returns False."""
        from datetime import datetime, timedelta
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        backups = [{"filename": "docsight_backup_test.tar.gz", "size": 100, "modified": one_hour_ago}]
        c, _ = self._make_collector(interval_hours=24, backups=backups)
        assert c.should_poll() is False

    def test_should_poll_true_when_backup_expired(self):
        """Backup older than interval → should_poll() returns True."""
        from datetime import datetime, timedelta
        two_days_ago = (datetime.now() - timedelta(days=2)).isoformat()
        backups = [{"filename": "docsight_backup_old.tar.gz", "size": 100, "modified": two_days_ago}]
        c, _ = self._make_collector(interval_hours=24, backups=backups)
        assert c.should_poll() is True

    def test_seed_includes_manual_backups(self):
        """Seed uses newest backup regardless of source (scheduled or manual).

        After a restart, _last_poll anchors to the newest file on disk.
        This means a manual backup can shift the automatic schedule, which
        is by design: the guarantee is "at least one backup every <interval>".
        """
        from datetime import datetime, timedelta
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        backups = [{"filename": "docsight_backup_2026-03-15_120000.tar.gz", "size": 100, "modified": one_hour_ago}]
        c, _ = self._make_collector(interval_hours=24, backups=backups)
        # _last_poll is seeded from the file, so should_poll() waits
        assert c.should_poll() is False

    @patch("app.modules.backup.backup.create_backup_to_file")
    @patch("app.modules.backup.backup.cleanup_old_backups")
    def test_collect_creates_backup(self, mock_cleanup, mock_create):
        mock_create.return_value = "docsight_backup_2026-03-15.tar.gz"
        c, _ = self._make_collector()
        result = c.collect()
        assert result.success is True
        mock_create.assert_called_once()
        mock_cleanup.assert_called_once()


# ── BQMCollector Tests ──


class TestBQMCollector:
    def _make_collector(self, configured=True, collect_time="02:00", bqm_url="https://www.thinkbroadband.com/broadband/monitoring/quality/share/bd77751689f2f7b8d47d99899335aef060c9e768-2-y.csv"):
        config_mgr = MagicMock()
        config_mgr.is_bqm_configured.return_value = configured
        config_mgr.get.side_effect = lambda k, *a: {
            "bqm_collect_time": collect_time,
            "bqm_url": bqm_url,
        }.get(k, a[0] if a else None)

        storage = MagicMock()
        # Provide a real temp db_path so BqmStorage can init
        storage.db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        c = BQMCollector(config_mgr=config_mgr, storage=storage, poll_interval=86400)
        return c, config_mgr, storage

    def test_is_enabled_true(self):
        c, *_ = self._make_collector(configured=True)
        assert c.is_enabled() is True

    def test_is_enabled_false(self):
        c, *_ = self._make_collector(configured=False)
        assert c.is_enabled() is False

    @patch("app.modules.bqm.collector.parse_bqm_csv")
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_success(self, mock_fetch, mock_parse):
        mock_fetch.return_value = '"Timestamp",...\n'
        mock_parse.return_value = [{
            "timestamp": "2026-03-15T19:00:00+00:00",
            "date": "2026-03-15",
            "sent_polls": 100,
            "lost_polls": 0,
            "latency_min_ms": 30.0,
            "latency_avg_ms": 35.0,
            "latency_max_ms": 40.0,
            "score": 1,
        }]
        c, _, storage = self._make_collector()
        result = c.collect()
        assert result.success is True
        assert c._last_date is not None
        assert c._storage.get_csv_dates() == ["2026-03-15"]

    @patch("app.modules.bqm.collector.parse_bqm_csv", return_value=[{
        "timestamp": "2026-03-15T19:00:00+00:00",
        "date": "2026-03-15",
        "sent_polls": 100,
        "lost_polls": 0,
        "latency_min_ms": 30.0,
        "latency_avg_ms": 35.0,
        "latency_max_ms": 40.0,
        "score": 1,
    }])
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_stores_yesterday_when_before_noon(self, mock_fetch, _mock_parse):
        """Collect always fetches yesterday CSV via share URL."""
        mock_fetch.return_value = '"Timestamp",...\n'
        c, _, storage = self._make_collector(collect_time="02:00")
        c.collect()
        mock_fetch.assert_called_once_with("bd77751689f2f7b8d47d99899335aef060c9e768-2", variant="y")

    @patch("app.modules.bqm.collector.parse_bqm_csv", return_value=[{
        "timestamp": "2026-03-15T19:00:00+00:00",
        "date": "2026-03-15",
        "sent_polls": 100,
        "lost_polls": 0,
        "latency_min_ms": 30.0,
        "latency_avg_ms": 35.0,
        "latency_max_ms": 40.0,
        "score": 1,
    }])
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_stores_today_when_after_noon(self, mock_fetch, _mock_parse):
        """Collect time doesn't affect share URL — always fetches yesterday variant."""
        mock_fetch.return_value = '"Timestamp",...\n'
        c, _, storage = self._make_collector(collect_time="14:00")
        c.collect()
        mock_fetch.assert_called_once_with("bd77751689f2f7b8d47d99899335aef060c9e768-2", variant="y")

    @patch("app.modules.bqm.collector.parse_bqm_csv", return_value=[{
        "timestamp": "2026-03-15T19:00:00+00:00",
        "date": "2026-03-15",
        "sent_polls": 100,
        "lost_polls": 0,
        "latency_min_ms": 30.0,
        "latency_avg_ms": 35.0,
        "latency_max_ms": 40.0,
        "score": 1,
    }])
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_skips_same_day(self, mock_fetch, _mock_parse):
        mock_fetch.return_value = '"Timestamp",...\n'
        c, _, storage = self._make_collector()
        c.collect()
        result = c.collect()
        assert result.data == {"skipped": True}
        assert mock_fetch.call_count == 1

    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_fetch_failure(self, mock_fetch):
        mock_fetch.return_value = ""
        c, _, storage = self._make_collector()
        result = c.collect()
        assert result.success is False
        assert "download" in result.error
        assert c._storage.get_csv_dates() == []

    def test_collect_skips_png_url(self):
        c, _, storage = self._make_collector(bqm_url="https://www.thinkbroadband.com/share/abc.png")
        result = c.collect()
        assert result.data.get("reason") == "no_csv"

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "bqm"

    @patch("app.modules.bqm.collector.random")
    @patch("app.modules.bqm.collector.time")
    def test_should_poll_before_target(self, mock_time, mock_random):
        """Should not poll if current time is before target + spread offset."""
        mock_random.randint.return_value = 30  # 30 min offset -> target 02:30
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "02:25",
        }[fmt]
        c, *_ = self._make_collector(collect_time="02:00")
        assert c.should_poll() is False

    @patch("app.modules.bqm.collector.random")
    @patch("app.modules.bqm.collector.time")
    def test_should_poll_after_target(self, mock_time, mock_random):
        """Should poll if current time is at/after target + spread offset."""
        mock_random.randint.return_value = 30  # 30 min offset -> target 02:30
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "02:30",
        }[fmt]
        c, *_ = self._make_collector(collect_time="02:00")
        assert c.should_poll() is True

    @patch("app.modules.bqm.collector.random")
    @patch("app.modules.bqm.collector.time")
    def test_should_poll_not_twice_same_day(self, mock_time, mock_random):
        """Should not poll again after collecting today."""
        mock_random.randint.return_value = 0
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "03:00",
        }[fmt]
        c, *_ = self._make_collector(collect_time="02:00")
        c._last_date = "2026-02-19"
        assert c.should_poll() is False

    @patch("app.modules.bqm.collector.random")
    def test_spread_offset_within_range(self, mock_random):
        """Spread offset should be between 0 and 120 minutes."""
        mock_random.randint.return_value = 42
        c, *_ = self._make_collector()
        assert c._spread_offset == 42
        mock_random.randint.assert_called_with(0, 120)

    @patch("app.modules.bqm.collector.random")
    @patch("app.modules.bqm.collector.time")
    def test_spread_clamped_to_0030(self, mock_time, mock_random):
        """Spread must never schedule collection before 00:30."""
        mock_random.randint.return_value = 0  # 00:20 + 0 = 00:20 -> clamp 00:30
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "00:25",
        }[fmt]
        c, *_ = self._make_collector(collect_time="00:20")
        assert c.should_poll() is False  # 00:25 < 00:30

        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "00:30",
        }[fmt]
        assert c.should_poll() is True  # 00:30 >= 00:30

    @patch("app.modules.bqm.collector.random")
    @patch("app.modules.bqm.collector.time")
    def test_spread_offset_wraps_past_midnight(self, mock_time, mock_random):
        """Spread offset should wrap correctly past midnight (22:00 + 150min = 00:30)."""
        mock_random.randint.return_value = 120  # 22:00 + 120 min = 00:00 -> clamp 00:30
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "00:30",
        }[fmt]
        c, *_ = self._make_collector(collect_time="22:00")
        assert c.should_poll() is True


# ── build_collectors Tests ──


class TestDiscoverCollectors:
    def _make_storage(self, tmp_path=None):
        import tempfile, os
        s = MagicMock()
        s.db_path = os.path.join(tmp_path or tempfile.mkdtemp(), "test.db")
        return s

    def _make_config_mgr(self, poll_interval=60, bnetz_watch=False):
        mgr = MagicMock()
        mgr.is_demo_mode.return_value = False
        mgr.is_configured.return_value = True
        mgr.is_speedtest_configured.return_value = True
        mgr.is_bqm_configured.return_value = True
        mgr.is_bnetz_watch_configured.return_value = bnetz_watch
        mgr.is_weather_configured.return_value = False
        mgr.is_segment_utilization_enabled.return_value = True
        mgr.get_all.return_value = {
            "modem_type": "fritzbox",
            "modem_url": "http://fritz.box",
            "modem_user": "admin",
            "modem_password": "pass",
            "poll_interval": poll_interval,
        }
        mgr.get.side_effect = lambda key, default=None: mgr.get_all.return_value.get(key, default)
        return mgr

    def _make_web_with_modules(self, module_specs):
        """Create a web mock with module_loader returning given module specs.

        module_specs: list of (collector_class, name) tuples.
        """
        web = MagicMock()
        modules = []
        for cls, mod_id in module_specs:
            mod = MagicMock()
            mod.collector_class = cls
            mod.id = mod_id
            modules.append(mod)
        module_loader = MagicMock()
        module_loader.get_enabled_modules.return_value = modules
        web.get_module_loader.return_value = module_loader
        return web

    @patch("app.drivers.driver_registry.load_driver")
    def test_discover_returns_modem_plus_modules(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        analyzer = MagicMock()

        # Create mock module collectors for speedtest and bqm
        mock_speedtest_cls = MagicMock()
        mock_speedtest_instance = MagicMock()
        mock_speedtest_instance.name = "speedtest"
        mock_speedtest_cls.return_value = mock_speedtest_instance

        mock_bqm_cls = MagicMock()
        mock_bqm_instance = MagicMock()
        mock_bqm_instance.name = "bqm"
        mock_bqm_cls.return_value = mock_bqm_instance

        web = self._make_web_with_modules([
            (mock_speedtest_cls, "docsight.speedtest"),
            (mock_bqm_cls, "docsight.bqm"),
        ])

        collectors = discover_collectors(
            config_mgr, self._make_storage(), MagicMock(), None, web, analyzer
        )
        assert len(collectors) == 4  # modem + segment_utilization + speedtest + bqm
        names = [c.name for c in collectors]
        assert "modem" in names
        assert "segment_utilization" in names
        assert "speedtest" in names
        assert "bqm" in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_discover_includes_bnetz_watcher_module(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr(bnetz_watch=True)
        analyzer = MagicMock()

        mock_bnetz_cls = MagicMock()
        mock_bnetz_instance = MagicMock()
        mock_bnetz_instance.name = "bnetz_watcher"
        mock_bnetz_cls.return_value = mock_bnetz_instance

        web = self._make_web_with_modules([
            (mock_bnetz_cls, "docsight.bnetz"),
        ])

        collectors = discover_collectors(
            config_mgr, self._make_storage(), MagicMock(), None, web, analyzer
        )
        assert len(collectors) == 3  # modem + segment_utilization + bnetz_watcher
        names = [c.name for c in collectors]
        assert "bnetz_watcher" in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_discover_no_modules_returns_modem_only(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        analyzer = MagicMock()

        # Web without module_loader attribute
        web = MagicMock(spec=[])

        collectors = discover_collectors(
            config_mgr, self._make_storage(), MagicMock(), None, web, analyzer
        )
        assert len(collectors) == 2  # modem + segment_utilization
        names = [c.name for c in collectors]
        assert "modem" in names
        assert "segment_utilization" in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_discover_skips_segment_when_disabled(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        config_mgr.is_segment_utilization_enabled.return_value = False
        analyzer = MagicMock()

        web = MagicMock(spec=[])

        collectors = discover_collectors(
            config_mgr, self._make_storage(), MagicMock(), None, web, analyzer
        )
        names = [c.name for c in collectors]
        assert "modem" in names
        assert "segment_utilization" not in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_modem_collector_gets_poll_interval(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr(poll_interval=120)
        analyzer = MagicMock()

        # Web without module_loader
        web = MagicMock(spec=[])

        collectors = discover_collectors(
            config_mgr, self._make_storage(), MagicMock(), None, web, analyzer
        )
        modem = [c for c in collectors if c.name == "modem"][0]
        assert modem.poll_interval_seconds == 120

    @patch("app.drivers.driver_registry.load_driver")
    def test_driver_loaded_by_modem_type(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        analyzer = MagicMock()

        # Web without module_loader
        web = MagicMock(spec=[])

        discover_collectors(
            config_mgr, self._make_storage(), MagicMock(), None, web, analyzer
        )
        mock_load.assert_called_once_with("fritzbox", "http://fritz.box", "admin", "pass")


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


class TestModemCollectorErrors:
    def _make_collector(self):
        driver = MagicMock()
        analyzer_fn = MagicMock()
        event_detector = MagicMock()
        storage = MagicMock()
        storage.get_latest_spike_timestamp.return_value = None
        web = MagicMock()
        c = ModemCollector(
            driver=driver, analyzer_fn=analyzer_fn, event_detector=event_detector,
            storage=storage, mqtt_pub=None, web=web, poll_interval=60,
        )
        return c, driver, analyzer_fn, storage, web

    def test_login_failure_propagates(self):
        c, driver, *_ = self._make_collector()
        driver.login.side_effect = RuntimeError("Auth failed")
        with pytest.raises(RuntimeError, match="Auth failed"):
            c.collect()

    def test_get_docsis_data_failure_propagates(self):
        c, driver, *_ = self._make_collector()
        driver.get_device_info.return_value = {"model": "X", "sw_version": "1"}
        driver.get_connection_info.return_value = {}
        driver.get_docsis_data.side_effect = RuntimeError("Timeout")
        with pytest.raises(RuntimeError, match="Timeout"):
            c.collect()

    def test_login_failure_does_not_update_web_state(self):
        c, driver, _, _, web = self._make_collector()
        driver.login.side_effect = RuntimeError("Auth failed")
        with pytest.raises(RuntimeError):
            c.collect()
        web.update_state.assert_not_called()

    def test_device_info_failure_propagates(self):
        c, driver, *_ = self._make_collector()
        driver.get_device_info.side_effect = RuntimeError("HTTP 500")
        with pytest.raises(RuntimeError, match="HTTP 500"):
            c.collect()

    def test_analyzer_failure_propagates(self):
        c, driver, analyzer_fn, _, _ = self._make_collector()
        driver.get_device_info.return_value = {"model": "X", "sw_version": "1"}
        driver.get_connection_info.return_value = {}
        driver.get_docsis_data.return_value = {"bad": "data"}
        analyzer_fn.side_effect = KeyError("ds_channels")
        with pytest.raises(KeyError):
            c.collect()

    def test_storage_failure_propagates(self):
        c, driver, analyzer_fn, storage, _ = self._make_collector()
        driver.get_device_info.return_value = {"model": "X", "sw_version": "1"}
        driver.get_connection_info.return_value = {}
        driver.get_docsis_data.return_value = {}
        analyzer_fn.return_value = {"ds_channels": [], "us_channels": [], "summary": {}}
        storage.save_snapshot.side_effect = RuntimeError("Disk full")
        with pytest.raises(RuntimeError, match="Disk full"):
            c.collect()


# ── Orchestrator Integration Tests (E1) ──


class TestPollingLoopOrchestrator:
    def _make_storage(self):
        import tempfile, os
        s = MagicMock()
        s.db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        return s

    def _make_config_mgr(self):
        mgr = MagicMock()
        mgr.get_all.return_value = {
            "modem_type": "fritzbox",
            "modem_url": "http://fritz.box",
            "modem_user": "admin",
            "modem_password": "pass",
            "poll_interval": 60,
            "mqtt_host": "",
            "mqtt_port": 1883,
            "mqtt_user": "",
            "mqtt_password": "",
            "mqtt_topic_prefix": "docsight",
            "mqtt_discovery_prefix": "homeassistant",
            "mqtt_tls_insecure": "",
            "web_port": 8765,
        }
        mgr.is_mqtt_configured.return_value = False
        mgr.is_speedtest_configured.return_value = False
        mgr.is_bqm_configured.return_value = False
        mgr.is_demo_mode.return_value = False
        mgr.is_configured.return_value = True
        mgr.is_bnetz_watch_configured.return_value = False
        mgr.is_backup_configured.return_value = False
        mgr.get.return_value = ""
        return mgr

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.main.web")
    def test_orchestrator_calls_enabled_collectors(self, mock_web, mock_load):
        """Orchestrator should call collect() for enabled collectors."""
        import threading
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        mock_driver.get_connection_info.return_value = {}
        mock_driver.get_docsis_data.return_value = {}
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        storage = MagicMock()
        import tempfile, os
        storage.db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        stop = threading.Event()

        original_wait = stop.wait
        call_count = [0]

        def stop_after_one_tick(timeout=None):
            call_count[0] += 1
            if call_count[0] >= 2:
                stop.set()
                return True
            return original_wait(0)

        stop.wait = stop_after_one_tick

        polling_loop(config_mgr, storage, stop)

        mock_driver.login.assert_called()
        mock_driver.get_docsis_data.assert_called()

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.main.web")
    def test_orchestrator_skips_disabled_collectors(self, mock_web, mock_load):
        """Speedtest/BQM collectors should be skipped when not configured."""
        import threading
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        mock_driver.get_connection_info.return_value = {}
        mock_driver.get_docsis_data.return_value = {}
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        storage = self._make_storage()
        stop = threading.Event()

        call_count = [0]
        original_wait = stop.wait

        def stop_after_one_tick(timeout=None):
            call_count[0] += 1
            if call_count[0] >= 2:
                stop.set()
                return True
            return original_wait(0)

        stop.wait = stop_after_one_tick

        polling_loop(config_mgr, storage, stop)

        # Core storage should not have speedtest/bqm methods called
        # (those are now handled by module-internal storage)
        storage.get_latest_speedtest_id.assert_not_called()
        storage.save_bqm_graph.assert_not_called()

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.main.web")
    def test_orchestrator_handles_collector_exception(self, mock_web, mock_load):
        """Orchestrator should catch exceptions and continue running."""
        import threading
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.login.side_effect = RuntimeError("Modem offline")
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        storage = self._make_storage()
        stop = threading.Event()

        call_count = [0]
        original_wait = stop.wait

        def stop_after_one_tick(timeout=None):
            call_count[0] += 1
            if call_count[0] >= 2:
                stop.set()
                return True
            return original_wait(0)

        stop.wait = stop_after_one_tick

        polling_loop(config_mgr, storage, stop)

        mock_web.update_state.assert_any_call(error=mock_driver.login.side_effect)

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.main.web")
    def test_orchestrator_stops_on_event(self, mock_web, mock_load):
        """Orchestrator should exit when stop_event is set."""
        import threading
        from app.main import polling_loop

        mock_load.return_value = MagicMock()

        config_mgr = self._make_config_mgr()
        storage = self._make_storage()
        stop = threading.Event()
        stop.set()  # Pre-set: should exit immediately

        polling_loop(config_mgr, storage, stop)
        # If we get here without hanging, the test passes

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.main.web")
    def test_driver_hot_swap_on_modem_type_change(self, mock_web, mock_load):
        """Polling loop should hot-swap the modem driver when modem_type changes."""
        import threading
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        mock_driver.get_connection_info.return_value = {}
        mock_driver.get_docsis_data.return_value = {}
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        storage = self._make_storage()
        stop = threading.Event()

        call_count = [0]
        original_wait = stop.wait

        def change_modem_after_first_tick(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # After first tick, change modem_type in config
                config_mgr.get_all.return_value["modem_type"] = "tc4400"
                config_mgr.get.side_effect = lambda k, d=None: {
                    "modem_type": "tc4400",
                    "modem_url": "http://fritz.box",
                    "modem_user": "admin",
                    "modem_password": "pass",
                    "poll_interval": 900,
                }.get(k, d)
                return original_wait(0)
            elif call_count[0] >= 3:
                stop.set()
                return True
            return original_wait(0)

        stop.wait = change_modem_after_first_tick

        polling_loop(config_mgr, storage, stop)

        # load_driver should have been called at least twice:
        # once for initial setup, once for hot-swap
        assert mock_load.call_count >= 2
        # Second call should use the new modem type
        second_call = mock_load.call_args_list[1]
        assert second_call[0][0] == "tc4400"
        # Web state should have been reset for the swap
        mock_web.reset_modem_state.assert_called()
        mock_web.init_collector.assert_called()

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.main.web")
    def test_driver_hot_swap_on_url_change(self, mock_web, mock_load):
        """Hot-swap should trigger when modem URL changes, not just type."""
        import threading
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        mock_driver.get_connection_info.return_value = {}
        mock_driver.get_docsis_data.return_value = {}
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        storage = self._make_storage()
        stop = threading.Event()

        call_count = [0]
        original_wait = stop.wait

        def change_url_after_first_tick(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # Change URL but keep same modem_type
                config_mgr.get.side_effect = lambda k, d=None: {
                    "modem_type": "fritzbox",
                    "modem_url": "http://192.168.100.1",
                    "modem_user": "admin",
                    "modem_password": "pass",
                    "poll_interval": 900,
                }.get(k, d)
                return original_wait(0)
            elif call_count[0] >= 3:
                stop.set()
                return True
            return original_wait(0)

        stop.wait = change_url_after_first_tick

        polling_loop(config_mgr, storage, stop)

        # load_driver called twice: initial + hot-swap for URL change
        assert mock_load.call_count >= 2
        second_call = mock_load.call_args_list[1]
        assert second_call[0][1] == "http://192.168.100.1"

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.main.web")
    def test_no_hot_swap_when_config_unchanged(self, mock_web, mock_load):
        """No hot-swap should occur when modem config hasn't changed."""
        import threading
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        mock_driver.get_connection_info.return_value = {}
        mock_driver.get_docsis_data.return_value = {}
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        storage = self._make_storage()
        stop = threading.Event()

        call_count = [0]
        original_wait = stop.wait

        def stop_after_ticks(timeout=None):
            call_count[0] += 1
            if call_count[0] >= 3:
                stop.set()
                return True
            return original_wait(0)

        stop.wait = stop_after_ticks

        polling_loop(config_mgr, storage, stop)

        # load_driver should only be called once (initial setup)
        assert mock_load.call_count == 1
        # reset_modem_state should NOT have been called (no swap)
        mock_web.reset_modem_state.assert_not_called()
