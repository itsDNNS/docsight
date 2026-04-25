"""Tests for modem collector behavior and error handling."""

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
        storage.get_device_state.return_value = {}
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

    def test_collect_refreshes_device_info_caches_connection_info(self):
        c, driver, *_ = self._make_collector()
        c.collect()
        c.collect()
        # device_info is refreshed every collect so mutable fields
        # (docsis_status, reboot_reason, uptime_seconds) stay current.
        # connection_info is static and stays cached after first fetch.
        assert driver.get_device_info.call_count == 2
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

    def test_format_uptime(self):
        from app.collectors.modem import format_uptime
        assert format_uptime(None) == "unknown"
        assert format_uptime(60) == "0d 0h 1m"
        assert format_uptime(3660) == "0d 1h 1m"
        assert format_uptime(90060) == "1d 1h 1m"
        assert format_uptime(86400) == "1d 0h 0m"
        assert format_uptime(0) == "0d 0h 0m"

    def test_device_reboot_detected(self):
        c, driver, _, _, storage, _ = self._make_collector()
        # Mock previous state: uptime 1000s
        storage.get_device_state.return_value = {
            "uptime_seconds": 60000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1"
        }
        # Mock current state: uptime 500s (decreased)
        driver.get_device_info.return_value = {
            "uptime_seconds": 500,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1",
            "reboot_reason": "power cycle"
        }
        c.collect()
        
        # Check that events were logged
        storage.save_events.assert_called_once()
        events = storage.save_events.call_args[0][0]
        assert len(events) == 1
        assert events[0]["event_type"] == "device_reboot"
        assert events[0]["severity"] == "warning"
        assert "Prior uptime: 0d 16h 40m, Reason: power cycle" in events[0]["message"]
        
        # Check that device state was updated
        storage.update_device_state.assert_called_once()
        args = storage.update_device_state.call_args[0]
        assert args[0] == 500  # uptime
        assert args[1] == "1.0" # sw_version

    def test_device_reboot_reason_visibility(self):
        """Verify that reason is omitted when None and shown when 'unknown'."""
        c, driver, _, _, storage, _ = self._make_collector()
        
        # 1. Driver is silent (None)
        storage.get_device_state.return_value = {"uptime_seconds": 60000, "sw_version": "1.0"}
        driver.get_device_info.return_value = {"uptime_seconds": 100, "sw_version": "1.0"} # No reboot_reason
        c.collect()
        events = storage.save_events.call_args[0][0]
        assert "Prior uptime: 0d 16h 40m" == events[0]["message"]
        
        storage.save_events.reset_mock()
        
        # 2. Driver explicitly says 'unknown'
        storage.get_device_state.return_value = {"uptime_seconds": 60000, "sw_version": "1.0"}
        driver.get_device_info.return_value = {"uptime_seconds": 100, "sw_version": "1.0", "reboot_reason": "unknown"}
        c.collect()
        events = storage.save_events.call_args[0][0]
        assert "Prior uptime: 0d 16h 40m, Reason: unknown" == events[0]["message"]

    def test_device_sw_update_detected(self):
        c, driver, _, _, storage, _ = self._make_collector()
        storage.get_device_state.return_value = {
            "uptime_seconds": 60000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1"
        }
        driver.get_device_info.return_value = {
            "uptime_seconds": 50,
            "sw_version": "2.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1",
            "reboot_reason": "firmware upgrade"
        }
        c.collect()
        
        storage.save_events.assert_called_once()
        events = storage.save_events.call_args[0][0]
        assert len(events) == 1
        assert events[0]["event_type"] == "device_sw_update"
        assert events[0]["severity"] == "info"
        assert "Prior uptime: 0d 16h 40m, SW: 1.0 → 2.0, Reason: firmware upgrade" == events[0]["message"]

    def test_device_ip_change_detected(self):
        c, driver, _, _, storage, _ = self._make_collector()
        storage.get_device_state.return_value = {
            "uptime_seconds": 60000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1"
        }
        driver.get_device_info.return_value = {
            "uptime_seconds": 70000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.2",
            "wan_ipv6": "::1",
            "reboot_reason": "unknown"
        }
        c.collect()
        
        storage.save_events.assert_called_once()
        events = storage.save_events.call_args[0][0]
        assert len(events) == 1
        assert events[0]["event_type"] == "device_ip_change"
        assert events[0]["severity"] == "info"
        assert "WAN IPv4: 203.0.113.1 → 203.0.113.2" in events[0]["message"]

    def test_device_reboot_with_ip_change(self):
        c, driver, _, _, storage, _ = self._make_collector()
        storage.get_device_state.return_value = {
            "uptime_seconds": 60000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1"
        }
        # Reboot AND IP change
        driver.get_device_info.return_value = {
            "uptime_seconds": 50,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.2",
            "wan_ipv6": "::1",
            "reboot_reason": "power cycle"
        }
        c.collect()
        
        storage.save_events.assert_called_once()
        events = storage.save_events.call_args[0][0]
        assert len(events) == 1
        # Should be combined into reboot
        assert events[0]["event_type"] == "device_reboot"
        assert "WAN IPv4: 203.0.113.1 → 203.0.113.2" in events[0]["message"]


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
        mock_storage.get_device_state.return_value = {}
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


class TestModemCollectorErrors:
    def _make_collector(self):
        driver = MagicMock()
        analyzer_fn = MagicMock()
        event_detector = MagicMock()
        storage = MagicMock()
        storage.get_latest_spike_timestamp.return_value = None
        storage.get_device_state.return_value = {}
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



# ── Device Event / Smart Capture Isolation Regression Tests ──


class TestDeviceEventSmartCaptureIsolation:
    """Regression: device lifecycle events must never trigger Smart Capture,
    and the first poll must only establish a baseline without firing events.

    Smart Capture is wired exclusively to the signal-quality event_detector
    path. Reboot / SW-update / IP-change events are stored and dispatched to
    the notifier but must not reach smart_capture.evaluate().
    """

    def _make_collector(self, initial_state=None):
        driver = MagicMock()
        driver.get_device_info.return_value = {
            "uptime_seconds": 1000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1",
            "reboot_reason": None,
        }
        driver.get_connection_info.return_value = None
        driver.get_docsis_data.return_value = {}

        analyzer_fn = MagicMock(return_value={
            "ds_channels": [], "us_channels": [], "summary": {},
        })
        event_detector = MagicMock()
        event_detector.check.return_value = []

        storage = MagicMock()
        storage.get_latest_spike_timestamp.return_value = None
        storage.get_device_state.return_value = initial_state if initial_state is not None else {}

        web = MagicMock()
        web._state = {}

        smart_capture = MagicMock()

        c = ModemCollector(
            driver=driver,
            analyzer_fn=analyzer_fn,
            event_detector=event_detector,
            storage=storage,
            mqtt_pub=None,
            web=web,
            poll_interval=60,
            smart_capture=smart_capture,
        )
        return c, driver, storage, smart_capture

    def test_reboot_does_not_trigger_smart_capture(self):
        """A detected reboot must not call smart_capture.evaluate()."""
        c, driver, storage, smart_capture = self._make_collector(
            initial_state={"uptime_seconds": 60000, "sw_version": "1.0",
                           "wan_ipv4": "203.0.113.1", "wan_ipv6": "::1"}
        )
        driver.get_device_info.return_value = {
            "uptime_seconds": 50,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1",
            "reboot_reason": "power cycle",
        }
        c.collect()

        storage.save_events.assert_called_once()
        events = storage.save_events.call_args[0][0]
        assert events[0]["event_type"] == "device_reboot"
        smart_capture.evaluate.assert_not_called()

    def test_sw_update_does_not_trigger_smart_capture(self):
        """A detected software update must not call smart_capture.evaluate()."""
        c, driver, storage, smart_capture = self._make_collector(
            initial_state={"uptime_seconds": 60000, "sw_version": "1.0",
                           "wan_ipv4": "203.0.113.1", "wan_ipv6": "::1"}
        )
        driver.get_device_info.return_value = {
            "uptime_seconds": 50,
            "sw_version": "2.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1",
            "reboot_reason": "firmware upgrade",
        }
        c.collect()

        storage.save_events.assert_called_once()
        events = storage.save_events.call_args[0][0]
        assert events[0]["event_type"] == "device_sw_update"
        smart_capture.evaluate.assert_not_called()

    def test_ip_change_does_not_trigger_smart_capture(self):
        """A standalone IP change must not call smart_capture.evaluate()."""
        c, driver, storage, smart_capture = self._make_collector(
            initial_state={"uptime_seconds": 60000, "sw_version": "1.0",
                           "wan_ipv4": "203.0.113.1", "wan_ipv6": "::1"}
        )
        driver.get_device_info.return_value = {
            "uptime_seconds": 70000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.2",
            "wan_ipv6": "::1",
            "reboot_reason": None,
        }
        c.collect()

        storage.save_events.assert_called_once()
        events = storage.save_events.call_args[0][0]
        assert events[0]["event_type"] == "device_ip_change"
        smart_capture.evaluate.assert_not_called()

    def test_first_poll_establishes_baseline_no_event_fired(self):
        """On the very first poll (no prior state in DB), no lifecycle event
        must be stored and Smart Capture must not be called."""
        c, driver, storage, smart_capture = self._make_collector(initial_state=None)
        storage.get_device_state.return_value = None

        driver.get_device_info.return_value = {
            "uptime_seconds": 5000,
            "sw_version": "1.0",
            "wan_ipv4": "203.0.113.1",
            "wan_ipv6": "::1",
            "reboot_reason": None,
        }
        c.collect()

        storage.save_events.assert_not_called()
        smart_capture.evaluate.assert_not_called()
        storage.update_device_state.assert_called_once()
