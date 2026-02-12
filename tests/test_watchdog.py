"""Tests for modulation watchdog, power drift, and ingress scoring."""

import time
import pytest
from unittest.mock import MagicMock

from app.watchdog import Watchdog, WatchdogEvent, QAM_ORDER, INGRESS_WEIGHTS


_DEFAULT_DS = [
    {"channel_id": 1, "frequency": "602 MHz", "power": 3.0,
     "snr": 35.0, "modulation": "256QAM", "health": "good",
     "correctable_errors": 0, "uncorrectable_errors": 0,
     "docsis_version": "3.0"},
]
_DEFAULT_US = [
    {"channel_id": 1, "frequency": "37 MHz", "power": 42.0,
     "modulation": "64QAM", "health": "good",
     "docsis_version": "3.0"},
]


def _make_analysis(ds_channels=None, us_channels=None, health="good",
                   ds_power_avg=3.0, us_power_avg=42.0, uncorr=0):
    """Build a minimal analysis dict for watchdog testing."""
    return {
        "summary": {
            "health": health,
            "ds_power_avg": ds_power_avg,
            "us_power_avg": us_power_avg,
            "ds_uncorrectable_errors": uncorr,
        },
        "ds_channels": _DEFAULT_DS if ds_channels is None else ds_channels,
        "us_channels": _DEFAULT_US if us_channels is None else us_channels,
    }


# ── QAM_ORDER sanity ──

class TestQamOrder:
    def test_4096qam_highest(self):
        assert QAM_ORDER["4096QAM"] > QAM_ORDER["256QAM"]

    def test_bpsk_lowest(self):
        assert QAM_ORDER["BPSK"] < QAM_ORDER["QPSK"]

    def test_common_order(self):
        assert QAM_ORDER["256QAM"] > QAM_ORDER["64QAM"] > QAM_ORDER["16QAM"]


# ── Modulation watchdog ──

class TestModulationWatchdog:
    def test_no_events_on_first_run(self):
        wd = Watchdog()
        events = wd.check(_make_analysis())
        assert events == []

    def test_no_event_on_stable_modulation(self):
        wd = Watchdog()
        wd.check(_make_analysis())  # baseline
        events = wd.check(_make_analysis())  # same
        assert events == []

    def test_ds_modulation_drop_detected(self):
        wd = Watchdog()
        # First run: 256QAM
        wd.check(_make_analysis(ds_channels=[
            {"channel_id": 3, "frequency": "650 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "256QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))
        # Second run: dropped to 64QAM
        events = wd.check(_make_analysis(ds_channels=[
            {"channel_id": 3, "frequency": "650 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "64QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))
        assert len(events) == 1
        assert events[0].event_type == "modulation_drop"
        assert events[0].direction == "ds"
        assert events[0].channel_id == 3
        assert "256QAM" in events[0].message
        assert "64QAM" in events[0].message

    def test_us_modulation_drop_detected(self):
        wd = Watchdog()
        wd.check(_make_analysis(us_channels=[
            {"channel_id": 1, "frequency": "37 MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"},
        ]))
        events = wd.check(_make_analysis(us_channels=[
            {"channel_id": 1, "frequency": "37 MHz", "power": 42.0,
             "modulation": "16QAM", "health": "good", "docsis_version": "3.0"},
        ]))
        assert len(events) == 1
        assert events[0].event_type == "modulation_drop"
        assert events[0].direction == "us"

    def test_modulation_upgrade_not_flagged(self):
        wd = Watchdog()
        wd.check(_make_analysis(ds_channels=[
            {"channel_id": 1, "frequency": "602 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "64QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))
        events = wd.check(_make_analysis(ds_channels=[
            {"channel_id": 1, "frequency": "602 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "256QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))
        assert events == []


# ── Channel count monitoring ──

class TestChannelCount:
    def test_no_event_first_run(self):
        wd = Watchdog()
        events = wd.check(_make_analysis(us_channels=[
            {"channel_id": i, "frequency": f"{37+i} MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"}
            for i in range(1, 5)
        ]))
        assert events == []

    def test_channel_drop_detected(self):
        wd = Watchdog()
        four_us = [
            {"channel_id": i, "frequency": f"{37+i} MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"}
            for i in range(1, 5)
        ]
        wd.check(_make_analysis(us_channels=four_us))

        two_us = four_us[:2]
        events = wd.check(_make_analysis(us_channels=two_us))
        drop_events = [e for e in events if e.event_type == "channel_count_drop"]
        assert len(drop_events) == 1
        assert drop_events[0].direction == "us"
        assert "4" in drop_events[0].message and "2" in drop_events[0].message

    def test_channel_drop_to_one_is_critical(self):
        wd = Watchdog()
        wd.check(_make_analysis(us_channels=[
            {"channel_id": i, "frequency": f"{37+i} MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"}
            for i in range(1, 4)
        ]))
        events = wd.check(_make_analysis(us_channels=[
            {"channel_id": 1, "frequency": "38 MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"},
        ]))
        drop_events = [e for e in events if e.event_type == "channel_count_drop"]
        assert drop_events[0].severity == "critical"

    def test_channel_count_stable(self):
        wd = Watchdog()
        us = [
            {"channel_id": i, "frequency": f"{37+i} MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"}
            for i in range(1, 3)
        ]
        wd.check(_make_analysis(us_channels=us))
        events = wd.check(_make_analysis(us_channels=us))
        drop_events = [e for e in events if e.event_type == "channel_count_drop"]
        assert drop_events == []


# ── Power drift ──

class TestPowerDrift:
    def test_no_drift_on_first_run(self):
        wd = Watchdog()
        events = wd.check(_make_analysis())
        drift_events = [e for e in events if e.event_type == "power_drift"]
        assert drift_events == []

    def test_drift_detected(self):
        wd = Watchdog()
        wd._drift_threshold_db = 2.0  # lower threshold for testing

        wd.check(_make_analysis(ds_power_avg=3.0, us_power_avg=42.0))
        events = wd.check(_make_analysis(ds_power_avg=6.0, us_power_avg=42.0))
        drift_events = [e for e in events if e.event_type == "power_drift"]
        assert len(drift_events) == 1
        assert "DS Power" in drift_events[0].message
        assert drift_events[0].details["drift_db"] == 3.0

    def test_no_drift_within_threshold(self):
        wd = Watchdog()
        wd._drift_threshold_db = 3.0

        wd.check(_make_analysis(ds_power_avg=3.0))
        events = wd.check(_make_analysis(ds_power_avg=5.0))
        drift_events = [e for e in events if e.event_type == "power_drift"]
        assert drift_events == []


# ── Ingress score ──

class TestIngressScore:
    def test_perfect_score(self):
        wd = Watchdog()
        analysis = _make_analysis(us_channels=[
            {"channel_id": i, "frequency": f"{37+i} MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"}
            for i in range(1, 5)
        ])
        wd.check(analysis)  # set baseline
        result = wd.compute_ingress_score(analysis)
        assert result["score"] >= 80
        assert result["health"] == "good"
        assert "power_score" in result["components"]
        assert "modulation_score" in result["components"]
        assert "channel_count_score" in result["components"]

    def test_poor_power_reduces_score(self):
        wd = Watchdog()
        analysis = _make_analysis(us_channels=[
            {"channel_id": 1, "frequency": "38 MHz", "power": 56.0,
             "modulation": "64QAM", "health": "poor", "docsis_version": "3.0"},
        ])
        wd.check(analysis)
        result = wd.compute_ingress_score(analysis)
        assert result["score"] < 80
        assert result["components"]["power_score"] < 50

    def test_low_modulation_reduces_score(self):
        wd = Watchdog()
        analysis = _make_analysis(us_channels=[
            {"channel_id": 1, "frequency": "38 MHz", "power": 42.0,
             "modulation": "QPSK", "health": "good", "docsis_version": "3.0"},
        ])
        wd.check(analysis)
        result = wd.compute_ingress_score(analysis)
        assert result["components"]["modulation_score"] < 50

    def test_no_us_channels_returns_perfect(self):
        wd = Watchdog()
        analysis = _make_analysis(us_channels=[])
        result = wd.compute_ingress_score(analysis)
        assert result["score"] == 100
        assert result["health"] == "good"
        assert result["components"] == {}

    def test_channel_drop_reduces_score(self):
        wd = Watchdog()
        us4 = [
            {"channel_id": i, "frequency": f"{37+i} MHz", "power": 42.0,
             "modulation": "64QAM", "health": "good", "docsis_version": "3.0"}
            for i in range(1, 5)
        ]
        wd.check(_make_analysis(us_channels=us4))  # baseline = 4

        us2 = us4[:2]
        result = wd.compute_ingress_score(_make_analysis(us_channels=us2))
        assert result["components"]["channel_count_score"] < 100


# ── Adaptive polling ──

class TestAdaptivePolling:
    def test_good_health_no_change(self):
        wd = Watchdog()
        analysis = _make_analysis(health="good", uncorr=0)
        interval = wd.get_adaptive_poll_interval(analysis, 900)
        assert interval == 900

    def test_poor_health_reduces_interval(self):
        wd = Watchdog()
        analysis = _make_analysis(health="poor", uncorr=100000)
        interval = wd.get_adaptive_poll_interval(analysis, 900)
        assert interval < 900
        assert interval >= 30

    def test_marginal_health_moderate_reduction(self):
        wd = Watchdog()
        analysis = _make_analysis(health="marginal", uncorr=15000)
        interval = wd.get_adaptive_poll_interval(analysis, 900)
        assert 30 < interval < 900

    def test_high_errors_triggers_fast_polling(self):
        wd = Watchdog()
        analysis = _make_analysis(health="good", uncorr=60000)
        interval = wd.get_adaptive_poll_interval(analysis, 900)
        assert interval <= 60


# ── Event persistence ──

class TestWatchdogPersistence:
    def test_events_saved_to_storage(self):
        storage = MagicMock()
        wd = Watchdog(storage=storage)

        # Set baseline
        wd.check(_make_analysis(ds_channels=[
            {"channel_id": 1, "frequency": "602 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "256QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))

        # Trigger modulation drop
        wd.check(_make_analysis(ds_channels=[
            {"channel_id": 1, "frequency": "602 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "64QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))

        storage.save_watchdog_event.assert_called_once()
        event_dict = storage.save_watchdog_event.call_args[0][0]
        assert event_dict["event_type"] == "modulation_drop"

    def test_notifier_called_on_event(self):
        notifier = MagicMock()
        notifier.is_configured.return_value = True
        wd = Watchdog(notifier=notifier)

        wd.check(_make_analysis(ds_channels=[
            {"channel_id": 1, "frequency": "602 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "256QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))
        wd.check(_make_analysis(ds_channels=[
            {"channel_id": 1, "frequency": "602 MHz", "power": 3.0,
             "snr": 35.0, "modulation": "64QAM", "health": "good",
             "correctable_errors": 0, "uncorrectable_errors": 0,
             "docsis_version": "3.0"},
        ]))

        notifier.send.assert_called_once()


# ── WatchdogEvent dataclass ──

class TestWatchdogEvent:
    def test_fields(self):
        evt = WatchdogEvent(
            timestamp="2026-01-01T00:00:00",
            event_type="modulation_drop",
            channel_id=3,
            direction="ds",
            message="Test",
            severity="warning",
        )
        assert evt.timestamp == "2026-01-01T00:00:00"
        assert evt.details == {}

    def test_asdict(self):
        from dataclasses import asdict
        evt = WatchdogEvent(
            timestamp="now", event_type="test", channel_id=None,
            direction=None, message="m", severity="info",
            details={"key": "val"},
        )
        d = asdict(evt)
        assert d["details"] == {"key": "val"}
