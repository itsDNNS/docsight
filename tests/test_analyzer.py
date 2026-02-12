"""Tests for DOCSIS channel health analyzer."""

import pytest
from app.analyzer import analyze, _parse_float


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


def _make_us30(channel_id=1, power=42.0):
    return {
        "channelID": channel_id,
        "frequency": "37 MHz",
        "powerLevel": str(power),
        "modulation": "64QAM",
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


# -- Health assessment: marginal --

class TestHealthMarginal:
    def test_ds_power_warning(self):
        """DS power 15 dBmV is marginal (>13, <20)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=15.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "ds_power_warn" in result["summary"]["health_issues"]

    def test_us_power_warning(self):
        """US power 49 dBmV triggers marginal (>47, <53)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=49.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "us_power_warn" in result["summary"]["health_issues"]

    def test_snr_warning(self):
        """SNR 31 dB is marginal (between 29-33)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-31")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "snr_warn" in result["summary"]["health_issues"]


# -- Health assessment: poor --

class TestHealthPoor:
    def test_ds_power_critical(self):
        """DS power 21 dBmV is critical (>20)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=21.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "poor"
        assert "ds_power_critical" in result["summary"]["health_issues"]

    def test_ds_power_critical_negative(self):
        """DS power -9 dBmV is also critical (<-8)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=-9.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "poor"
        assert "ds_power_critical" in result["summary"]["health_issues"]

    def test_us_power_critical_high(self):
        """US power 55 dBmV is critical (>53)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=55.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "poor"
        assert "us_power_critical" in result["summary"]["health_issues"]

    def test_us_power_critical_low(self):
        """US power 33 dBmV is critical (<35)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=33.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "poor"
        assert "us_power_critical" in result["summary"]["health_issues"]

    def test_snr_critical(self):
        """SNR 27 dB is critical (<29)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-27")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "poor"
        assert "snr_critical" in result["summary"]["health_issues"]

    def test_uncorrectable_errors(self):
        """High uncorrectable errors trigger issue (>10000 threshold)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35", uncorr=15000)],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert "uncorr_errors_high" in result["summary"]["health_issues"]
        assert result["summary"]["health"] in ("marginal", "poor")

    def test_multiple_issues(self):
        """Multiple issues can coexist."""
        data = _make_data(
            ds30=[_make_ds30(1, power=21.0, mse="-27", uncorr=20000)],
            us30=[_make_us30(1, power=55.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "poor"
        issues = result["summary"]["health_issues"]
        assert "ds_power_critical" in issues
        assert "us_power_critical" in issues
        assert "snr_critical" in issues
        assert "uncorr_errors_high" in issues


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
