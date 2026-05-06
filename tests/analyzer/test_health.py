"""Tests for analyzer health classification and summary behavior."""

import pytest
from unittest.mock import patch
from app import analyzer
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

class TestParseFloat:
    def test_normal(self):
        assert _parse_float("3.5") == 3.5

    def test_negative(self):
        assert _parse_float("-7.2") == -7.2

    def test_none(self):
        assert _parse_float(None) == 0.0

    def test_empty_string(self):
        assert _parse_float("") == 0.0

    def test_custom_default(self):
        assert _parse_float("bad", default=-1.0) == -1.0


# -- Health assessment: good --

class TestHealthGood:
    def test_all_normal(self):
        data = _make_data(
            ds30=[_make_ds30(i, power=2.0, mse="-35") for i in range(1, 4)],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "good"
        assert result["summary"]["health_issues"] == []

    def test_power_at_boundary(self):
        """Power exactly at 13.0 is still good (VFKD regelkonform)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=13.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "good"


# -- Health assessment: tolerated --

class TestHealthTolerated:
    def test_threshold_classifications(self):
        cases = [
            {
                "label": "ds power tolerated",
                "expected_issue": "ds_power_tolerated",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=15.0, mse="-35")],
                    us30=[_make_us30(1, power=44.0)],
                ),
            },
            {
                "label": "ds power tolerated low",
                "expected_issue": "ds_power_tolerated",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=-5.0, mse="-35")],
                    us30=[_make_us30(1, power=44.0)],
                ),
            },
            {
                "label": "us power tolerated high",
                "expected_issue": "us_power_tolerated_high",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-35")],
                    us30=[_make_us30(1, power=49.0)],
                ),
            },
            {
                "label": "us power tolerated low",
                "expected_issue": "us_power_tolerated_low",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-35")],
                    us30=[_make_us30(1, power=40.0)],
                ),
            },
            {
                "label": "snr tolerated",
                "expected_issue": "snr_tolerated",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-31")],
                    us30=[_make_us30(1, power=42.0)],
                ),
            },
        ]

        for case in cases:
            result = analyze(case["data"])
            assert result["summary"]["health"] == "tolerated", case["label"]
            assert case["expected_issue"] in result["summary"]["health_issues"], case["label"]


# -- Health assessment: marginal --

class TestHealthMarginal:
    def test_threshold_classifications(self):
        cases = [
            {
                "label": "ds power marginal",
                "expected_issue": "ds_power_marginal",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=15.5, mse="-35")],
                    us30=[_make_us30(1, power=44.0)],
                ),
            },
            {
                "label": "ds power marginal low",
                "expected_issue": "ds_power_marginal",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=-6.5, mse="-35")],
                    us30=[_make_us30(1, power=44.0)],
                ),
            },
            {
                "label": "us power marginal high",
                "expected_issue": "us_power_marginal_high",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-35")],
                    us30=[_make_us30(1, power=52.0)],
                ),
            },
            {
                "label": "us power marginal low",
                "expected_issue": "us_power_marginal_low",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-35")],
                    us30=[_make_us30(1, power=36.0)],
                ),
            },
            {
                "label": "snr marginal",
                "expected_issue": "snr_marginal",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-30.5")],
                    us30=[_make_us30(1, power=42.0)],
                ),
            },
        ]

        for case in cases:
            result = analyze(case["data"])
            assert result["summary"]["health"] == "marginal", case["label"]
            assert case["expected_issue"] in result["summary"]["health_issues"], case["label"]


# -- Health assessment: critical --

class TestHealthCritical:
    def test_threshold_classifications(self):
        cases = [
            {
                "label": "ds power critical high",
                "expected_issue": "ds_power_critical",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=21.0, mse="-35")],
                    us30=[_make_us30(1, power=44.0)],
                ),
            },
            {
                "label": "ds power critical low",
                "expected_issue": "ds_power_critical",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=-9.0, mse="-35")],
                    us30=[_make_us30(1, power=44.0)],
                ),
            },
            {
                "label": "us power critical high",
                "expected_issue": "us_power_critical_high",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-35")],
                    us30=[_make_us30(1, power=55.0)],
                ),
            },
            {
                "label": "us power critical low",
                "expected_issue": "us_power_critical_low",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-35")],
                    us30=[_make_us30(1, power=33.0)],
                ),
            },
            {
                "label": "snr critical",
                "expected_issue": "snr_critical",
                "data": _make_data(
                    ds30=[_make_ds30(1, power=2.0, mse="-27")],
                    us30=[_make_us30(1, power=42.0)],
                ),
            },
        ]

        for case in cases:
            result = analyze(case["data"])
            assert result["summary"]["health"] == "critical", case["label"]
            assert case["expected_issue"] in result["summary"]["health_issues"], case["label"]

    def test_uncorrectable_errors(self):
        """High uncorrectable error percent triggers issue."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35", corr=10000, uncorr=200)],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert "uncorr_errors_high" in result["summary"]["health_issues"]
        assert result["summary"]["health"] in ("tolerated", "marginal", "critical")

    def test_uncorrectable_percent_requires_both_error_counter_types(self):
        """Partial counter support must not be scored as 100% uncorrectable."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35", corr=None, uncorr=1000)],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        assert result["summary"]["ds_correctable_errors"] is None
        assert result["summary"]["ds_uncorrectable_errors"] == 1000
        assert result["summary"]["ds_uncorr_pct"] is None
        assert "uncorr_errors_critical" not in result["summary"]["health_issues"]
        assert "uncorr_errors_high" not in result["summary"]["health_issues"]

    def test_multiple_issues(self):
        """Multiple issues can coexist."""
        data = _make_data(
            ds30=[_make_ds30(1, power=21.0, mse="-27", corr=9000, uncorr=1000)],
            us30=[_make_us30(1, power=55.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        issues = result["summary"]["health_issues"]
        assert "ds_power_critical" in issues
        assert "us_power_critical_high" in issues
        assert "snr_critical" in issues
        assert "uncorr_errors_critical" in issues


# -- Channel parsing --

class TestChannelParsing:
    def test_ds_channels_sorted(self):
        data = _make_data(
            ds30=[_make_ds30(3), _make_ds30(1), _make_ds30(2)],
            us30=[_make_us30(1)],
        )
        result = analyze(data)
        ids = [ch["channel_id"] for ch in result["ds_channels"]]
        assert ids == [1, 2, 3]

    def test_ds30_fields(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=3.5, mse="-35", corr=100, uncorr=5)],
            us30=[_make_us30(1)],
        )
        ch = analyze(data)["ds_channels"][0]
        assert ch["channel_id"] == 1
        assert ch["power"] == 3.5
        assert ch["snr"] == 35.0  # abs of mse
        assert ch["correctable_errors"] == 100
        assert ch["uncorrectable_errors"] == 5
        assert ch["docsis_version"] == "3.0"

    def test_ds31_fields(self):
        data = _make_data(
            ds31=[_make_ds31(100, power=5.0, mer="38.0")],
            us30=[_make_us30(1)],
        )
        ch = analyze(data)["ds_channels"][0]
        assert ch["channel_id"] == 100
        assert ch["snr"] == 38.0
        assert ch["docsis_version"] == "3.1"

    def test_us_channel_fields(self):
        data = _make_data(
            ds30=[_make_ds30(1)],
            us30=[_make_us30(1, power=45.0)],
        )
        ch = analyze(data)["us_channels"][0]
        assert ch["channel_id"] == 1
        assert ch["power"] == 45.0
        assert ch["docsis_version"] == "3.0"

    def test_string_channel_id_parsed_to_int(self):
        """Vodafone Station driver returns channelID as string like '1.0'."""
        data = _make_data(
            ds30=[{**_make_ds30(1), "channelID": "1.0"}],
            us30=[{**_make_us30(1), "channelID": "2"}],
        )
        result = analyze(data)
        assert result["ds_channels"][0]["channel_id"] == 1
        assert result["us_channels"][0]["channel_id"] == 2

    def test_empty_channel_id_defaults_to_zero(self):
        """TG driver may return empty ChannelID - should not crash analyze()."""
        data = _make_data(
            ds30=[{**_make_ds30(1), "channelID": ""}],
            us30=[_make_us30(1)],
        )
        result = analyze(data)
        assert result["ds_channels"][0]["channel_id"] == 0

    def test_per_channel_health(self):
        data = _make_data(
            ds30=[
                _make_ds30(1, power=2.0, mse="-35"),  # good
                _make_ds30(2, power=21.0, mse="-35"),  # power critical
                _make_ds30(3, power=2.0, mse="-27"),  # snr critical
            ],
            us30=[_make_us30(1)],
        )
        channels = analyze(data)["ds_channels"]
        assert channels[0]["health"] == "good"
        assert channels[1]["health"] == "critical"
        assert channels[2]["health"] == "critical"


# -- Summary metrics --

class TestSummaryMetrics:
    def test_counts(self):
        data = _make_data(
            ds30=[_make_ds30(i) for i in range(1, 4)],
            ds31=[_make_ds31(100)],
            us30=[_make_us30(1), _make_us30(2)],
        )
        s = analyze(data)["summary"]
        assert s["ds_total"] == 4
        assert s["us_total"] == 2

    def test_power_stats(self):
        data = _make_data(
            ds30=[
                _make_ds30(1, power=2.0, mse="-35"),
                _make_ds30(2, power=4.0, mse="-35"),
                _make_ds30(3, power=6.0, mse="-35"),
            ],
            us30=[_make_us30(1, power=40.0), _make_us30(2, power=44.0)],
        )
        s = analyze(data)["summary"]
        assert s["ds_power_min"] == 2.0
        assert s["ds_power_max"] == 6.0
        assert s["ds_power_avg"] == 4.0
        assert s["us_power_min"] == 40.0
        assert s["us_power_max"] == 44.0
        assert s["us_power_avg"] == 42.0

    def test_error_totals(self):
        data = _make_data(
            ds30=[
                _make_ds30(1, corr=100, uncorr=5),
                _make_ds30(2, corr=200, uncorr=10),
            ],
            us30=[_make_us30(1)],
        )
        s = analyze(data)["summary"]
        assert s["ds_correctable_errors"] == 300
        assert s["ds_uncorrectable_errors"] == 15

    def test_empty_data(self):
        data = _make_data()
        result = analyze(data)
        assert result["summary"]["ds_total"] == 0
        assert result["summary"]["us_total"] == 0
        assert result["summary"]["health"] == "good"


# -- QAM order parsing --
