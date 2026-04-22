"""Tests for collector discovery and polling orchestration."""

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
