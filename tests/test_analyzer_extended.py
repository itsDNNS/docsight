"""Tests for new analyzer functions: OFDMA, channel heatmap, before/after comparison."""

import pytest
from app.analyzer import (
    analyze_ofdma, build_channel_heatmap, compare_periods,
    _compute_ds_quality, _compute_us_quality, _quality_to_color,
    QAM_QUALITY,
)


# ── Helper factories ──

def _make_raw_data(ds30=None, ds31=None, us30=None, us31=None):
    return {
        "channelDs": {
            "docsis30": ds30 or [],
            "docsis31": ds31 or [],
        },
        "channelUs": {
            "docsis30": us30 or [],
            "docsis31": us31 or [],
        },
    }


def _ds_channel(ch_id=1, power=3.0, snr=35.0, mod="256QAM", corr=0, uncorr=0, ver="3.0"):
    return {
        "channel_id": ch_id, "frequency": "602 MHz", "power": power,
        "snr": snr, "modulation": mod, "health": "good",
        "correctable_errors": corr, "uncorrectable_errors": uncorr,
        "docsis_version": ver,
    }


def _us_channel(ch_id=1, power=42.0, mod="64QAM", ver="3.0"):
    return {
        "channel_id": ch_id, "frequency": "37 MHz", "power": power,
        "modulation": mod, "health": "good", "docsis_version": ver,
    }


def _analysis(ds=None, us=None, health="good"):
    return {
        "summary": {"health": health, "ds_total": len(ds or []), "us_total": len(us or [])},
        "ds_channels": ds or [],
        "us_channels": us or [],
    }


# ── QAM_QUALITY ──

class TestQamQuality:
    def test_4096qam_is_highest(self):
        assert QAM_QUALITY["4096QAM"] == 100

    def test_bpsk_is_lowest(self):
        assert QAM_QUALITY["BPSK"] == 5

    def test_256qam_mid_range(self):
        assert QAM_QUALITY["256QAM"] == 70


# ── OFDMA analysis ──

class TestAnalyzeOfdma:
    def test_no_ofdma(self):
        data = _make_raw_data(
            ds30=[{"channelID": 1}] * 24,
            us30=[{"channelID": 1}] * 4,
        )
        result = analyze_ofdma(data)
        assert result["ofdma_type"] == "none"
        assert result["has_ofdma_ds"] is False
        assert result["ds_31_count"] == 0
        assert result["ds_30_count"] == 24

    def test_wide_block(self):
        """All DS channels on DOCSIS 3.1 → wide_block."""
        data = _make_raw_data(ds31=[{"channelID": 1}] * 2)
        result = analyze_ofdma(data)
        assert result["ofdma_type"] == "wide_block"
        assert result["has_ofdma_ds"] is True

    def test_narrow_scqam(self):
        """Many DS30 + few DS31 → narrow_scqam (typical hybrid)."""
        data = _make_raw_data(
            ds30=[{"channelID": i} for i in range(24)],
            ds31=[{"channelID": 100}],
        )
        result = analyze_ofdma(data)
        assert result["ofdma_type"] == "narrow_scqam"

    def test_mixed(self):
        """Roughly equal DS30 and DS31 → mixed."""
        data = _make_raw_data(
            ds30=[{"channelID": i} for i in range(5)],
            ds31=[{"channelID": i + 100} for i in range(5)],
        )
        result = analyze_ofdma(data)
        assert result["ofdma_type"] == "mixed"

    def test_upstream_ofdma_detected(self):
        data = _make_raw_data(
            ds30=[{"channelID": 1}],
            us31=[{"channelID": 1}],
        )
        result = analyze_ofdma(data)
        assert result["has_ofdma_us"] is True
        assert result["us_31_count"] == 1

    def test_assessment_is_string(self):
        data = _make_raw_data(ds30=[{"channelID": 1}])
        result = analyze_ofdma(data)
        assert isinstance(result["assessment"], str)


# ── Channel Heatmap ──

class TestBuildChannelHeatmap:
    def test_basic_heatmap(self):
        analysis = _analysis(
            ds=[_ds_channel(1), _ds_channel(2, power=12.0, snr=22.0)],
            us=[_us_channel(1), _us_channel(2, power=56.0)],
        )
        heatmap = build_channel_heatmap(analysis)
        assert len(heatmap["ds"]) == 2
        assert len(heatmap["us"]) == 2

        # First channel should have high quality
        assert heatmap["ds"][0]["quality"] > 50
        assert heatmap["ds"][0]["color"] in ("green", "yellow")

        # Second channel should have lower quality (bad power + bad SNR)
        assert heatmap["ds"][1]["quality"] < heatmap["ds"][0]["quality"]

    def test_heatmap_fields(self):
        analysis = _analysis(ds=[_ds_channel(1)])
        heatmap = build_channel_heatmap(analysis)
        ch = heatmap["ds"][0]
        assert "channel_id" in ch
        assert "frequency" in ch
        assert "quality" in ch
        assert "color" in ch
        assert "modulation" in ch
        assert "power" in ch
        assert "docsis_version" in ch

    def test_empty_analysis(self):
        analysis = _analysis()
        heatmap = build_channel_heatmap(analysis)
        assert heatmap["ds"] == []
        assert heatmap["us"] == []

    def test_us_channel_heatmap_fields(self):
        analysis = _analysis(us=[_us_channel(1)])
        heatmap = build_channel_heatmap(analysis)
        ch = heatmap["us"][0]
        assert "channel_id" in ch
        assert "quality" in ch
        assert "color" in ch


# ── Quality computation ──

class TestDsQuality:
    def test_perfect_channel(self):
        ch = _ds_channel(power=0.5, snr=40.0, mod="4096QAM")
        assert _compute_ds_quality(ch) >= 90

    def test_bad_power(self):
        ch = _ds_channel(power=12.0, snr=35.0, mod="256QAM")
        assert _compute_ds_quality(ch) < 50

    def test_bad_snr(self):
        ch = _ds_channel(power=3.0, snr=22.0, mod="256QAM")
        assert _compute_ds_quality(ch) < 50

    def test_low_modulation(self):
        ch = _ds_channel(power=3.0, snr=35.0, mod="QPSK")
        q = _compute_ds_quality(ch)
        assert q < 30


class TestUsQuality:
    def test_perfect_us(self):
        ch = _us_channel(power=42.0, mod="64QAM")
        assert _compute_us_quality(ch) >= 30  # 64QAM = 40% quality

    def test_bad_us_power(self):
        ch = _us_channel(power=56.0, mod="64QAM")
        assert _compute_us_quality(ch) < _compute_us_quality(_us_channel())


class TestQualityToColor:
    def test_green(self):
        assert _quality_to_color(90) == "green"

    def test_yellow(self):
        assert _quality_to_color(70) == "yellow"

    def test_orange(self):
        assert _quality_to_color(50) == "orange"

    def test_red(self):
        assert _quality_to_color(30) == "red"


# ── Before/After Comparison ──

class TestComparePeriods:
    def _snapshot(self, power_max=5.0, snr_min=35.0, uncorr=100, health="good"):
        return {
            "summary": {
                "ds_power_min": -1.0,
                "ds_power_max": power_max,
                "ds_power_avg": 2.5,
                "us_power_min": 40.0,
                "us_power_max": 45.0,
                "us_power_avg": 42.5,
                "ds_snr_min": snr_min,
                "ds_snr_avg": 37.0,
                "ds_correctable_errors": 500,
                "ds_uncorrectable_errors": uncorr,
                "health": health,
            }
        }

    def test_equal_periods(self):
        snap = self._snapshot()
        result = compare_periods([snap], [snap])
        assert result["before"]["ds_power_max"] == result["after"]["ds_power_max"]
        for key, change in result["changes"].items():
            assert change["delta"] == 0

    def test_improvement_detected(self):
        before = [self._snapshot(power_max=8.0, snr_min=28.0, uncorr=5000)]
        after = [self._snapshot(power_max=4.0, snr_min=36.0, uncorr=50)]
        result = compare_periods(before, after)
        # SNR improved (higher = better)
        assert result["changes"]["ds_snr_min"]["improved"] is True
        # Uncorrectable errors decreased (lower = better)
        assert result["changes"]["ds_uncorrectable_errors"]["improved"] is True

    def test_degradation_detected(self):
        before = [self._snapshot(power_max=3.0, uncorr=10)]
        after = [self._snapshot(power_max=10.0, uncorr=5000)]
        result = compare_periods(before, after)
        assert result["changes"]["ds_power_max"]["improved"] is False
        assert result["changes"]["ds_uncorrectable_errors"]["improved"] is False

    def test_averaging(self):
        before = [
            self._snapshot(power_max=4.0),
            self._snapshot(power_max=6.0),
        ]
        result = compare_periods(before, [self._snapshot()])
        assert result["before"]["ds_power_max"] == 5.0

    def test_empty_before(self):
        result = compare_periods([], [self._snapshot()])
        assert result["before"] == {}
        assert result["changes"] == {}

    def test_empty_after(self):
        result = compare_periods([self._snapshot()], [])
        assert result["after"] == {}

    def test_health_distribution(self):
        snaps = [
            self._snapshot(health="good"),
            self._snapshot(health="good"),
            self._snapshot(health="marginal"),
        ]
        result = compare_periods(snaps, snaps)
        assert result["before"]["health_distribution"]["good"] == 2
        assert result["before"]["health_distribution"]["marginal"] == 1
