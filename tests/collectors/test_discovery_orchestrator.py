"""Tests for collector discovery and polling orchestration."""

import sqlite3
import threading
import time
from concurrent.futures import Future
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from app.collectors.base import Collector, CollectorResult


class TestDiscoverCollectors:
    def test_collector_registry_is_not_exported(self):
        import app.collectors as collectors

        assert not hasattr(collectors, "COLLECTOR_REGISTRY")

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
    def test_discover_returns_modem_plus_modules(self, mock_load, mock_storage):
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
            config_mgr, mock_storage, MagicMock(), None, web, analyzer
        )
        assert len(collectors) == 4  # modem + segment_utilization + speedtest + bqm
        names = [c.name for c in collectors]
        assert "modem" in names
        assert "segment_utilization" in names
        assert "speedtest" in names
        assert "bqm" in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_discover_includes_bnetz_watcher_module(self, mock_load, mock_storage):
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
            config_mgr, mock_storage, MagicMock(), None, web, analyzer
        )
        assert len(collectors) == 3  # modem + segment_utilization + bnetz_watcher
        names = [c.name for c in collectors]
        assert "bnetz_watcher" in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_discover_no_modules_returns_modem_only(self, mock_load, mock_storage):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        analyzer = MagicMock()

        # Web without module_loader attribute
        web = MagicMock(spec=[])

        collectors = discover_collectors(
            config_mgr, mock_storage, MagicMock(), None, web, analyzer
        )
        assert len(collectors) == 2  # modem + segment_utilization
        names = [c.name for c in collectors]
        assert "modem" in names
        assert "segment_utilization" in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_discover_skips_segment_when_disabled(self, mock_load, mock_storage):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        config_mgr.is_segment_utilization_enabled.return_value = False
        analyzer = MagicMock()

        web = MagicMock(spec=[])

        collectors = discover_collectors(
            config_mgr, mock_storage, MagicMock(), None, web, analyzer
        )
        names = [c.name for c in collectors]
        assert "modem" in names
        assert "segment_utilization" not in names

    @patch("app.drivers.driver_registry.load_driver")
    def test_modem_collector_gets_poll_interval(self, mock_load, mock_storage):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr(poll_interval=120)
        analyzer = MagicMock()

        # Web without module_loader
        web = MagicMock(spec=[])

        collectors = discover_collectors(
            config_mgr, mock_storage, MagicMock(), None, web, analyzer
        )
        modem = [c for c in collectors if c.name == "modem"][0]
        assert modem.poll_interval_seconds == 120

    @patch("app.drivers.driver_registry.load_driver")
    def test_driver_loaded_by_modem_type(self, mock_load, mock_storage):
        from app.collectors import discover_collectors

        mock_load.return_value = MagicMock()
        config_mgr = self._make_config_mgr()
        analyzer = MagicMock()

        # Web without module_loader
        web = MagicMock(spec=[])

        discover_collectors(
            config_mgr, mock_storage, MagicMock(), None, web, analyzer
        )
        mock_load.assert_called_once_with("fritzbox", "http://fritz.box", "admin", "pass")


@pytest.fixture
def mock_runtime():
    return MagicMock(smart_capture_ticks=0)


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

    @staticmethod
    def _stop_when(stop, done, timeout=5):
        """Tick polling_loop until done() holds; collectors run in a thread pool."""
        deadline = time.monotonic() + timeout

        def wait(_timeout=None):
            if done():
                stop.set()
            elif time.monotonic() > deadline:
                pytest.fail(f"polling_loop did not reach the expected state within {timeout}s")
            else:
                time.sleep(0.01)

        stop.wait = wait

    @staticmethod
    def _working_driver(mock_load):
        driver = mock_load.return_value
        driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        driver.get_connection_info.return_value = {}
        driver.get_docsis_data.return_value = {}
        return driver

    @patch("app.main.discover_collectors")
    def test_long_running_collector_is_tracked_until_result(
        self, mock_discover, mock_runtime, mock_storage, caplog, monkeypatch
    ):
        """A collector crossing the old observation window is not resubmitted."""
        from app import main

        polling_loop = main.polling_loop
        monkeypatch.setattr(main, "COLLECTOR_LONG_RUNNING_SECONDS", 0)

        started = threading.Event()
        release = threading.Event()
        success_recorded = threading.Event()

        class SlowCollector(Collector):
            name = "slow"

            def __init__(self):
                super().__init__(poll_interval_seconds=3600)
                self.collect_calls = 0
                self.success_calls = 0
                self.failure_calls = 0
                self.skip_calls = 0

            def collect(self):
                self.collect_calls += 1
                started.set()
                assert release.wait(2)
                return CollectorResult(source=self.name)

            def record_success(self):
                self.success_calls += 1
                super().record_success()
                success_recorded.set()

            def record_failure(self):
                self.failure_calls += 1
                super().record_failure()

            def record_skip(self):
                self.skip_calls += 1
                super().record_skip()

        collector = SlowCollector()
        mock_discover.return_value = [collector]
        config_mgr = self._make_config_mgr()
        stop = threading.Event()
        tick = 0
        deadline = None

        def advance_tick(timeout=None):
            nonlocal tick, deadline
            tick += 1
            if tick == 1:
                assert started.wait(1)
            elif tick == 2:
                assert collector.collect_calls == 1
                release.set()
                deadline = time.monotonic() + 2
            elif success_recorded.is_set():
                stop.set()
                return True
            else:
                assert deadline is not None
                assert time.monotonic() < deadline
            return False

        stop.wait = advance_tick

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        assert collector.collect_calls == 1
        assert collector.success_calls == 1
        assert collector.failure_calls == 0
        assert collector.skip_calls == 0
        warnings = [
            record for record in caplog.records
            if "slow: still running after" in record.getMessage()
        ]
        assert len(warnings) == 1

    @patch("app.drivers.driver_registry.load_driver")
    @patch("app.collectors.modem.ModemCollector")
    @patch("app.main.discover_collectors")
    def test_hot_swap_waits_for_in_flight_collector_with_same_name(
        self, mock_discover, mock_modem_cls, mock_load, mock_runtime, mock_storage, monkeypatch
    ):
        """A replacement modem waits for the prior modem future to finish."""
        from app import main

        class ControlledCollector(Collector):
            name = "modem"

            def __init__(self):
                super().__init__(poll_interval_seconds=3600)
                self.success_calls = 0
                self.success_recorded = threading.Event()

            def collect(self):
                raise AssertionError("controlled executor should not invoke collect()")

            def record_success(self):
                self.success_calls += 1
                super().record_success()
                self.success_recorded.set()

        old_collector = ControlledCollector()
        replacement_collector = ControlledCollector()
        mock_discover.return_value = [old_collector]
        mock_modem_cls.return_value = replacement_collector

        submissions = []
        futures = {}

        class ControlledExecutor:
            def __init__(self, *args, **kwargs):
                pass

            def submit(self, fn, collector):
                future = Future()
                submissions.append(collector)
                futures[collector] = future
                if collector is replacement_collector:
                    future.set_result(
                        (collector, CollectorResult(source=collector.name))
                    )
                return future

            def shutdown(self, *args, **kwargs):
                pass

        monkeypatch.setattr(main, "ThreadPoolExecutor", ControlledExecutor)

        config_mgr = self._make_config_mgr()
        modem_type = "fritzbox"

        def get_config(key, default=None):
            return {
                "modem_type": modem_type,
                "modem_url": "http://fritz.box",
                "modem_user": "admin",
                "modem_password": "pass",
            }.get(key, default)

        config_mgr.get.side_effect = get_config
        stop = threading.Event()
        tick = 0

        def advance_tick(timeout=None):
            nonlocal tick, modem_type
            tick += 1
            if tick == 1:
                assert submissions == [old_collector]
                modem_type = "tc4400"
            elif tick == 2:
                assert submissions == [old_collector]
                futures[old_collector].set_result(
                    (
                        old_collector,
                        CollectorResult(source=old_collector.name),
                    )
                )
            elif tick == 3:
                assert submissions == [old_collector, replacement_collector]
                assert old_collector.success_recorded.is_set()
                assert replacement_collector.success_recorded.is_set()
                stop.set()
                return True
            return False

        stop.wait = advance_tick

        main.polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        assert old_collector.success_calls == 1
        assert replacement_collector.success_calls == 1

    @patch("app.drivers.driver_registry.load_driver")
    def test_orchestrator_calls_enabled_collectors(self, mock_load, mock_runtime, mock_storage):
        """Orchestrator should call collect() for enabled collectors."""
        from app.main import polling_loop

        mock_driver = self._working_driver(mock_load)

        config_mgr = self._make_config_mgr()
        stop = threading.Event()
        self._stop_when(stop, lambda: mock_driver.get_docsis_data.call_count)

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        mock_driver.login.assert_called()
        mock_driver.get_docsis_data.assert_called()

    @patch("app.drivers.driver_registry.load_driver")
    def test_orchestrator_skips_disabled_collectors(self, mock_load, mock_runtime, mock_storage):
        """Speedtest/BQM collectors should be skipped when not configured."""
        from app.main import polling_loop

        mock_driver = self._working_driver(mock_load)

        config_mgr = self._make_config_mgr()
        stop = threading.Event()
        self._stop_when(stop, lambda: mock_driver.get_docsis_data.call_count)

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        # Core storage should not have speedtest/bqm methods called
        # (those are now handled by module-internal storage)
        mock_storage.get_latest_speedtest_id.assert_not_called()
        mock_storage.save_bqm_graph.assert_not_called()

    @patch("app.drivers.driver_registry.load_driver")
    def test_orchestrator_handles_collector_exception(self, mock_load, mock_runtime, mock_storage):
        """Orchestrator should catch exceptions and continue running."""
        from app.main import polling_loop

        mock_driver = MagicMock()
        mock_driver.login.side_effect = RuntimeError("Modem offline")
        mock_load.return_value = mock_driver

        config_mgr = self._make_config_mgr()
        stop = threading.Event()
        self._stop_when(stop, lambda: any(
            "error" in c.kwargs for c in mock_runtime.update_state.call_args_list
        ))

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        mock_runtime.update_state.assert_any_call(error="Modem login failed, see the DOCSight log")

    @patch("app.drivers.driver_registry.load_driver")
    def test_orchestrator_stops_on_event(self, mock_load, mock_runtime, mock_storage):
        """Orchestrator should exit when stop_event is set."""
        from app.main import polling_loop

        mock_load.return_value = MagicMock()

        config_mgr = self._make_config_mgr()
        stop = threading.Event()
        stop.set()  # Pre-set: should exit immediately

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)
        # If we get here without hanging, the test passes

    # A failed fired write skips the pending write of that sweep; both run again 60 ticks later.
    @pytest.mark.parametrize("failing_write,first_sweep", [
        (None, ["fired", "pending"]), ("fired", ["fired"]), ("pending", ["fired", "pending"]),
    ])
    @pytest.mark.parametrize("loop_error", [None, RuntimeError("loop boom")])
    @patch("app.main.discover_collectors")
    def test_expiry_cadence_survives_restarts_and_cleanup_always_runs(
        self, mock_discover, loop_error, failing_write, first_sweep, mock_runtime, mock_storage, caplog
    ):
        from app.main import polling_loop

        collector = MagicMock()
        collector.name = "stubborn"
        collector.is_enabled.return_value = False
        collector.stop.side_effect = RuntimeError("stop boom")
        # The third start fails during collector discovery, after MQTT is up.
        mock_discover.side_effect = [[collector], [collector], RuntimeError("discovery boom")]
        publisher = MagicMock()
        publisher.return_value.disconnect.side_effect = RuntimeError("mqtt boom")
        mock_runtime.get_module_loader.return_value.get_enabled_modules.return_value = [
            MagicMock(id="docsight.mqtt", publisher_class=publisher)
        ]
        config_mgr = self._make_config_mgr()
        config_mgr.is_mqtt_configured.return_value = True
        ticks, writes = [], []

        def storage_write(name):
            def write(*_args, **_kwargs):
                writes.append((name, len(ticks)))
                if name == failing_write and len(ticks) == 59:
                    raise sqlite3.OperationalError("database is locked")
                return 0
            return write

        for name in ("fired", "pending"):
            getattr(mock_storage, f"expire_stale_{name}").side_effect = storage_write(name)

        # The second run restarts the loop on the same runtime.
        for last_tick in (59, 120):
            stop = threading.Event()

            def tick(_timeout=None, stop=stop, last_tick=last_tick):
                ticks.append(_timeout)
                if len(ticks) == last_tick:
                    stop.set()
                    if loop_error:
                        raise loop_error

            stop.wait = tick
            with pytest.raises(RuntimeError, match="loop boom") if loop_error else nullcontext():
                polling_loop(config_mgr, mock_storage, stop, mock_runtime)
        with pytest.raises(RuntimeError, match="discovery boom"):
            polling_loop(config_mgr, mock_storage, threading.Event(), mock_runtime)

        # Sweeps run in the 60th and 120th loop iteration, before that iteration's tick.
        assert writes == [(name, 59) for name in first_sweep] + [("fired", 119), ("pending", 119)]
        assert ("Smart Capture expiry failed: database is locked" in caplog.messages) == bool(failing_write)
        cleanup = [m for m in caplog.messages if m.endswith("boom")]
        stop_and_disconnect = ["stubborn: stop failed: stop boom", "MQTT disconnect failed: mqtt boom"]
        assert cleanup == stop_and_disconnect * 2 + ["MQTT disconnect failed: mqtt boom"]
        assert publisher.return_value.connect.call_count == publisher.return_value.disconnect.call_count == 3

    @patch("app.drivers.driver_registry.load_driver")
    def test_driver_hot_swap_on_modem_type_change(self, mock_load, mock_runtime, mock_storage):
        """Polling loop should hot-swap the modem driver when modem_type changes."""
        from app.main import polling_loop

        self._working_driver(mock_load)

        config_mgr = self._make_config_mgr()
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

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        # load_driver should have been called at least twice:
        # once for initial setup, once for hot-swap
        assert mock_load.call_count >= 2
        # Second call should use the new modem type
        second_call = mock_load.call_args_list[1]
        assert second_call[0][0] == "tc4400"
        # Web state should have been reset for the swap
        mock_runtime.reset_modem_state.assert_called()
        assert mock_runtime.modem_collector.name == "modem"

    @patch("app.drivers.driver_registry.load_driver")
    def test_driver_hot_swap_on_url_change(self, mock_load, mock_runtime, mock_storage):
        """Hot-swap should trigger when modem URL changes, not just type."""
        from app.main import polling_loop

        self._working_driver(mock_load)

        config_mgr = self._make_config_mgr()
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

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        # load_driver called twice: initial + hot-swap for URL change
        assert mock_load.call_count >= 2
        second_call = mock_load.call_args_list[1]
        assert second_call[0][1] == "http://192.168.100.1"

    @patch("app.drivers.driver_registry.load_driver")
    def test_no_hot_swap_when_config_unchanged(self, mock_load, mock_runtime, mock_storage):
        """No hot-swap should occur when modem config hasn't changed."""
        from app.main import polling_loop

        self._working_driver(mock_load)

        config_mgr = self._make_config_mgr()
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

        polling_loop(config_mgr, mock_storage, stop, mock_runtime)

        # load_driver should only be called once (initial setup)
        assert mock_load.call_count == 1
        # reset_modem_state should NOT have been called (no swap)
        mock_runtime.reset_modem_state.assert_not_called()
