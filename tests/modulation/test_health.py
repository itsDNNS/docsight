"""Tests for modulation parsing and health classification."""

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
    _low_qam_pct,
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

class TestParseQamOrder:
    def test_qpsk(self):
        assert _parse_qam_order("4QAM") == 4

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
        assert _canonical_label("4QAM") == ("4QAM", 4)

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
        obs = [("4QAM", 4)] * 1 + [("64QAM", 64)] * 3
        result = _distribution_pct(obs)
        assert result["4QAM"] == 25.0
        assert result["64QAM"] == 75.0

    def test_percentages_sum_to_100(self):
        obs = [("4QAM", 4)] * 3 + [("16QAM", 16)] * 3 + [("256QAM", 256)] * 4
        result = _distribution_pct(obs)
        assert abs(sum(result.values()) - 100.0) < 0.5

    def test_many_modulation_types(self):
        obs = [("4QAM", 4), ("16QAM", 16), ("64QAM", 64),
               ("256QAM", 256), ("OFDM", None)]
        result = _distribution_pct(obs)
        assert len(result) == 5
        assert result["4QAM"] == 20.0

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
        obs = [("4QAM", 4)] * 10
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
        obs = [("4QAM", 4)]
        assert _health_index(obs) >= 0

    def test_all_64qam(self):
        obs = [("64QAM", 64)] * 10
        assert _health_index(obs) == 40.0

    def test_mixed_qam_weighted_average(self):
        obs = [("4QAM", 4)] * 5 + [("256QAM", 256)] * 5
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
        obs = [("4QAM", 4)] * 10
        assert _health_index_for_group(obs, "us", "3.0") == 0.0

    def test_ds_30_at_qpsk_is_zero(self):
        obs = [("4QAM", 4)] * 10
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
        # 50% 4QAM (log2=2) + 50% 64QAM (log2=6) → avg=4 → 100*(4-2)/(6-2) = 50.0
        obs = [("4QAM", 4)] * 5 + [("64QAM", 64)] * 5
        assert _health_index_for_group(obs, "us", "3.0") == 50.0


class TestDegradedThresholds:
    def test_default_threshold_unchanged(self):
        assert _degraded_qam_threshold("us", "3.0", 16) == 16
        assert _degraded_qam_threshold("ds", "3.0", 16) == 16

    def test_us31_uses_64qam_threshold(self):
        assert _degraded_qam_threshold("us", "3.1", 16) == 64


# ── _low_qam_pct ──

class TestLowQamPct:
    def test_no_observations(self):
        assert _low_qam_pct([], 16) == 0

    def test_all_low(self):
        obs = [("4QAM", 4)] * 10
        assert _low_qam_pct(obs, 16) == 100.0

    def test_none_low(self):
        obs = [("256QAM", 256)] * 10
        assert _low_qam_pct(obs, 16) == 0.0

    def test_mixed(self):
        obs = [("4QAM", 4)] * 2 + [("256QAM", 256)] * 8
        assert _low_qam_pct(obs, 16) == 20.0

    def test_threshold_boundary(self):
        obs = [("16QAM", 16)] * 5 + [("64QAM", 64)] * 5
        assert _low_qam_pct(obs, 16) == 50.0


    def test_threshold_64_excludes_128qam(self):
        obs = [("64QAM", 64)] * 4 + [("128QAM", 128)] * 6
        assert _low_qam_pct(obs, 64) == 40.0

    def test_ignores_ofdm(self):
        obs = [("4QAM", 4)] * 1 + [("64QAM", 64)] * 1 + [("OFDM", None)] * 8
        assert _low_qam_pct(obs, 16) == 50.0

    def test_custom_threshold_64(self):
        obs = [("16QAM", 16)] * 3 + [("64QAM", 64)] * 2 + [("256QAM", 256)] * 5
        assert _low_qam_pct(obs, 64) == 50.0

    def test_ofdm_only_returns_zero(self):
        obs = [("OFDM", None)] * 10
        assert _low_qam_pct(obs, 16) == 0


# ── _group_channels_by_protocol ──
