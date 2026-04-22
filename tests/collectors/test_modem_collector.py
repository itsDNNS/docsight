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

