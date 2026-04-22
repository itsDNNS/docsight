"""Tests for analyzer threshold configuration and OFDMA handling."""

import pytest
from unittest.mock import patch
from app import analyzer

_TEST_THRESHOLDS = {
    "downstream_power": {
        "_default": "256QAM",
        "256QAM": {"good": [-4, 13], "warning": [-6, 18], "critical": [-8, 20]},
    },
    "upstream_power": {
        "_default": "sc_qam",
        "sc_qam": {"good": [41, 47], "warning": [37, 51], "critical": [35, 53]},
        "ofdma": {"good": [44, 47], "warning": [40, 48], "critical": [38, 50]},
    },
    "snr": {
        "_default": "256QAM",
        "256QAM": {"good_min": 33, "warning_min": 31, "critical_min": 30},
    },
    "upstream_modulation": {"critical_max_qam": 4, "warning_max_qam": 16},
    "errors": {"uncorrectable_pct": {"warning": 1.0, "critical": 3.0}},
}
from app.analyzer import analyze, _parse_float, _parse_qam_order, _resolve_modulation, _channel_bitrate_mbps, _metric_healths


# -- Helper to build FritzBox-style channel data --

def _make_ds30(channel_id=1, power=3.0, mse="-35.0", corr=0, uncorr=0):
    return {
        "channelID": channel_id,
        "frequency": "602 MHz",
        "powerLevel": str(power),
        "modulation": "256QAM",
        "mse": str(mse),
        "corrErrors": corr,
        "nonCorrErrors": uncorr,
    }


def _make_ds31(channel_id=100, power=5.0, mer="38.0", corr=0, uncorr=0):
    return {
        "channelID": channel_id,
        "frequency": "159 MHz",
        "powerLevel": str(power),
        "modulation": "4096QAM",
        "mer": str(mer),
        "corrErrors": corr,
        "nonCorrErrors": uncorr,
    }


def _make_us30(channel_id=1, power=42.0, modulation="64QAM"):
    return {
        "channelID": channel_id,
        "frequency": "37 MHz",
        "powerLevel": str(power),
        "modulation": modulation,
        "multiplex": "ATDMA",
    }


def _make_data(ds30=None, ds31=None, us30=None, us31=None):
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


# -- parse_float --

class TestSetThresholds:
    """Test dynamic threshold loading."""

    def setup_method(self):
        self._orig = analyzer._thresholds.copy()
        analyzer.set_thresholds(_TEST_THRESHOLDS)

    def teardown_method(self):
        analyzer._thresholds = self._orig

    def test_set_thresholds_updates_global(self):
        assert "downstream_power" in analyzer._thresholds
        assert analyzer._thresholds["downstream_power"]["256QAM"]["good"] == [-4, 13]

    def test_ds_power_getter_reads_array(self):
        t = analyzer._get_ds_power_thresholds("256QAM")
        assert t["good_min"] == -4
        assert t["good_max"] == 13
        assert t["crit_min"] == -8
        assert t["crit_max"] == 20

    def test_us_power_getter_sc_qam(self):
        t = analyzer._get_us_power_thresholds("sc_qam")
        assert t["good_min"] == 41
        assert t["good_max"] == 47

    def test_us_power_getter_ofdma(self):
        t = analyzer._get_us_power_thresholds("ofdma")
        assert t["good_min"] == 44
        assert t["good_max"] == 47

    def test_snr_getter_reads_new_keys(self):
        t = analyzer._get_snr_thresholds("256QAM")
        assert t["good_min"] == 33
        assert t["crit_min"] == 30

    def test_error_threshold_percent(self):
        t = analyzer._get_uncorr_thresholds()
        assert t["warning"] == 1.0
        assert t["critical"] == 3.0

    def test_fallback_when_empty(self):
        analyzer._thresholds = {}
        t = analyzer._get_ds_power_thresholds("256QAM")
        assert t["good_min"] == -4.0  # fallback value (Vodafone pNTP spec v1.06)


class TestOFDMAUpstream:
    """Test OFDMA upstream channel assessment."""

    def setup_method(self):
        self._orig = analyzer._thresholds.copy()
        analyzer.set_thresholds(_TEST_THRESHOLDS)

    def teardown_method(self):
        analyzer._thresholds = self._orig

    def test_ofdma_channel_threshold_classifications(self):
        cases = [
            {"label": "good", "power": "45.0", "expected": "good"},
            {"label": "tolerated", "power": "40.5", "expected": "tolerated"},
            {"label": "critical low", "power": "37.0", "expected": "critical"},
        ]

        for case in cases:
            ch = {"powerLevel": case["power"], "modulation": "OFDMA", "type": "OFDMA"}
            health, detail = analyzer._assess_us_channel(ch)
            assert health == case["expected"], case["label"]

    def test_sc_qam_still_uses_sc_qam_thresholds(self):
        ch = {"powerLevel": "42.0", "modulation": "64QAM", "type": "ATDMA"}
        health, detail = analyzer._assess_us_channel(ch)
        assert health == "good"

    def test_analyze_preserves_ofdma_profile_modulation(self):
        data = _make_data(
            us31=[{
                "channelID": 5,
                "frequency": "18.000 - 44.000",
                "powerLevel": "40.0",
                "modulation": "OFDMA",
                "profile_modulation": "128QAM",
                "type": "OFDMA",
                "multiplex": "OFDMA",
            }]
        )

        result = analyze(data)
        channel = result["us_channels"][0]
        assert channel["modulation"] == "OFDMA"
        assert channel["profile_modulation"] == "128QAM"
        assert channel["power_health"] == "tolerated"


class TestPercentErrors:
    """Test percent-based error thresholds."""

    def setup_method(self):
        self._orig = analyzer._thresholds.copy()
        analyzer.set_thresholds(_TEST_THRESHOLDS)

    def teardown_method(self):
        analyzer._thresholds = self._orig

    def test_no_errors_healthy(self):
        data = _make_data(ds30=[_make_ds30(1, corr=1000, uncorr=0)])
        result = analyze(data)
        assert "uncorr_errors_high" not in result["summary"]["health_issues"]
        assert "uncorr_errors_critical" not in result["summary"]["health_issues"]

    def test_percent_error_threshold_classifications(self):
        cases = [
            {
                "label": "warning threshold",
                "corr": 9900,
                "uncorr": 100,
                "expected_present": "uncorr_errors_high",
                "expected_absent": "uncorr_errors_critical",
            },
            {
                "label": "critical threshold",
                "corr": 9500,
                "uncorr": 500,
                "expected_present": "uncorr_errors_critical",
                "expected_absent": "uncorr_errors_high",
            },
        ]

        for case in cases:
            data = _make_data(ds30=[_make_ds30(1, corr=case["corr"], uncorr=case["uncorr"])])
            result = analyze(data)
            issues = result["summary"]["health_issues"]
            assert case["expected_present"] in issues, case["label"]
            assert case["expected_absent"] not in issues, case["label"]

    def test_percent_error_suppression_cases(self):
        cases = [
            {
                "label": "zero codewords",
                "corr": 0,
                "uncorr": 0,
                "expected_pct": None,
            },
            {
                "label": "below minimum codewords",
                "corr": 3,
                "uncorr": 3,
                "expected_pct": 0.0,
            },
        ]

        for case in cases:
            data = _make_data(ds30=[_make_ds30(1, corr=case["corr"], uncorr=case["uncorr"])])
            result = analyze(data)
            issues = result["summary"]["health_issues"]
            assert "uncorr_errors_high" not in issues, case["label"]
            assert "uncorr_errors_critical" not in issues, case["label"]
            if case["expected_pct"] is not None:
                assert result["summary"]["ds_uncorr_pct"] == case["expected_pct"], case["label"]

