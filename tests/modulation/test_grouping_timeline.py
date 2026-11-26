"""Tests for grouping, periods, timeline simplification, and degradation events."""

from app.modules.modulation.engine import (
    _modulation_periods,
    _channel_summary,
    _build_degraded_events,
    compute_intraday,
)
from tests.modulation.factories import make_channels, make_snapshot


# ── _modulation_periods ──

class TestModulationPeriods:
    def test_empty(self):
        assert _modulation_periods([]) == []

    def test_single_entry(self):
        timeline = [("10:00", "64QAM", 64)]
        periods = _modulation_periods(timeline)
        assert len(periods) == 1
        assert periods[0] == ("10:00", "10:00", "64QAM", 64, 1)

    def test_consecutive_same(self):
        timeline = [
            ("10:00", "64QAM", 64),
            ("10:15", "64QAM", 64),
            ("10:30", "64QAM", 64),
        ]
        periods = _modulation_periods(timeline)
        assert len(periods) == 1
        assert periods[0] == ("10:00", "10:30", "64QAM", 64, 3)

    def test_change_in_middle(self):
        timeline = [
            ("10:00", "64QAM", 64),
            ("10:15", "16QAM", 16),
            ("10:30", "16QAM", 16),
            ("10:45", "64QAM", 64),
        ]
        periods = _modulation_periods(timeline)
        assert len(periods) == 3
        assert periods[0] == ("10:00", "10:00", "64QAM", 64, 1)
        assert periods[1] == ("10:15", "10:30", "16QAM", 16, 2)
        assert periods[2] == ("10:45", "10:45", "64QAM", 64, 1)

    def test_every_entry_different(self):
        timeline = [
            ("10:00", "64QAM", 64),
            ("10:15", "16QAM", 16),
            ("10:30", "4QAM", 4),
        ]
        periods = _modulation_periods(timeline)
        assert len(periods) == 3


# ── intraday timeline ──

class TestIntradayTimeline:
    def test_keeps_only_modulation_changes(self):
        snaps = [
            make_snapshot(f"2026-03-01T10:{minute:02d}:00Z", us_channels=make_channels([modulation]))
            for minute, modulation in ((0, "64QAM"), (15, "64QAM"), (30, "16QAM"), (45, "16QAM"))
        ]
        channel = compute_intraday(snaps, "us", "UTC", "2026-03-01")["protocol_groups"][0]["channels"][0]
        assert channel["timeline"] == [
            {"time": "10:00", "modulation": "64QAM"},
            {"time": "10:30", "modulation": "16QAM"},
        ]
        assert channel["summary"] == "0.5h (50%) at 16QAM between 10:30\u201310:45"


# ── _channel_summary ──

class TestChannelSummary:
    def test_no_degradation(self):
        periods = [("10:00", "18:00", "64QAM", 64, 32)]
        assert _channel_summary(_build_degraded_events(periods, 16)) == ""

    def test_with_degradation(self):
        periods = [
            ("00:00", "13:45", "64QAM", 64, 56),
            ("14:00", "18:30", "16QAM", 16, 18),
            ("18:45", "18:45", "4QAM", 4, 1),
            ("19:00", "23:45", "64QAM", 64, 20),
        ]
        assert _channel_summary(_build_degraded_events(periods, 16)) == (
            "4.5h (19%) at 16QAM between 14:00\u201318:30; 0.2h (1%) at 4QAM around 18:45"
        )


# ── _build_degraded_events ──

class TestBuildDegradedEvents:
    def test_uses_clock_duration_for_multi_sample_window(self):
        periods = [
            ("01:06", "01:11", "16QAM", 16, 2),
            ("01:16", "01:26", "64QAM", 64, 4),
        ]
        events = _build_degraded_events(periods, 16)
        assert len(events) == 1
        assert events[0]["duration_minutes"] == 5
        assert events[0]["pct"] == 33
        assert events[0]["point_in_time"] is False

    def test_single_observation_stays_point_in_time(self):
        periods = [
            ("03:07", "03:07", "16QAM", 16, 1),
            ("03:12", "03:22", "64QAM", 64, 3),
        ]
        events = _build_degraded_events(periods, 16)
        assert len(events) == 1
        assert events[0]["duration_minutes"] == 0
        assert events[0]["point_in_time"] is True
