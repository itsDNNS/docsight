"""Tests for the modulation performance engine (v2)."""

import math

import pytest

from app.modules.modulation.engine import (
    _parse_qam_order,
    _canonical_label,
    _distribution_pct,
    _health_index,
    _health_index_for_group,
    _low_qam_pct,
    _group_channels_by_protocol,
    _modulation_periods,
    _simplify_timeline,
    _channel_summary,
    compute_distribution,
    compute_distribution_v2,
    compute_intraday,
    compute_trend,
    MAX_QAM,
    DISCLAIMER,
)


# ── _parse_qam_order ──

class TestParseQamOrder:
    def test_qpsk(self):
        assert _parse_qam_order("QPSK") == 4

    def test_numeric_qam(self):
        assert _parse_qam_order("64QAM") == 64
        assert _parse_qam_order("256-QAM") == 256
        assert _parse_qam_order("16 QAM") == 16

    def test_4096qam(self):
        assert _parse_qam_order("4096QAM") == 4096

    def test_ofdm_returns_none(self):
        assert _parse_qam_order("OFDM") is None
        assert _parse_qam_order("OFDMA") is None

    def test_empty_returns_none(self):
        assert _parse_qam_order("") is None
        assert _parse_qam_order(None) is None

    def test_unknown_returns_none(self):
        assert _parse_qam_order("something_weird") is None

    def test_case_insensitive(self):
        assert _parse_qam_order("qpsk") == 4
        assert _parse_qam_order("64qam") == 64

    def test_8qam(self):
        assert _parse_qam_order("8QAM") == 8

    def test_32qam(self):
        assert _parse_qam_order("32QAM") == 32

    def test_1024qam(self):
        assert _parse_qam_order("1024QAM") == 1024

    @pytest.mark.parametrize("value", ["64-QAM", "64 QAM", "64QAM", "64qam"])
    def test_various_64qam_formats(self, value):
        assert _parse_qam_order(value) == 64


# ── _canonical_label ──

class TestCanonicalLabel:
    def test_qpsk(self):
        assert _canonical_label("QPSK") == ("QPSK", 4)

    def test_numeric_qam(self):
        assert _canonical_label("64QAM") == ("64QAM", 64)
        assert _canonical_label("256-QAM") == ("256QAM", 256)

    def test_ofdm(self):
        assert _canonical_label("OFDM") == ("OFDM", None)
        assert _canonical_label("OFDMA") == ("OFDMA", None)

    def test_empty(self):
        assert _canonical_label("") == ("Unknown", None)
        assert _canonical_label(None) == ("Unknown", None)

    def test_1024qam_label(self):
        assert _canonical_label("1024QAM") == ("1024QAM", 1024)

    def test_4096qam_label(self):
        assert _canonical_label("4096QAM") == ("4096QAM", 4096)

    def test_hyphenated(self):
        label, qam = _canonical_label("256-QAM")
        assert label == "256QAM"
        assert qam == 256


# ── _distribution_pct ──

class TestDistributionPct:
    def test_empty(self):
        assert _distribution_pct([]) == {}

    def test_all_same(self):
        obs = [("64QAM", 64)] * 10
        result = _distribution_pct(obs)
        assert result == {"64QAM": 100.0}

    def test_mixed(self):
        obs = [("QPSK", 4)] * 1 + [("64QAM", 64)] * 3
        result = _distribution_pct(obs)
        assert result["QPSK"] == 25.0
        assert result["64QAM"] == 75.0

    def test_percentages_sum_to_100(self):
        obs = [("QPSK", 4)] * 3 + [("16QAM", 16)] * 3 + [("256QAM", 256)] * 4
        result = _distribution_pct(obs)
        assert abs(sum(result.values()) - 100.0) < 0.5

    def test_many_modulation_types(self):
        obs = [("QPSK", 4), ("16QAM", 16), ("64QAM", 64),
               ("256QAM", 256), ("OFDM", None)]
        result = _distribution_pct(obs)
        assert len(result) == 5
        assert result["QPSK"] == 20.0

    def test_single_observation(self):
        obs = [("64QAM", 64)]
        result = _distribution_pct(obs)
        assert result == {"64QAM": 100.0}


# ── _health_index (legacy global scale) ──

class TestHealthIndex:
    def test_no_observations(self):
        assert _health_index([]) is None

    def test_ofdm_only_returns_none(self):
        obs = [("OFDM", None), ("OFDMA", None)]
        assert _health_index(obs) is None

    def test_all_qpsk_is_zero(self):
        obs = [("QPSK", 4)] * 10
        assert _health_index(obs) == 0.0

    def test_all_4096qam_is_100(self):
        obs = [("4096QAM", 4096)] * 10
        assert _health_index(obs) == 100.0

    def test_all_256qam(self):
        obs = [("256QAM", 256)] * 10
        assert _health_index(obs) == 60.0

    def test_mixed_ignores_ofdm(self):
        obs = [("256QAM", 256)] * 5 + [("OFDM", None)] * 5
        assert _health_index(obs) == 60.0

    def test_clamped_at_boundaries(self):
        obs = [("QPSK", 4)]
        assert _health_index(obs) >= 0

    def test_all_64qam(self):
        obs = [("64QAM", 64)] * 10
        assert _health_index(obs) == 40.0

    def test_mixed_qam_weighted_average(self):
        obs = [("QPSK", 4)] * 5 + [("256QAM", 256)] * 5
        assert _health_index(obs) == 30.0

    def test_health_index_range(self):
        for qam in [4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]:
            obs = [(f"{qam}QAM", qam)] * 5
            hi = _health_index(obs)
            assert 0 <= hi <= 100, f"QAM {qam} produced health_index {hi}"

    def test_single_observation(self):
        obs = [("256QAM", 256)]
        assert _health_index(obs) == 60.0

    def test_monotonically_increasing(self):
        qam_orders = [4, 16, 64, 256, 1024, 4096]
        indices = []
        for qam in qam_orders:
            obs = [(f"{qam}QAM", qam)] * 10
            indices.append(_health_index(obs))
        for i in range(1, len(indices)):
            assert indices[i] > indices[i - 1]


# ── _health_index_for_group (per-protocol scaling) ──

class TestHealthIndexForGroup:
    def test_us_30_at_64qam_is_100(self):
        obs = [("64QAM", 64)] * 10
        assert _health_index_for_group(obs, "us", "3.0") == 100.0

    def test_ds_30_at_256qam_is_100(self):
        obs = [("256QAM", 256)] * 10
        assert _health_index_for_group(obs, "ds", "3.0") == 100.0

    def test_ds_31_at_4096qam_is_100(self):
        obs = [("4096QAM", 4096)] * 10
        assert _health_index_for_group(obs, "ds", "3.1") == 100.0

    def test_us_31_at_1024qam_is_100(self):
        obs = [("1024QAM", 1024)] * 10
        assert _health_index_for_group(obs, "us", "3.1") == 100.0

    def test_us_30_at_qpsk_is_zero(self):
        obs = [("QPSK", 4)] * 10
        assert _health_index_for_group(obs, "us", "3.0") == 0.0

    def test_ds_30_at_qpsk_is_zero(self):
        obs = [("QPSK", 4)] * 10
        assert _health_index_for_group(obs, "ds", "3.0") == 0.0

    def test_us_30_at_16qam_partial(self):
        # log2(16)=4, max=64→log2=6, index = 100*(4-2)/(6-2) = 50
        obs = [("16QAM", 16)] * 10
        assert _health_index_for_group(obs, "us", "3.0") == 50.0

    def test_ds_30_at_64qam_partial(self):
        # log2(64)=6, max=256→log2=8, index = 100*(6-2)/(8-2) = 66.7
        obs = [("64QAM", 64)] * 10
        assert _health_index_for_group(obs, "ds", "3.0") == 66.7

    def test_no_numeric_returns_none(self):
        obs = [("OFDM", None)] * 5
        assert _health_index_for_group(obs, "ds", "3.1") is None

    def test_empty_returns_none(self):
        assert _health_index_for_group([], "us", "3.0") is None

    def test_mixed_qam_us_30(self):
        # 50% QPSK (log2=2) + 50% 64QAM (log2=6) → avg=4 → 100*(4-2)/(6-2) = 50.0
        obs = [("QPSK", 4)] * 5 + [("64QAM", 64)] * 5
        assert _health_index_for_group(obs, "us", "3.0") == 50.0


# ── _low_qam_pct ──

class TestLowQamPct:
    def test_no_observations(self):
        assert _low_qam_pct([], 16) == 0

    def test_all_low(self):
        obs = [("QPSK", 4)] * 10
        assert _low_qam_pct(obs, 16) == 100.0

    def test_none_low(self):
        obs = [("256QAM", 256)] * 10
        assert _low_qam_pct(obs, 16) == 0.0

    def test_mixed(self):
        obs = [("QPSK", 4)] * 2 + [("256QAM", 256)] * 8
        assert _low_qam_pct(obs, 16) == 20.0

    def test_threshold_boundary(self):
        obs = [("16QAM", 16)] * 5 + [("64QAM", 64)] * 5
        assert _low_qam_pct(obs, 16) == 50.0

    def test_ignores_ofdm(self):
        obs = [("QPSK", 4)] * 1 + [("64QAM", 64)] * 1 + [("OFDM", None)] * 8
        assert _low_qam_pct(obs, 16) == 50.0

    def test_custom_threshold_64(self):
        obs = [("16QAM", 16)] * 3 + [("64QAM", 64)] * 2 + [("256QAM", 256)] * 5
        assert _low_qam_pct(obs, 64) == 50.0

    def test_ofdm_only_returns_zero(self):
        obs = [("OFDM", None)] * 10
        assert _low_qam_pct(obs, 16) == 0


# ── _group_channels_by_protocol ──

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
            ("10:30", "QPSK", 4),
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


class TestComputeDistributionV2:
    def test_empty_snapshots(self):
        result = compute_distribution_v2([], "us", "UTC")
        assert result["sample_count"] == 0
        assert result["protocol_groups"] == []
        assert result["aggregate"]["health_index"] is None
        assert result["disclaimer"] == DISCLAIMER

    def test_single_protocol_group(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "64QAM", "64QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        assert len(result["protocol_groups"]) == 1
        pg = result["protocol_groups"][0]
        assert pg["docsis_version"] == "3.0"
        assert pg["max_qam"] == "64QAM"
        assert pg["health_index"] == 100.0  # US 3.0 at 64QAM = max
        assert pg["channel_count"] == 4

    def test_mixed_protocol_groups(self):
        us_channels = (
            _make_channels(["64QAM", "64QAM"], docsis_version="3.0") +
            _make_channels(["1024QAM"], docsis_version="3.1")
        )
        # Fix channel_ids to be unique
        for i, ch in enumerate(us_channels):
            ch["channel_id"] = i
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_distribution_v2(snaps, "us", "UTC")
        assert len(result["protocol_groups"]) == 2
        versions = [pg["docsis_version"] for pg in result["protocol_groups"]]
        assert "3.0" in versions
        assert "3.1" in versions

    def test_per_day_data(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["64QAM"])),
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert len(pg["days"]) == 2
        assert pg["days"][0]["date"] == "2026-03-01"
        assert pg["days"][1]["date"] == "2026-03-02"

    def test_health_index_us30_correct(self):
        """US 3.0 at 64QAM should be 100, not the old 40."""
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "64QAM", "64QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["health_index"] == 100.0

    def test_health_index_ds30_correct(self):
        """DS 3.0 at 256QAM should be 100."""
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                ds_channels=_make_channels(["256QAM", "256QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "ds", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["health_index"] == 100.0

    def test_degraded_channel_count(self):
        us_channels = [
            {"channel_id": 1, "modulation": "64QAM", "docsis_version": "3.0"},
            {"channel_id": 2, "modulation": "64QAM", "docsis_version": "3.0"},
            {"channel_id": 3, "modulation": "16QAM", "docsis_version": "3.0"},
        ]
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["degraded_channel_count"] == 1  # Ch 3 at 16QAM < 64QAM

    def test_dominant_modulation(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "16QAM"]),
            )
        ]
        result = compute_distribution_v2(snaps, "us", "UTC")
        pg = result["protocol_groups"][0]
        assert pg["dominant_modulation"] == "64QAM"

    def test_sample_density(self):
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"]))]
        result = compute_distribution_v2(snaps, "us", "UTC")
        assert result["expected_samples"] == 96
        assert result["sample_count"] == 1
        assert result["sample_density"] == 0.01

    def test_disclaimer_present(self):
        result = compute_distribution_v2([], "us", "UTC")
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 0


class TestComputeIntraday:
    def test_empty(self):
        result = compute_intraday([], "us", "UTC", "2026-03-01")
        assert result["protocol_groups"] == []
        assert result["date"] == "2026-03-01"
        assert result["disclaimer"] == DISCLAIMER

    def test_single_channel_timeline(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
            _make_snapshot("2026-03-01T14:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "16QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
            _make_snapshot("2026-03-01T18:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        assert len(result["protocol_groups"]) == 1
        pg = result["protocol_groups"][0]
        assert pg["docsis_version"] == "3.0"
        ch = pg["channels"][0]
        assert ch["channel_id"] == 1
        assert ch["degraded"] is True
        assert len(ch["timeline"]) == 3  # 3 transitions: 64→16→64
        assert ch["summary"] != ""  # Should mention 16QAM degradation

    def test_filters_by_date(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
            _make_snapshot("2026-03-02T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        pg = result["protocol_groups"][0]
        ch = pg["channels"][0]
        assert len(ch["timeline"]) == 1  # Only 1 snapshot on March 1

    def test_not_degraded_channel(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z",
                           us_channels=[{"channel_id": 1, "modulation": "64QAM",
                                         "docsis_version": "3.0", "frequency": "51.000"}]),
        ]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        ch = result["protocol_groups"][0]["channels"][0]
        assert ch["degraded"] is False
        assert ch["health_index"] == 100.0
        assert ch["summary"] == ""

    def test_multi_protocol_groups(self):
        us_channels = [
            {"channel_id": 1, "modulation": "64QAM", "docsis_version": "3.0", "frequency": "51.000"},
            {"channel_id": 10, "modulation": "1024QAM", "docsis_version": "3.1", "frequency": "100.000"},
        ]
        snaps = [_make_snapshot("2026-03-01T10:00:00Z", us_channels=us_channels)]
        result = compute_intraday(snaps, "us", "UTC", "2026-03-01")
        assert len(result["protocol_groups"]) == 2


# ── Legacy compute_distribution (v1 compat) ──

class TestComputeDistribution:
    def test_empty_snapshots(self):
        result = compute_distribution([], "us", "UTC")
        assert result["sample_count"] == 0
        assert result["days"] == []
        assert result["aggregate"]["health_index"] is None
        assert result["aggregate"]["distribution"] == {}

    def test_single_day_single_snapshot(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                us_channels=_make_channels(["64QAM", "64QAM", "QPSK", "64QAM"]),
            )
        ]
        result = compute_distribution(snaps, "us", "UTC")
        assert len(result["days"]) == 1
        day = result["days"][0]
        assert day["date"] == "2026-03-01"

    def test_multi_day_grouping(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-01T14:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["QPSK"])),
        ]
        result = compute_distribution(snaps, "us", "UTC")
        assert len(result["days"]) == 2
        assert result["days"][0]["date"] == "2026-03-01"
        assert result["days"][1]["date"] == "2026-03-02"

    def test_downstream_channels(self):
        snaps = [
            _make_snapshot(
                "2026-03-01T10:00:00Z",
                ds_channels=_make_channels(["256QAM", "256QAM"]),
                us_channels=_make_channels(["QPSK"]),
            )
        ]
        result = compute_distribution(snaps, "ds", "UTC")
        assert "256QAM" in result["aggregate"]["distribution"]
        assert "QPSK" not in result["aggregate"]["distribution"]

    def test_direction_field_in_result(self):
        result = compute_distribution([], "ds", "UTC")
        assert result["direction"] == "ds"

    def test_low_qam_threshold_in_result(self):
        result = compute_distribution([], "us", "UTC", low_qam_threshold=32)
        assert result["low_qam_threshold"] == 32

    def test_date_range_correct(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-05T10:00:00Z", us_channels=_make_channels(["64QAM"])),
        ]
        result = compute_distribution(snaps, "us", "UTC")
        assert result["date_range"]["start"] == "2026-03-01"
        assert result["date_range"]["end"] == "2026-03-05"

    def test_density_capped_at_1(self):
        snaps = [
            _make_snapshot(f"2026-03-01T{i:02d}:00:00Z", us_channels=_make_channels(["64QAM"]))
            for i in range(24)
        ] * 5
        result = compute_distribution(snaps, "us", "UTC")
        assert result["sample_density"] == 1.0


# ── compute_trend ──

class TestComputeTrend:
    def test_returns_per_day_data(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM", "QPSK"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["256QAM"])),
        ]
        trend = compute_trend(snaps, "us", "UTC")
        assert len(trend) == 2
        assert trend[0]["date"] == "2026-03-01"
        assert trend[0]["health_index"] is not None
        assert trend[0]["dominant_modulation"] is not None

    def test_empty(self):
        trend = compute_trend([], "us", "UTC")
        assert trend == []

    def test_trend_fields_present(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
        ]
        trend = compute_trend(snaps, "us", "UTC")
        assert len(trend) == 1
        entry = trend[0]
        assert "date" in entry
        assert "health_index" in entry
        assert "low_qam_pct" in entry
        assert "dominant_modulation" in entry
        assert "sample_count" in entry

    def test_trend_multi_day_order(self):
        snaps = [
            _make_snapshot("2026-03-03T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["QPSK"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["256QAM"])),
        ]
        trend = compute_trend(snaps, "us", "UTC")
        dates = [t["date"] for t in trend]
        assert dates == sorted(dates)
