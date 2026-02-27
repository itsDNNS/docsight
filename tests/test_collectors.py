"""Tests for the unified Collector Architecture."""

import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.collectors.base import Collector, CollectorResult
from app.collectors.modem import ModemCollector
from app.collectors.speedtest import SpeedtestCollector
from app.collectors.bqm import BQMCollector
from app.drivers.base import ModemDriver
from app.drivers.fritzbox import FritzBoxDriver


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
        storage.save_events.assert_called_once()

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
        storage.get_latest_speedtest_id.return_value = 0
        storage.get_speedtest_count.return_value = 0
        web = MagicMock()

        c = SpeedtestCollector(config_mgr=config_mgr, storage=storage, web=web, poll_interval=300)
        return c, config_mgr, storage, web

    def test_is_enabled_true(self):
        c, *_ = self._make_collector(configured=True)
        assert c.is_enabled() is True

    def test_is_enabled_false(self):
        c, *_ = self._make_collector(configured=False)
        assert c.is_enabled() is False

    @patch("app.collectors.speedtest.SpeedtestClient")
    def test_collect_initializes_client(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_latest.return_value = [{"id": 1, "download_mbps": 100}]
        mock_client.get_results.return_value = []
        mock_cls.return_value = mock_client

        c, *_ = self._make_collector()
        c.collect()
        mock_cls.assert_called_once_with("http://speed:8999", "tok")

    @patch("app.collectors.speedtest.SpeedtestClient")
    def test_collect_updates_web_state(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_latest.return_value = [{"id": 1}]
        mock_client.get_results.return_value = []
        mock_cls.return_value = mock_client

        c, _, _, web = self._make_collector()
        c.collect()
        web.update_state.assert_called_once()

    @patch("app.collectors.speedtest.SpeedtestClient")
    def test_collect_delta_cache(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_latest.return_value = []
        mock_client.get_results.return_value = [{"id": 1}, {"id": 2}]
        mock_cls.return_value = mock_client

        c, _, storage, _ = self._make_collector()
        c.collect()
        storage.save_speedtest_results.assert_called_once()

    @patch("app.collectors.speedtest.SpeedtestClient")
    def test_collect_delta_cache_failure_does_not_crash(self, mock_cls):
        """Delta cache failure should not prevent a successful collect result."""
        mock_client = MagicMock()
        mock_client.get_latest.return_value = [{"id": 1}]
        mock_client.get_newer_than.side_effect = Exception("API timeout")
        mock_cls.return_value = mock_client

        c, _, storage, web = self._make_collector()
        storage.get_speedtest_count.return_value = 100  # triggers get_newer_than path
        result = c.collect()
        assert result.success is True
        web.update_state.assert_called_once()

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "speedtest"


# ── BQMCollector Tests ──


class TestBQMCollector:
    def _make_collector(self, configured=True, collect_time="02:00"):
        config_mgr = MagicMock()
        config_mgr.is_bqm_configured.return_value = configured
        config_mgr.get.side_effect = lambda k, *a: {
            "bqm_url": "https://example.com/graph.png",
            "bqm_collect_time": collect_time,
        }.get(k, a[0] if a else None)

        storage = MagicMock()
        c = BQMCollector(config_mgr=config_mgr, storage=storage, poll_interval=86400)
        return c, config_mgr, storage

    def test_is_enabled_true(self):
        c, *_ = self._make_collector(configured=True)
        assert c.is_enabled() is True

    def test_is_enabled_false(self):
        c, *_ = self._make_collector(configured=False)
        assert c.is_enabled() is False

    @patch("app.collectors.bqm.thinkbroadband")
    def test_collect_success(self, mock_tb):
        mock_tb.fetch_graph.return_value = b"\x89PNG" + b"\x00" * 200
        c, _, storage = self._make_collector()
        result = c.collect()
        assert result.success is True
        storage.save_bqm_graph.assert_called_once()
        # Verify graph_date kwarg is passed
        _, kwargs = storage.save_bqm_graph.call_args
        assert "graph_date" in kwargs
        assert c._last_date is not None

    @patch("app.collectors.bqm.thinkbroadband")
    def test_collect_stores_yesterday_when_before_noon(self, mock_tb):
        """Collect time before 12:00 should store as yesterday."""
        from datetime import date, timedelta
        mock_tb.fetch_graph.return_value = b"\x89PNG" + b"\x00" * 200
        c, _, storage = self._make_collector(collect_time="02:00")
        c.collect()
        _, kwargs = storage.save_bqm_graph.call_args
        expected = (date.today() - timedelta(days=1)).isoformat()
        assert kwargs["graph_date"] == expected

    @patch("app.collectors.bqm.thinkbroadband")
    def test_collect_stores_today_when_after_noon(self, mock_tb):
        """Collect time at/after 12:00 should store as today."""
        from datetime import date
        mock_tb.fetch_graph.return_value = b"\x89PNG" + b"\x00" * 200
        c, _, storage = self._make_collector(collect_time="14:00")
        c.collect()
        _, kwargs = storage.save_bqm_graph.call_args
        assert kwargs["graph_date"] == date.today().isoformat()

    @patch("app.collectors.bqm.thinkbroadband")
    def test_collect_skips_same_day(self, mock_tb):
        mock_tb.fetch_graph.return_value = b"\x89PNG" + b"\x00" * 200
        c, _, storage = self._make_collector()
        c.collect()
        result = c.collect()
        assert result.data == {"skipped": True}
        assert mock_tb.fetch_graph.call_count == 1

    @patch("app.collectors.bqm.thinkbroadband")
    def test_collect_fetch_failure(self, mock_tb):
        mock_tb.fetch_graph.return_value = None
        c, _, storage = self._make_collector()
        result = c.collect()
        assert result.success is False
        assert "Failed" in result.error
        storage.save_bqm_graph.assert_not_called()

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "bqm"

    @patch("app.collectors.bqm.time")
    def test_should_poll_before_target(self, mock_time):
        """Should not poll if current time is before configured collect_time."""
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "01:30",
        }[fmt]
        c, *_ = self._make_collector(collect_time="02:00")
        assert c.should_poll() is False

    @patch("app.collectors.bqm.time")
    def test_should_poll_after_target(self, mock_time):
        """Should poll if current time is at/after configured collect_time."""
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "02:00",
        }[fmt]
        c, *_ = self._make_collector(collect_time="02:00")
        assert c.should_poll() is True

    @patch("app.collectors.bqm.time")
    def test_should_poll_not_twice_same_day(self, mock_time):
        """Should not poll again after collecting today."""
        mock_time.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d": "2026-02-19",
            "%H:%M": "03:00",
        }[fmt]
        c, *_ = self._make_collector(collect_time="02:00")
        c._last_date = "2026-02-19"
        assert c.should_poll() is False


# ── build_collectors Tests ──


class TestDiscoverCollectors:
    def _make_config_mgr(self, poll_interval=60, bnetz_watch=False, backup=False):
        mgr = MagicMock()
        mgr.is_demo_mode.return_value = False
        mgr.is_configured.return_value = True
        mgr.is_speedtest_configured.return_value = True
        mgr.is_bqm_configured.return_value = True
        mgr.is_bnetz_watch_configured.return_value = bnetz_watch
        mgr.is_backup_configured.return_value = backup
        mgr.is_weather_configured.return_value = False
        mgr.get_all.return_value = {
            "modem_type": "fritzbox",
            "modem_url": "http://fritz.box",
            "modem_user": "admin",
            "modem_password": "pass",
            "poll_interval": poll_interval,
        }
        return mgr

    @patch("app.drivers.load_driver")
    def test_discover_returns_three_collectors(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        analyzer = MagicMock()

        collectors = discover_collectors(
            config_mgr, MagicMock(), MagicMock(), None, MagicMock(), analyzer
        )
        assert len(collectors) == 3
        names = [c.name for c in collectors]
        assert "modem" in names
        assert "speedtest" in names
        assert "bqm" in names

    @patch("app.drivers.load_driver")
    def test_discover_includes_bnetz_watcher(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr(bnetz_watch=True)
        analyzer = MagicMock()

        collectors = discover_collectors(
            config_mgr, MagicMock(), MagicMock(), None, MagicMock(), analyzer
        )
        assert len(collectors) == 4
        names = [c.name for c in collectors]
        assert "bnetz_watcher" in names

    @patch("app.drivers.load_driver")
    def test_modem_collector_gets_poll_interval(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr(poll_interval=120)
        analyzer = MagicMock()

        collectors = discover_collectors(
            config_mgr, MagicMock(), MagicMock(), None, MagicMock(), analyzer
        )
        modem = [c for c in collectors if c.name == "modem"][0]
        assert modem.poll_interval_seconds == 120

    @patch("app.drivers.load_driver")
    def test_driver_loaded_by_modem_type(self, mock_load):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        analyzer = MagicMock()

        discover_collectors(
            config_mgr, MagicMock(), MagicMock(), None, MagicMock(), analyzer
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
        from app.drivers import DRIVER_REGISTRY
        assert "fritzbox" in DRIVER_REGISTRY

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

    @patch("app.drivers.load_driver")
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

    @patch("app.drivers.load_driver")
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
        storage = MagicMock()
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

        storage.get_latest_speedtest_id.assert_not_called()
        storage.save_bqm_graph.assert_not_called()

    @patch("app.drivers.load_driver")
    @patch("app.main.web")
    def test_orchestrator_handles_collector_exception(self, mock_web, mock_load):
        """Orchestrator should catch exceptions and continue running."""
        import threading
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.login.side_effect = RuntimeError("Modem offline")
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        storage = MagicMock()
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

    @patch("app.drivers.load_driver")
    @patch("app.main.web")
    def test_orchestrator_stops_on_event(self, mock_web, mock_load):
        """Orchestrator should exit when stop_event is set."""
        import threading
        from app.main import polling_loop

        mock_load.return_value = MagicMock()

        config_mgr = self._make_config_mgr()
        storage = MagicMock()
        stop = threading.Event()
        stop.set()  # Pre-set: should exit immediately

        polling_loop(config_mgr, storage, stop)
        # If we get here without hanging, the test passes
