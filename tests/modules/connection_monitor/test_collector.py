"""Tests for Connection Monitor collector."""

import time
from unittest.mock import MagicMock, patch
import pytest

from app.modules.connection_monitor.collector import ConnectionMonitorCollector
from app.modules.connection_monitor.probe import ProbeResult
from app.collectors.base import CollectorResult


@pytest.fixture(autouse=True)
def _set_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR to a temp directory so storage init doesn't hit /data."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


@pytest.fixture
def mock_deps(tmp_path):
    config_mgr = MagicMock()
    config_mgr.get.side_effect = lambda key, default=None: {
        "connection_monitor_enabled": True,
        "connection_monitor_poll_interval_ms": 5000,
        "connection_monitor_probe_method": "tcp",
        "connection_monitor_tcp_port": 443,
        "connection_monitor_retention_days": 0,
        "connection_monitor_outage_threshold": 5,
        "connection_monitor_loss_warning_pct": 2.0,
    }.get(key, default)
    storage = MagicMock()
    web = MagicMock()
    return config_mgr, storage, web


class TestCollectorInit:
    def test_creates_with_1s_base_interval(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector._poll_interval_seconds == 1

    def test_should_poll_always_true(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector.should_poll() is True


class TestCollectorEnabled:
    def test_enabled_when_config_true(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector.is_enabled() is True

    def test_disabled_when_config_false(self, mock_deps):
        config_mgr, storage, web = mock_deps
        config_mgr.get.side_effect = lambda key, default=None: {
            "connection_monitor_enabled": False,
        }.get(key, default)
        with patch("app.modules.connection_monitor.collector.ProbeEngine"):
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            assert collector.is_enabled() is False


class TestCollect:
    def test_always_returns_ok(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.probe.return_value = ProbeResult(
                latency_ms=None, timeout=True, method="tcp"
            )
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            # Force a target to be due
            collector._cm_storage = MagicMock()
            collector._cm_storage.get_targets.return_value = [
                {"id": 1, "host": "1.1.1.1", "enabled": True,
                 "poll_interval_ms": 5000, "probe_method": "tcp", "tcp_port": 443},
            ]
            collector._cm_storage.get_summary.return_value = {
                "sample_count": 1, "packet_loss_pct": 0.0,
            }
            collector._last_probe = {}
            result = collector.collect()
            assert result.success is True

    def test_skips_targets_not_due(self, mock_deps):
        config_mgr, storage, web = mock_deps
        with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            collector._cm_storage = MagicMock()
            collector._cm_storage.get_targets.return_value = [
                {"id": 1, "host": "1.1.1.1", "enabled": True,
                 "poll_interval_ms": 5000, "probe_method": "tcp", "tcp_port": 443},
            ]
            # Set last probe to now - target is not due
            collector._last_probe = {1: time.time()}
            result = collector.collect()
            mock_engine.probe.assert_not_called()


class TestCleanupCycle:
    def test_aggregation_called_before_cleanup(self, mock_deps):
        """The cleanup cycle should call aggregate() before cleanup()."""
        config_mgr, storage, web = mock_deps
        config_mgr.get.side_effect = lambda key, default=None: {
            "connection_monitor_enabled": True,
            "connection_monitor_poll_interval_ms": 5000,
            "connection_monitor_probe_method": "tcp",
            "connection_monitor_tcp_port": 443,
            "connection_monitor_retention_days": "7",
            "connection_monitor_outage_threshold": 5,
            "connection_monitor_loss_warning_pct": 2.0,
        }.get(key, default)
        with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.probe.return_value = ProbeResult(
                latency_ms=None, timeout=True, method="tcp"
            )
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
            collector._cm_storage = MagicMock()
            collector._cm_storage.get_targets.return_value = [
                {"id": 1, "host": "1.1.1.1", "enabled": True,
                 "poll_interval_ms": 5000, "probe_method": "tcp", "tcp_port": 443},
            ]
            collector._cm_storage.get_summary.return_value = {
                "sample_count": 1, "packet_loss_pct": 0.0,
            }
            collector._last_probe = {}
            # Force cleanup to run by setting last_cleanup far in the past
            collector._last_cleanup = 0.0

            call_order = []
            collector._cm_storage.aggregate.side_effect = lambda: call_order.append("aggregate")
            collector._cm_storage.cleanup.side_effect = lambda *a, **kw: call_order.append("cleanup")

            collector.collect()

            mock_agg = collector._cm_storage.aggregate
            mock_clean = collector._cm_storage.cleanup
            mock_agg.assert_called_once()
            mock_clean.assert_called_once_with(7)
            # Verify order: aggregate was called before cleanup
            assert call_order == ["aggregate", "cleanup"]
