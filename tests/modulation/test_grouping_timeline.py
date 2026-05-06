"""Tests for grouping, periods, timeline simplification, and degradation events."""

"""Tests for the modulation performance engine (v2)."""

import math

import pytest

from app.modules.modulation.engine import (
    _parse_qam_order,
    _canonical_label,
    _distribution_pct,
    _degraded_qam_threshold,
    _health_index,
    _health_index_for_group,
    _numeric_low_qam_pct,
    _group_channels_by_protocol,
    _modulation_periods,
    _simplify_timeline,
    _channel_summary,
    _build_degraded_events,
    compute_distribution,
    compute_distribution_v2,
    compute_intraday,
    compute_trend,
    MAX_QAM,
    DISCLAIMER,
)


# ── _parse_qam_order ──

class TestGroupChannelsByProtocol:
    def test_single_version(self):
        channels = [
            {"channel_id": 1, "docsis_version": "3.0"},
            {"channel_id": 2, "docsis_version": "3.0"},
        ]
        result = _group_channels_by_protocol(channels)
        assert list(result.keys()) == ["3.0"]
        assert len(result["3.0"]) == 2

    def test_mixed_versions(self):
        channels = [
            {"channel_id": 1, "docsis_version": "3.0"},
            {"channel_id": 2, "docsis_version": "3.1"},
            {"channel_id": 3, "docsis_version": "3.0"},
        ]
        result = _group_channels_by_protocol(channels)
        assert len(result["3.0"]) == 2
        assert len(result["3.1"]) == 1

    def test_missing_version_defaults_to_30(self):
        channels = [{"channel_id": 1}]
        result = _group_channels_by_protocol(channels)
        assert "3.0" in result

    def test_empty(self):
        assert _group_channels_by_protocol([]) == {}


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


# ── _simplify_timeline ──

class TestSimplifyTimeline:
    def test_empty(self):
        assert _simplify_timeline([]) == []

    def test_no_changes(self):
        timeline = [("10:00", "64QAM", 64), ("10:15", "64QAM", 64)]
        result = _simplify_timeline(timeline)
        assert result == [("10:00", "64QAM")]

    def test_one_change(self):
        timeline = [
            ("10:00", "64QAM", 64),
            ("10:15", "64QAM", 64),
            ("10:30", "16QAM", 16),
            ("10:45", "16QAM", 16),
        ]
        result = _simplify_timeline(timeline)
        assert result == [("10:00", "64QAM"), ("10:30", "16QAM")]


# ── _channel_summary ──

class TestChannelSummary:
    def test_no_degradation(self):
        periods = [("10:00", "18:00", "64QAM", 64, 32)]
        assert _channel_summary(periods, 64) == ""

    def test_with_degradation(self):
        periods = [
            ("00:00", "13:45", "64QAM", 64, 56),
            ("14:00", "18:30", "16QAM", 16, 18),
            ("18:45", "23:45", "64QAM", 64, 20),
        ]
        summary = _channel_summary(periods, 64)
        assert "16QAM" in summary
        assert "14:00" in summary
        assert "18:30" in summary


# ── compute_distribution_v2 ──

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


def _make_snapshot(timestamp, us_channels=None, ds_channels=None):
    return {
        "timestamp": timestamp,
        "us_channels": us_channels or [],
        "ds_channels": ds_channels or [],
        "summary": {},
    }


def _make_channels(modulations, docsis_version="3.0"):
    return [
        {"modulation": m, "channel_id": i, "docsis_version": docsis_version}
        for i, m in enumerate(modulations)
    ]

