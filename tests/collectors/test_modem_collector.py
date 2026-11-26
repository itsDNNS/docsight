"""Tests for modem collector behavior and error handling."""

from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from app.collectors.modem import ModemCollector
from app.drivers.base import ModemDriver


# Last known device state of the device event tests.
_DEVICE_STATE = {"uptime_seconds": 60000, "sw_version": "1.0", "wan_ipv4": "203.0.113.1", "wan_ipv6": "::1"}


def _make_collector(*, mqtt_pub=None, smart_capture=None):
    """A ModemCollector over mocks, returned together with each mock."""
    driver = MagicMock(spec=ModemDriver)
    driver.get_device_info.return_value = {"model": "6690", "sw_version": "7.57"}
    driver.get_connection_info.return_value = {
        "max_downstream_kbps": 1000000,
        "max_upstream_kbps": 50000,
        "connection_type": "Cable",
    }
    driver.get_docsis_data.return_value = {"some": "data"}
    analyzer_fn = MagicMock(return_value={"ds_channels": [], "us_channels": [], "summary": {}})
    event_detector = MagicMock()
    event_detector.check.return_value = []
    storage = MagicMock()
    storage.get_latest_spike_timestamp.return_value = None
    storage.get_device_state.return_value = {}
    web = MagicMock()
    collector = ModemCollector(
        driver=driver, analyzer_fn=analyzer_fn, event_detector=event_detector, storage=storage,
        mqtt_pub=mqtt_pub, web=web, poll_interval=60, smart_capture=smart_capture,
    )
    return SimpleNamespace(collector=collector, driver=driver, analyzer_fn=analyzer_fn, event_detector=event_detector,
                           storage=storage, web=web, smart_capture=smart_capture)


class TestModemCollector:
    def test_login_failure_is_marked_for_the_poll_message(self):
        m = _make_collector()
        m.driver.login.side_effect = RuntimeError("Login failed: wrong password")

        with pytest.raises(RuntimeError) as raised:
            m.collector.collect()

        assert raised.value.modem_stage == "login"
        m.driver.get_docsis_data.assert_not_called()

    def test_collect_full_pipeline(self):
        m = _make_collector()
        result = m.collector.collect()

        assert result.success is True
        assert result.source == "modem"
        m.driver.login.assert_called_once()
        m.driver.get_device_info.assert_called_once()
        m.driver.get_connection_info.assert_called_once()
        m.driver.get_docsis_data.assert_called_once()
        m.analyzer_fn.assert_called_once()
        m.storage.save_snapshot.assert_called_once()
        m.event_detector.check.assert_called_once()
        assert m.web.update_state.call_count >= 3  # device_info, connection_info, analysis

    def test_collect_refreshes_device_info_caches_connection_info(self):
        m = _make_collector()
        m.collector.collect()
        m.collector.collect()
        # device_info is refreshed every collect so mutable fields
        # (docsis_status, reboot_reason, uptime_seconds) stay current.
        # connection_info is static and stays cached after first fetch.
        assert m.driver.get_device_info.call_count == 2
        assert m.driver.get_connection_info.call_count == 1

    def test_collect_with_events(self):
        m = _make_collector()
        m.event_detector.check.return_value = [{"type": "power_change"}]
        m.collector.collect()
        m.storage.save_events_with_ids.assert_called_once()

    def test_collect_with_mqtt(self):
        mqtt = MagicMock()
        _make_collector(mqtt_pub=mqtt).collector.collect()
        mqtt.publish_discovery.assert_called_once()
        mqtt.publish_channel_discovery.assert_called_once()
        mqtt.publish_data.assert_called_once()

    def test_collect_mqtt_discovery_only_once(self):
        mqtt = MagicMock()
        c = _make_collector(mqtt_pub=mqtt).collector
        c.collect()
        c.collect()
        assert mqtt.publish_discovery.call_count == 1
        assert mqtt.publish_data.call_count == 2

    def test_collect_skips_mqtt_while_broker_is_unreachable(self):
        mqtt = MagicMock(is_connected=False, connection_count=0)
        result = _make_collector(mqtt_pub=mqtt).collector.collect()
        assert result.success is True
        mqtt.publish_discovery.assert_not_called()
        mqtt.publish_data.assert_not_called()

    @patch("app.collectors.modem.time.sleep")
    def test_collect_publishes_once_broker_connects_later(self, _sleep):
        mqtt = MagicMock(is_connected=False, connection_count=0)
        c = _make_collector(mqtt_pub=mqtt).collector
        c.collect()
        mqtt.is_connected = True
        mqtt.connection_count = 1
        c.collect()
        mqtt.publish_discovery.assert_called_once()
        mqtt.publish_channel_discovery.assert_called_once()
        mqtt.publish_data.assert_called_once()

    @patch("app.collectors.modem.time.sleep")
    def test_collect_publishes_discovery_again_after_reconnect(self, _sleep):
        # A broker restarted without persistence has lost the retained discovery.
        mqtt = MagicMock(is_connected=True, connection_count=1)
        c = _make_collector(mqtt_pub=mqtt).collector
        c.collect()
        c.collect()
        mqtt.connection_count = 2
        c.collect()
        assert mqtt.publish_discovery.call_count == 2
        assert mqtt.publish_channel_discovery.call_count == 2
        assert mqtt.publish_data.call_count == 3

    def test_collect_no_mqtt(self):
        result = _make_collector(mqtt_pub=None).collector.collect()
        assert result.success is True

    def test_name(self):
        assert _make_collector().collector.name == "modem"

    def test_format_uptime(self):
        from app.collectors.modem import format_uptime
        assert format_uptime(None) == "unknown"
        assert format_uptime(60) == "0d 0h 1m"
        assert format_uptime(3660) == "0d 1h 1m"
        assert format_uptime(90060) == "1d 1h 1m"
        assert format_uptime(86400) == "1d 0h 0m"
        assert format_uptime(0) == "0d 0h 0m"

    def test_device_reboot_detected(self):
        m = _make_collector()
        # Previous state: uptime 60000s; current state: uptime 500s (decreased)
        m.storage.get_device_state.return_value = _DEVICE_STATE
        m.driver.get_device_info.return_value = {**_DEVICE_STATE, "uptime_seconds": 500, "reboot_reason": "power cycle"}
        m.collector.collect()

        # Check that events were logged
        m.storage.save_events.assert_called_once()
        events = m.storage.save_events.call_args[0][0]
        assert len(events) == 1
        assert events[0]["event_type"] == "device_reboot"
        assert events[0]["severity"] == "warning"
        assert "Prior uptime: 0d 16h 40m, Reason: power cycle" in events[0]["message"]

        # Check that device state was updated
        m.storage.update_device_state.assert_called_once()
        args = m.storage.update_device_state.call_args[0]
        assert args[0] == 500  # uptime
        assert args[1] == "1.0" # sw_version

    def test_device_reboot_reason_visibility(self):
        """Verify that reason is omitted when None and shown when 'unknown'."""
        m = _make_collector()

        # 1. Driver is silent (None)
        m.storage.get_device_state.return_value = {"uptime_seconds": 60000, "sw_version": "1.0"}
        m.driver.get_device_info.return_value = {"uptime_seconds": 100, "sw_version": "1.0"} # No reboot_reason
        m.collector.collect()
        events = m.storage.save_events.call_args[0][0]
        assert "Prior uptime: 0d 16h 40m" == events[0]["message"]

        m.storage.save_events.reset_mock()

        # 2. Driver explicitly says 'unknown'
        m.storage.get_device_state.return_value = {"uptime_seconds": 60000, "sw_version": "1.0"}
        m.driver.get_device_info.return_value = {"uptime_seconds": 100, "sw_version": "1.0", "reboot_reason": "unknown"}
        m.collector.collect()
        events = m.storage.save_events.call_args[0][0]
        assert "Prior uptime: 0d 16h 40m, Reason: unknown" == events[0]["message"]

    def test_device_sw_update_detected(self):
        m = _make_collector()
        m.storage.get_device_state.return_value = _DEVICE_STATE
        m.driver.get_device_info.return_value = {
            **_DEVICE_STATE, "uptime_seconds": 50, "sw_version": "2.0", "reboot_reason": "firmware upgrade",
        }
        m.collector.collect()

        m.storage.save_events.assert_called_once()
        events = m.storage.save_events.call_args[0][0]
        assert len(events) == 1
        assert events[0]["event_type"] == "device_sw_update"
        assert events[0]["severity"] == "info"
        assert "Prior uptime: 0d 16h 40m, SW: 1.0 → 2.0, Reason: firmware upgrade" == events[0]["message"]

    def test_device_ip_change_detected(self):
        m = _make_collector()
        m.storage.get_device_state.return_value = _DEVICE_STATE
        m.driver.get_device_info.return_value = {
            **_DEVICE_STATE, "uptime_seconds": 70000, "wan_ipv4": "203.0.113.2", "reboot_reason": "unknown",
        }
        m.collector.collect()

        m.storage.save_events.assert_called_once()
        events = m.storage.save_events.call_args[0][0]
        assert len(events) == 1
        assert events[0]["event_type"] == "device_ip_change"
        assert events[0]["severity"] == "info"
        assert "WAN IPv4: 203.0.113.1 → 203.0.113.2" in events[0]["message"]

    def test_device_reboot_with_ip_change(self):
        m = _make_collector()
        m.storage.get_device_state.return_value = _DEVICE_STATE
        # Reboot AND IP change
        m.driver.get_device_info.return_value = {
            **_DEVICE_STATE, "uptime_seconds": 50, "wan_ipv4": "203.0.113.2", "reboot_reason": "power cycle",
        }
        m.collector.collect()

        m.storage.save_events.assert_called_once()
        events = m.storage.save_events.call_args[0][0]
        assert len(events) == 1
        # Should be combined into reboot
        assert events[0]["event_type"] == "device_reboot"
        assert "WAN IPv4: 203.0.113.1 → 203.0.113.2" in events[0]["message"]


class TestModemCollectorSpikeSuppression:
    """Verify spike suppression is called in the collector pipeline."""

    def test_modem_collector_calls_spike_suppression(self):
        """ModemCollector calls apply_spike_suppression after analyze."""
        m = _make_collector()
        m.driver.get_device_info.return_value = {"model": "Test", "sw_version": "1.0"}
        m.driver.get_connection_info.return_value = None
        m.driver.get_docsis_data.return_value = {"channelDs": {"docsis30": []}, "channelUs": {"docsis30": []}}
        m.event_detector.check.return_value = [{"type": "power_change"}]  # suppression applies before event handling
        previous_analysis = {"summary": {"ds_correctable_errors": 1, "ds_uncorrectable_errors": 1}, "ds_channels": [], "us_channels": []}
        m.storage.get_latest_snapshot.return_value = previous_analysis
        analysis = m.analyzer_fn.return_value = {
            "summary": {"health": "good", "health_issues": [], "ds_total": 0, "us_total": 0},
            "ds_channels": [],
            "us_channels": [],
        }

        with patch("app.collectors.modem.apply_cumulative_error_baseline") as mock_baseline, \
             patch("app.collectors.modem.apply_spike_suppression") as mock_suppress:
            m.collector.collect()
            mock_baseline.assert_called_once_with(analysis, previous_analysis, recent_spike_active=False)
            mock_suppress.assert_called_once_with(analysis, None)


class TestModemCollectorErrors:
    def test_login_failure_propagates(self):
        m = _make_collector()
        m.driver.login.side_effect = RuntimeError("Auth failed")
        with pytest.raises(RuntimeError, match="Auth failed"):
            m.collector.collect()

    def test_get_docsis_data_failure_propagates(self):
        m = _make_collector()
        m.driver.get_device_info.return_value = {"model": "X", "sw_version": "1"}
        m.driver.get_connection_info.return_value = {}
        m.driver.get_docsis_data.side_effect = RuntimeError("Timeout")
        with pytest.raises(RuntimeError, match="Timeout"):
            m.collector.collect()

    def test_login_failure_does_not_update_web_state(self):
        m = _make_collector()
        m.driver.login.side_effect = RuntimeError("Auth failed")
        with pytest.raises(RuntimeError):
            m.collector.collect()
        m.web.update_state.assert_not_called()

    def test_device_info_failure_propagates(self):
        m = _make_collector()
        m.driver.get_device_info.side_effect = RuntimeError("HTTP 500")
        with pytest.raises(RuntimeError, match="HTTP 500"):
            m.collector.collect()

    def test_analyzer_failure_propagates(self):
        m = _make_collector()
        m.driver.get_device_info.return_value = {"model": "X", "sw_version": "1"}
        m.driver.get_connection_info.return_value = {}
        m.driver.get_docsis_data.return_value = {"bad": "data"}
        m.analyzer_fn.side_effect = KeyError("ds_channels")
        with pytest.raises(KeyError):
            m.collector.collect()

    def test_storage_failure_propagates(self):
        m = _make_collector()
        m.driver.get_device_info.return_value = {"model": "X", "sw_version": "1"}
        m.driver.get_connection_info.return_value = {}
        m.driver.get_docsis_data.return_value = {}
        m.storage.save_snapshot.side_effect = RuntimeError("Disk full")
        with pytest.raises(RuntimeError, match="Disk full"):
            m.collector.collect()


# ── Device Event / Smart Capture Isolation Regression Tests ──


class TestDeviceEventSmartCaptureIsolation:
    """Regression: device lifecycle events must never trigger Smart Capture,
    and the first poll must only establish a baseline without firing events.

    Smart Capture is wired exclusively to the signal-quality event_detector
    path. Reboot / SW-update / IP-change events are stored and dispatched to
    the notifier but must not reach smart_capture.evaluate().
    """

    @pytest.mark.parametrize("device_info,event_type", [
        ({**_DEVICE_STATE, "uptime_seconds": 50, "reboot_reason": "power cycle"}, "device_reboot"),
        ({**_DEVICE_STATE, "uptime_seconds": 50, "sw_version": "2.0", "reboot_reason": "firmware upgrade"}, "device_sw_update"),
        ({**_DEVICE_STATE, "uptime_seconds": 70000, "wan_ipv4": "203.0.113.2", "reboot_reason": None}, "device_ip_change"),
    ], ids=["reboot", "sw-update", "ip-change"])
    def test_device_event_does_not_trigger_smart_capture(self, device_info, event_type):
        """A detected reboot, software update or standalone IP change must not call smart_capture.evaluate()."""
        m = _make_collector(smart_capture=MagicMock())
        m.driver.get_connection_info.return_value = None
        m.driver.get_docsis_data.return_value = {}
        m.storage.get_device_state.return_value = _DEVICE_STATE
        m.driver.get_device_info.return_value = device_info
        m.collector.collect()

        m.storage.save_events.assert_called_once()
        events = m.storage.save_events.call_args[0][0]
        assert events[0]["event_type"] == event_type
        m.smart_capture.evaluate.assert_not_called()

    def test_first_poll_establishes_baseline_no_event_fired(self):
        """On the very first poll (no prior state in DB), no lifecycle event
        must be stored and Smart Capture must not be called."""
        m = _make_collector(smart_capture=MagicMock())
        m.driver.get_connection_info.return_value = None
        m.driver.get_docsis_data.return_value = {}
        m.storage.get_device_state.return_value = None
        m.driver.get_device_info.return_value = {**_DEVICE_STATE, "uptime_seconds": 5000, "reboot_reason": None}
        m.collector.collect()

        m.storage.save_events.assert_not_called()
        m.smart_capture.evaluate.assert_not_called()
        m.storage.update_device_state.assert_called_once()
