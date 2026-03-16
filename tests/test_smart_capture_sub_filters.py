"""Tests for Smart Capture per-trigger sub-filter functions."""

import pytest
from unittest.mock import MagicMock

from app.smart_capture.sub_filters import (
    modulation_sub_filter,
    snr_sub_filter,
    error_spike_sub_filter,
    health_sub_filter,
    packet_loss_sub_filter,
)


def _config(**overrides):
    defaults = {
        "sc_trigger_modulation_direction": "both",
        "sc_trigger_modulation_min_qam": "",
        "sc_trigger_error_spike_min_delta": 0,
        "sc_trigger_health_level": "any_degradation",
        "sc_trigger_packet_loss_min_pct": "5.0",
    }
    defaults.update(overrides)
    mock = MagicMock()
    mock.get = lambda key, default=None: defaults.get(key, default)
    return mock


class TestModulationSubFilter:
    def _event(self, changes):
        return {"event_type": "modulation_change", "severity": "warning",
                "details": {"direction": "downgrade", "changes": changes}}

    def test_no_filter_passes(self):
        config = _config()
        event = self._event([{"channel": 1, "direction": "DS", "prev_rank": 7, "current_rank": 5}])
        assert modulation_sub_filter(config, event) is True

    def test_direction_ds_only(self):
        config = _config(sc_trigger_modulation_direction="DS")
        event = self._event([
            {"channel": 1, "direction": "US", "prev_rank": 5, "current_rank": 3},
        ])
        assert modulation_sub_filter(config, event) is False

    def test_direction_ds_passes_ds_change(self):
        config = _config(sc_trigger_modulation_direction="DS")
        event = self._event([
            {"channel": 1, "direction": "DS", "prev_rank": 7, "current_rank": 5},
        ])
        assert modulation_sub_filter(config, event) is True

    def test_direction_us_only(self):
        config = _config(sc_trigger_modulation_direction="US")
        event = self._event([
            {"channel": 1, "direction": "DS", "prev_rank": 7, "current_rank": 5},
        ])
        assert modulation_sub_filter(config, event) is False

    def test_min_qam_threshold(self):
        """Only trigger when current rank is below 256QAM (rank 7)."""
        config = _config(sc_trigger_modulation_min_qam="256QAM")
        # 64QAM (rank 5) is below 256QAM (rank 7) → qualifies
        event = self._event([{"channel": 1, "direction": "DS", "prev_rank": 7, "current_rank": 5}])
        assert modulation_sub_filter(config, event) is True

    def test_min_qam_above_threshold(self):
        """Don't trigger when current rank is at or above threshold."""
        config = _config(sc_trigger_modulation_min_qam="64QAM")
        # 256QAM (rank 7) is above 64QAM (rank 5) → does not qualify
        event = self._event([{"channel": 1, "direction": "DS", "prev_rank": 9, "current_rank": 7}])
        assert modulation_sub_filter(config, event) is False

    def test_qualifying_subset_any_match(self):
        """If ANY change qualifies, the filter passes."""
        config = _config(sc_trigger_modulation_direction="DS")
        event = self._event([
            {"channel": 1, "direction": "US", "prev_rank": 5, "current_rank": 3},  # not DS
            {"channel": 2, "direction": "DS", "prev_rank": 7, "current_rank": 5},  # DS → qualifies
        ])
        assert modulation_sub_filter(config, event) is True

    def test_empty_changes_passes(self):
        config = _config()
        event = self._event([])
        assert modulation_sub_filter(config, event) is True


class TestSnrSubFilter:
    def test_always_passes(self):
        config = _config()
        event = {"event_type": "snr_change", "severity": "warning", "details": {}}
        assert snr_sub_filter(config, event) is True


class TestErrorSpikeSubFilter:
    def test_zero_min_delta_passes_all(self):
        config = _config(sc_trigger_error_spike_min_delta=0)
        event = {"event_type": "error_spike", "details": {"delta": 100}}
        assert error_spike_sub_filter(config, event) is True

    def test_min_delta_filters(self):
        config = _config(sc_trigger_error_spike_min_delta=5000)
        event = {"event_type": "error_spike", "details": {"delta": 2000}}
        assert error_spike_sub_filter(config, event) is False

    def test_min_delta_passes(self):
        config = _config(sc_trigger_error_spike_min_delta=1000)
        event = {"event_type": "error_spike", "details": {"delta": 5000}}
        assert error_spike_sub_filter(config, event) is True


class TestHealthSubFilter:
    def test_any_degradation_passes_all(self):
        config = _config(sc_trigger_health_level="any_degradation")
        event = {"event_type": "health_change", "details": {"current": "marginal"}}
        assert health_sub_filter(config, event) is True

    def test_critical_only_blocks_marginal(self):
        config = _config(sc_trigger_health_level="critical_only")
        event = {"event_type": "health_change", "details": {"current": "marginal"}}
        assert health_sub_filter(config, event) is False

    def test_critical_only_passes_critical(self):
        config = _config(sc_trigger_health_level="critical_only")
        event = {"event_type": "health_change", "details": {"current": "critical"}}
        assert health_sub_filter(config, event) is True


class TestPacketLossSubFilter:
    def test_above_threshold_passes(self):
        config = _config(sc_trigger_packet_loss_min_pct="5.0")
        event = {"event_type": "cm_packet_loss_warning",
                 "details": {"packet_loss_pct": 8.5, "target_id": 1}}
        assert packet_loss_sub_filter(config, event) is True

    def test_below_threshold_fails(self):
        config = _config(sc_trigger_packet_loss_min_pct="10.0")
        event = {"event_type": "cm_packet_loss_warning",
                 "details": {"packet_loss_pct": 5.0, "target_id": 1}}
        assert packet_loss_sub_filter(config, event) is False

    def test_equal_threshold_passes(self):
        config = _config(sc_trigger_packet_loss_min_pct="5.0")
        event = {"event_type": "cm_packet_loss_warning",
                 "details": {"packet_loss_pct": 5.0, "target_id": 1}}
        assert packet_loss_sub_filter(config, event) is True


# ── Config key coverage ──

class TestConfigKeysExist:
    """Verify sub-settings config keys are properly registered."""

    def test_sub_settings_in_defaults(self):
        from app.config import DEFAULTS
        assert "sc_trigger_modulation_direction" in DEFAULTS
        assert "sc_trigger_modulation_min_qam" in DEFAULTS
        assert "sc_trigger_error_spike_min_delta" in DEFAULTS
        assert "sc_trigger_health_level" in DEFAULTS
        assert "sc_trigger_packet_loss" in DEFAULTS
        assert "sc_trigger_packet_loss_min_pct" in DEFAULTS

    def test_sub_settings_default_values(self):
        from app.config import DEFAULTS
        assert DEFAULTS["sc_trigger_modulation_direction"] == "both"
        assert DEFAULTS["sc_trigger_modulation_min_qam"] == ""
        assert DEFAULTS["sc_trigger_error_spike_min_delta"] == 0
        assert DEFAULTS["sc_trigger_health_level"] == "any_degradation"
        assert DEFAULTS["sc_trigger_packet_loss"] is False

    def test_packet_loss_in_bool_keys(self):
        from app.config import BOOL_KEYS
        assert "sc_trigger_packet_loss" in BOOL_KEYS

    def test_error_spike_delta_in_int_keys(self):
        from app.config import INT_KEYS
        assert "sc_trigger_error_spike_min_delta" in INT_KEYS


# ── CM Collector Smart Capture integration ──

class TestCMCollectorSmartCapture:
    """Verify CM collector wires Smart Capture correctly."""

    def test_set_smart_capture_stores_reference(self):
        from unittest.mock import patch
        cm_defaults = {
            "connection_monitor_probe_method": "auto",
            "connection_monitor_outage_threshold": "5",
            "connection_monitor_loss_warning_pct": "2.0",
        }
        with patch("app.modules.connection_monitor.collector.ConnectionMonitorStorage"):
            with patch("app.modules.connection_monitor.collector.ProbeEngine"):
                from app.modules.connection_monitor.collector import ConnectionMonitorCollector
                config = MagicMock()
                config.get = MagicMock(side_effect=lambda k, d=None: cm_defaults.get(k, d))
                storage = MagicMock()
                storage.db_path = ":memory:"
                web = MagicMock()
                collector = ConnectionMonitorCollector(config_mgr=config, storage=storage, web=web)
                assert collector._smart_capture is None
                mock_engine = MagicMock()
                collector.set_smart_capture(mock_engine)
                assert collector._smart_capture is mock_engine

    def test_check_events_calls_evaluate_with_annotated_events(self):
        """_check_events() must save via save_events_with_ids and pass annotated events to evaluate."""
        from unittest.mock import patch, call
        cm_defaults = {
            "connection_monitor_probe_method": "auto",
            "connection_monitor_outage_threshold": "5",
            "connection_monitor_loss_warning_pct": "2.0",
        }
        with patch("app.modules.connection_monitor.collector.ConnectionMonitorStorage"):
            with patch("app.modules.connection_monitor.collector.ProbeEngine"):
                from app.modules.connection_monitor.collector import ConnectionMonitorCollector
                config = MagicMock()
                config.get = MagicMock(side_effect=lambda k, d=None: cm_defaults.get(k, d))
                storage = MagicMock()
                storage.db_path = ":memory:"
                web = MagicMock()
                collector = ConnectionMonitorCollector(config_mgr=config, storage=storage, web=web)

        mock_engine = MagicMock()
        collector.set_smart_capture(mock_engine)

        # Simulate events from event_rules
        test_events = [
            {"timestamp": "2026-03-16T10:00:00Z", "severity": "warning",
             "event_type": "cm_packet_loss_warning", "message": "5% loss",
             "details": {"target_id": 1, "packet_loss_pct": 5.0, "window_seconds": 60}},
        ]
        collector._event_rules = MagicMock()
        collector._event_rules.check_probe_result.return_value = test_events
        collector._event_rules.check_window_stats.return_value = []

        # Mock core_storage to have save_events_with_ids
        collector._core_storage = MagicMock()
        collector._core_storage.save_events_with_ids = MagicMock()

        samples = [{"target_id": 1, "timeout": False}]
        collector._check_events(samples)

        # Verify save_events_with_ids was called (not save_events)
        collector._core_storage.save_events_with_ids.assert_called_once_with(test_events)
        # Verify evaluate was called with the same events
        mock_engine.evaluate.assert_called_once_with(test_events)
