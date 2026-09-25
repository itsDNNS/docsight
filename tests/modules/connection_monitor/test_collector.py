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


def _config(interval_ms):
    values = {
        "connection_monitor_enabled": True,
        "connection_monitor_poll_interval_ms": interval_ms,
        "connection_monitor_probe_method": "tcp",
        "connection_monitor_tcp_port": 443,
        "connection_monitor_retention_days": 0,
        "connection_monitor_outage_threshold": 5,
        "connection_monitor_loss_warning_pct": 2.0,
    }
    return lambda key, default=None: values.get(key, default)


class TestProbeInterval:
    """The configured probe interval drives probing (issue #873)."""

    def _collector(self, mock_deps, interval_ms, stored_interval_ms=5000):
        config_mgr, storage, web = mock_deps
        config_mgr.get.side_effect = _config(interval_ms)
        with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
            MockEngine.return_value.probe.return_value = ProbeResult(
                latency_ms=10.0, timeout=False, method="tcp"
            )
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
        collector._cm_storage = MagicMock()
        collector._cm_storage.get_targets.return_value = [
            {"id": 1, "host": "1.1.1.1", "enabled": True,
             "poll_interval_ms": stored_interval_ms, "probe_method": "tcp", "tcp_port": 443},
        ]
        collector._cm_storage.get_summary.return_value = {
            "sample_count": 1, "packet_loss_pct": 0.0,
        }
        collector._seeded = True
        collector._last_cleanup = time.time()
        return collector

    def test_configured_interval_makes_target_due_sooner(self, mock_deps):
        collector = self._collector(mock_deps, 1000)
        collector._last_probe = {1: time.time() - 1.5}
        result = collector.collect()
        assert result.data == {"probed": 1}
        collector._probe.probe.assert_called_once()

    def test_target_not_due_within_configured_interval(self, mock_deps):
        collector = self._collector(mock_deps, 10000, stored_interval_ms=1000)
        collector._last_probe = {1: time.time() - 6}
        collector.collect()
        collector._probe.probe.assert_not_called()

    def test_slightly_early_wakeup_still_probes(self, mock_deps):
        collector = self._collector(mock_deps, 1000, stored_interval_ms=1000)
        collector._last_probe = {1: time.time() - 0.97}
        collector.collect()
        collector._probe.probe.assert_called_once()

    def test_disabled_targets_are_synced_but_not_probed(self, mock_deps):
        collector = self._collector(mock_deps, 1000)
        collector._cm_storage.get_targets.return_value = [
            {"id": 2, "host": "", "enabled": False,
             "poll_interval_ms": 5000, "probe_method": "tcp", "tcp_port": 443},
        ]
        collector.collect()
        collector._cm_storage.update_target.assert_called_once_with(2, poll_interval_ms=1000)
        collector._probe.probe.assert_not_called()

    def test_stored_target_interval_follows_configuration(self, mock_deps):
        collector = self._collector(mock_deps, 1000)
        collector._last_probe = {1: time.time()}
        collector.collect()
        collector._cm_storage.update_target.assert_called_once_with(1, poll_interval_ms=1000)

    def test_no_write_when_target_already_matches(self, mock_deps):
        collector = self._collector(mock_deps, 1000, stored_interval_ms=1000)
        collector._last_probe = {1: time.time()}
        collector.collect()
        collector._cm_storage.update_target.assert_not_called()

    @pytest.mark.parametrize("configured, effective", [
        (200, 1000),
        (0, 1000),
        (-5000, 1000),
        ("2000", 2000),
        (86_400_000, 300_000),
        (10**20, 300_000),
        ("not-a-number", 5000),
        (None, 5000),
        (float("inf"), 5000),
    ])
    def test_invalid_or_too_small_values_are_bounded(self, mock_deps, configured, effective):
        collector = self._collector(mock_deps, configured, stored_interval_ms=effective)
        collector._last_probe = {1: time.time()}
        collector.collect()
        collector._cm_storage.update_target.assert_not_called()

    def test_real_storage_reports_configured_interval(self, mock_deps):
        config_mgr, storage, web = mock_deps
        config_mgr.get.side_effect = _config(1000)
        with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
            MockEngine.return_value.probe.return_value = ProbeResult(
                latency_ms=10.0, timeout=False, method="tcp"
            )
            collector = ConnectionMonitorCollector(
                config_mgr=config_mgr, storage=storage, web=web
            )
        collector.collect()  # seeds the default targets with the stored 5000 ms default
        collector.collect()
        intervals = {t["label"]: t["poll_interval_ms"] for t in collector.get_storage().get_targets()}
        assert intervals == {"Cloudflare DNS": 1000, "Google DNS": 1000}


@pytest.mark.parametrize("saved", ["1500.5", "1e3", "abc"])
def test_real_config_value_the_form_can_save_does_not_stop_probing(tmp_path, monkeypatch, saved):
    """ConfigManager.get() raises for these INT-key values; the collector keeps working."""
    import app.config as config_module
    from app.config import ConfigManager

    # The module loader registers manifest integer defaults as INT keys at startup.
    monkeypatch.setattr(
        config_module, "INT_KEYS", config_module.INT_KEYS | {"connection_monitor_poll_interval_ms"}
    )
    config_mgr = ConfigManager(str(tmp_path / "cfg"))
    config_mgr.save({"connection_monitor_enabled": True, "connection_monitor_poll_interval_ms": saved})
    with pytest.raises(ValueError):
        config_mgr.get("connection_monitor_poll_interval_ms")
    with patch("app.modules.connection_monitor.collector.ProbeEngine") as MockEngine:
        MockEngine.return_value.probe.return_value = ProbeResult(
            latency_ms=10.0, timeout=False, method="tcp"
        )
        collector = ConnectionMonitorCollector(
            config_mgr=config_mgr, storage=MagicMock(), web=MagicMock()
        )
    result = collector.collect()
    assert result.success is True
    assert result.data == {"probed": 2}
    assert {t["poll_interval_ms"] for t in collector.get_storage().get_targets()} == {5000}
