"""Tests for DOCSIS channel health analyzer."""

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
    def test_ds_power_tolerated(self):
        """DS power 15 dBmV is tolerated (between good_max 13 and warn_max 18)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=15.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "tolerated"
        assert "ds_power_tolerated" in result["summary"]["health_issues"]

    def test_us_power_tolerated_high(self):
        """US power 49 dBmV is tolerated (between good_max 47 and warn_max 51)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=49.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "tolerated"
        assert "us_power_tolerated_high" in result["summary"]["health_issues"]

    def test_us_power_tolerated_low(self):
        """US power 40 dBmV is tolerated (between warn_min 37.1 and good_min 41.1)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=40.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "tolerated"
        assert "us_power_tolerated_low" in result["summary"]["health_issues"]

    def test_snr_tolerated(self):
        """SNR 31 dB is tolerated (between warn_min 31 and good_min 33)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-31")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "tolerated"
        assert "snr_tolerated" in result["summary"]["health_issues"]


# -- Health assessment: marginal --

class TestHealthMarginal:
    def test_ds_power_marginal(self):
        """DS power 19 dBmV is marginal (between warn_max 18 and crit_max 20)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=19.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "ds_power_marginal" in result["summary"]["health_issues"]

    def test_us_power_marginal_high(self):
        """US power 52 dBmV is marginal (between warn_max 51 and crit_max 53)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=52.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "us_power_marginal_high" in result["summary"]["health_issues"]

    def test_us_power_marginal_low(self):
        """US power 36 dBmV is marginal (between crit_min 35 and warn_min 37.1)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=36.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "us_power_marginal_low" in result["summary"]["health_issues"]

    def test_snr_marginal(self):
        """SNR 30.5 dB is marginal (between crit_min 30 and warn_min 31)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-30.5")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "snr_marginal" in result["summary"]["health_issues"]


# -- Health assessment: critical --

class TestHealthCritical:
    def test_ds_power_critical(self):
        """DS power 21 dBmV is critical (>20)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=21.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "ds_power_critical" in result["summary"]["health_issues"]

    def test_ds_power_critical_negative(self):
        """DS power -9 dBmV is also critical (<-8)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=-9.0, mse="-35")],
            us30=[_make_us30(1, power=44.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "ds_power_critical" in result["summary"]["health_issues"]

    def test_us_power_critical_high(self):
        """US power 55 dBmV is critical (>53)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=55.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "us_power_critical_high" in result["summary"]["health_issues"]

    def test_us_power_critical_low(self):
        """US power 33 dBmV is critical (<35)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=33.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "us_power_critical_low" in result["summary"]["health_issues"]

    def test_snr_critical(self):
        """SNR 27 dB is critical (<30)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-27")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "snr_critical" in result["summary"]["health_issues"]

    def test_uncorrectable_errors(self):
        """High uncorrectable error percent triggers issue."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35", corr=10000, uncorr=200)],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        assert "uncorr_errors_high" in result["summary"]["health_issues"]
        assert result["summary"]["health"] in ("tolerated", "marginal", "critical")

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

class TestParseQamOrder:
    def test_standard_qam(self):
        assert _parse_qam_order("64QAM") == 64

    def test_lower_qam(self):
        assert _parse_qam_order("16QAM") == 16
        assert _parse_qam_order("4QAM") == 4

    def test_high_qam(self):
        assert _parse_qam_order("256QAM") == 256
        assert _parse_qam_order("1024QAM") == 1024

    def test_qpsk(self):
        assert _parse_qam_order("QPSK") == 4

    def test_case_insensitive(self):
        assert _parse_qam_order("64qam") == 64
        assert _parse_qam_order("qpsk") == 4

    def test_none_and_empty(self):
        assert _parse_qam_order(None) is None
        assert _parse_qam_order("") is None

    def test_unparseable(self):
        assert _parse_qam_order("OFDMA") is None
        assert _parse_qam_order("SC-QAM") is None


# -- Upstream modulation health --

class TestUpstreamModulation:
    def test_64qam_good(self):
        """64-QAM is normal for Vodafone upstream."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="64QAM")],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "good"
        us_ch = result["us_channels"][0]
        assert us_ch["health"] == "good"

    def test_32qam_good(self):
        """32-QAM is tolerated, no warning."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="32QAM")],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "good"

    def test_16qam_warning(self):
        """16-QAM triggers modulation warning."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="16QAM")],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "us_modulation_marginal" in result["summary"]["health_issues"]
        us_ch = result["us_channels"][0]
        assert us_ch["health"] == "warning"
        assert "modulation warning" in us_ch["health_detail"]

    def test_8qam_warning(self):
        """8-QAM triggers modulation warning."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="8QAM")],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "marginal"
        assert "us_modulation_marginal" in result["summary"]["health_issues"]

    def test_4qam_critical(self):
        """4-QAM is critical (Rueckwegstoerer indicator)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="4QAM")],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "us_modulation_critical" in result["summary"]["health_issues"]
        us_ch = result["us_channels"][0]
        assert us_ch["health"] == "critical"
        assert "modulation critical" in us_ch["health_detail"]

    def test_qpsk_critical(self):
        """QPSK (= 4-QAM) is critical."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="QPSK")],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "us_modulation_critical" in result["summary"]["health_issues"]

    def test_mixed_channels(self):
        """One degraded channel is enough to affect overall health."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[
                _make_us30(1, power=42.0, modulation="64QAM"),
                _make_us30(2, power=42.0, modulation="64QAM"),
                _make_us30(3, power=42.0, modulation="4QAM"),
                _make_us30(4, power=42.0, modulation="64QAM"),
            ],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        assert "us_modulation_critical" in result["summary"]["health_issues"]
        healths = [c["health"] for c in result["us_channels"]]
        assert healths.count("critical") == 1
        assert healths.count("good") == 3

    def test_modulation_and_power_combined(self):
        """Both power and modulation issues can coexist."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=55.0, modulation="4QAM")],
        )
        result = analyze(data)
        assert result["summary"]["health"] == "critical"
        issues = result["summary"]["health_issues"]
        assert "us_power_critical_high" in issues
        assert "us_modulation_critical" in issues
        us_ch = result["us_channels"][0]
        assert "power critical high" in us_ch["health_detail"]
        assert "modulation critical" in us_ch["health_detail"]


# -- OFDM / 4096QAM threshold resolution --

class TestOFDMThresholds:
    def test_resolve_ofdm_to_4096qam(self):
        """OFDM modulation string maps to 4096QAM thresholds."""
        section = {"256QAM": {}, "4096QAM": {}, "_default": "256QAM"}
        assert _resolve_modulation("OFDM", section) == "4096QAM"

    def test_resolve_ofdma_to_4096qam(self):
        """OFDMA modulation string maps to 4096QAM thresholds."""
        section = {"256QAM": {}, "4096QAM": {}, "_default": "256QAM"}
        assert _resolve_modulation("OFDMA", section) == "4096QAM"

    def test_resolve_4096qam_direct(self):
        """4096QAM modulation string resolves directly."""
        section = {"256QAM": {}, "4096QAM": {}, "_default": "256QAM"}
        assert _resolve_modulation("4096QAM", section) == "4096QAM"

    def test_resolve_unknown_falls_back(self):
        """Unknown modulation falls back to _default."""
        section = {"256QAM": {}, "_default": "256QAM"}
        assert _resolve_modulation("UNKNOWN", section) == "256QAM"

    def test_4096qam_snr_good(self):
        """4096QAM channel with MER 41 dB is good (threshold: good_min=40)."""
        data = _make_data(
            ds31=[_make_ds31(100, power=5.0, mer="41.0")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        ch = result["ds_channels"][0]
        assert ch["health"] == "good"

    def test_4096qam_snr_tolerated(self):
        """4096QAM channel with MER 39.5 dB triggers SNR tolerated (good_min=40, warn_min=38, crit=36)."""
        data = _make_data(
            ds31=[_make_ds31(100, power=5.0, mer="39.5")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        ch = result["ds_channels"][0]
        assert "snr tolerated" in ch["health_detail"]

    def test_4096qam_snr_critical(self):
        """4096QAM channel with MER 35 dB is critical (threshold: immediate_min=36)."""
        data = _make_data(
            ds31=[_make_ds31(100, power=5.0, mer="35.0")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        ch = result["ds_channels"][0]
        assert "snr critical" in ch["health_detail"]

    def test_ofdm_type_field_uses_4096qam_thresholds(self):
        """Channel with type=OFDM (no modulation field) uses 4096QAM thresholds."""
        ds_ofdm = {
            "channelID": 200,
            "frequency": "134-325 MHz",
            "powerLevel": "5.0",
            "type": "OFDM",
            "mer": "39.5",
            "corrErrors": 0,
            "nonCorrErrors": 0,
        }
        data = _make_data(
            ds31=[ds_ofdm],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        ch = result["ds_channels"][0]
        # MER 39.5 is below 4096QAM good_min (40) but above warn_min (38), so tolerated
        assert "snr tolerated" in ch["health_detail"]


# -- Upstream bitrate calculation --

class TestChannelBitrate:
    def test_64qam_default_rate(self):
        """64-QAM at 5120 kSym/s = 30.72 Mbit/s."""
        assert _channel_bitrate_mbps("64QAM") == 30.72

    def test_4qam(self):
        """4-QAM at 5120 kSym/s = 10.24 Mbit/s."""
        assert _channel_bitrate_mbps("4QAM") == 10.24

    def test_qpsk(self):
        """QPSK (= 4-QAM) at 5120 kSym/s = 10.24 Mbit/s."""
        assert _channel_bitrate_mbps("QPSK") == 10.24

    def test_16qam(self):
        """16-QAM at 5120 kSym/s = 20.48 Mbit/s."""
        assert _channel_bitrate_mbps("16QAM") == 20.48

    def test_256qam(self):
        """256-QAM at 5120 kSym/s = 40.96 Mbit/s."""
        assert _channel_bitrate_mbps("256QAM") == 40.96

    def test_custom_symbol_rate(self):
        """Custom symbol rate overrides default."""
        assert _channel_bitrate_mbps("64QAM", 2560) == 15.36

    def test_ofdma_returns_none(self):
        """OFDMA modulation has no simple QAM order, returns None."""
        assert _channel_bitrate_mbps("OFDMA") is None

    def test_none_returns_none(self):
        assert _channel_bitrate_mbps(None) is None

    def test_empty_returns_none(self):
        assert _channel_bitrate_mbps("") is None


class TestUpstreamCapacity:
    def test_aggregate_4x64qam(self):
        """4 channels at 64-QAM = 122.88 Mbit/s."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(i, power=42.0, modulation="64QAM") for i in range(1, 5)],
        )
        result = analyze(data)
        assert result["summary"]["us_capacity_mbps"] == 122.9

    def test_aggregate_4x4qam(self):
        """4 channels at 4-QAM = 40.96 Mbit/s (degraded)."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(i, power=42.0, modulation="4QAM") for i in range(1, 5)],
        )
        result = analyze(data)
        assert result["summary"]["us_capacity_mbps"] == 41.0

    def test_per_channel_bitrate(self):
        """Each US channel has theoretical_bitrate field."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="64QAM")],
        )
        ch = analyze(data)["us_channels"][0]
        assert ch["theoretical_bitrate"] == 30.72

    def test_mixed_modulation(self):
        """Mixed 64-QAM and 4-QAM channels sum correctly."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[
                _make_us30(1, power=42.0, modulation="64QAM"),
                _make_us30(2, power=42.0, modulation="64QAM"),
                _make_us30(3, power=42.0, modulation="4QAM"),
                _make_us30(4, power=42.0, modulation="64QAM"),
            ],
        )
        result = analyze(data)
        # 3 * 30.72 + 1 * 10.24 = 102.4
        assert result["summary"]["us_capacity_mbps"] == 102.4

    def test_no_us_channels(self):
        """No US channels -> us_capacity_mbps is None."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
        )
        result = analyze(data)
        assert result["summary"]["us_capacity_mbps"] is None


# -- Dynamic threshold tests --

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
        assert t["good_min"] == -3.9  # fallback value


class TestOFDMAUpstream:
    """Test OFDMA upstream channel assessment."""

    def setup_method(self):
        self._orig = analyzer._thresholds.copy()
        analyzer.set_thresholds(_TEST_THRESHOLDS)

    def teardown_method(self):
        analyzer._thresholds = self._orig

    def test_ofdma_channel_good(self):
        ch = {"powerLevel": "45.0", "modulation": "OFDMA", "type": "OFDMA"}
        health, detail = analyzer._assess_us_channel(ch)
        assert health == "good"

    def test_ofdma_channel_tolerated(self):
        """OFDMA power 40.5 is tolerated (between warn_min 40.1 and good_min 44.1)."""
        ch = {"powerLevel": "40.5", "modulation": "OFDMA", "type": "OFDMA"}
        health, detail = analyzer._assess_us_channel(ch)
        assert health == "tolerated"

    def test_ofdma_channel_critical_low(self):
        ch = {"powerLevel": "37.0", "modulation": "OFDMA", "type": "OFDMA"}
        health, detail = analyzer._assess_us_channel(ch)
        assert health == "critical"

    def test_sc_qam_still_uses_sc_qam_thresholds(self):
        ch = {"powerLevel": "42.0", "modulation": "64QAM", "type": "ATDMA"}
        health, detail = analyzer._assess_us_channel(ch)
        assert health == "good"


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

    def test_warning_threshold(self):
        # 1% uncorrectable => warning
        data = _make_data(ds30=[_make_ds30(1, corr=9900, uncorr=100)])
        result = analyze(data)
        assert "uncorr_errors_high" in result["summary"]["health_issues"]

    def test_critical_threshold(self):
        # 5% uncorrectable => critical
        data = _make_data(ds30=[_make_ds30(1, corr=9500, uncorr=500)])
        result = analyze(data)
        assert "uncorr_errors_critical" in result["summary"]["health_issues"]

    def test_zero_codewords_no_error(self):
        data = _make_data(ds30=[_make_ds30(1, corr=0, uncorr=0)])
        result = analyze(data)
        assert "uncorr_errors_high" not in result["summary"]["health_issues"]
        assert "uncorr_errors_critical" not in result["summary"]["health_issues"]

    def test_below_min_codewords_suppressed(self):
        # 50% uncorrectable but only 6 total codewords — below min_codewords threshold
        data = _make_data(ds30=[_make_ds30(1, corr=3, uncorr=3)])
        result = analyze(data)
        assert result["summary"]["ds_uncorr_pct"] == 0.0
        assert "uncorr_errors_high" not in result["summary"]["health_issues"]
        assert "uncorr_errors_critical" not in result["summary"]["health_issues"]


class TestSpikeExpiryThreshold:
    def test_default_spike_expiry_hours(self):
        from app.analyzer import _get_spike_expiry_hours
        hours = _get_spike_expiry_hours()
        assert hours == 48


class TestSpikeSuppression:
    """Tests for apply_spike_suppression()."""

    def _make_analysis_with_uncorr(self, uncorr_pct=86.6, health="critical",
                                    extra_issues=None):
        """Build a minimal analysis dict with uncorrectable error issues."""
        issues = ["uncorr_errors_critical"]
        if extra_issues:
            issues.extend(extra_issues)
        return {
            "summary": {
                "health": health,
                "health_issues": issues,
                "ds_uncorr_pct": uncorr_pct,
                "ds_correctable_errors": 155000,
                "ds_uncorrectable_errors": 1000000,
                "ds_total": 33,
                "us_total": 4,
            },
            "ds_channels": [],
            "us_channels": [],
        }

    def test_no_spike_no_change(self):
        """No spike timestamp — analysis stays unchanged."""
        from app.analyzer import apply_spike_suppression
        analysis = self._make_analysis_with_uncorr()
        apply_spike_suppression(analysis, None)
        assert analysis["summary"]["ds_uncorr_pct"] == 86.6
        assert "uncorr_errors_critical" in analysis["summary"]["health_issues"]
        assert analysis["summary"]["health"] == "critical"
        assert "spike_suppression" not in analysis["summary"]

    @patch("app.analyzer.utc_now")
    def test_recent_spike_no_suppression(self, mock_now):
        """Spike < 48h ago — still in observation period, no suppression."""
        from app.analyzer import apply_spike_suppression
        mock_now.return_value = "2026-02-28T12:00:00Z"
        analysis = self._make_analysis_with_uncorr()
        apply_spike_suppression(analysis, "2026-02-27T14:00:00Z")
        assert analysis["summary"]["ds_uncorr_pct"] == 86.6
        assert "uncorr_errors_critical" in analysis["summary"]["health_issues"]
        assert analysis["summary"]["health"] == "critical"
        assert "spike_suppression" not in analysis["summary"]

    @patch("app.analyzer.utc_now")
    def test_expired_spike_suppresses(self, mock_now):
        """Spike >= 48h ago — suppression active."""
        from app.analyzer import apply_spike_suppression
        mock_now.return_value = "2026-03-01T15:00:00Z"  # 72.5h after spike
        analysis = self._make_analysis_with_uncorr()
        apply_spike_suppression(analysis, "2026-02-27T14:30:00Z")
        assert analysis["summary"]["ds_uncorr_pct"] == 0.0
        assert "uncorr_errors_critical" not in analysis["summary"]["health_issues"]
        assert "uncorr_errors_high" not in analysis["summary"]["health_issues"]
        assert analysis["summary"]["health"] == "good"
        sup = analysis["summary"]["spike_suppression"]
        assert sup["active"] is True
        assert sup["last_spike"] == "2026-02-27T14:30:00Z"
        assert sup["expiry_hours"] == 48

    @patch("app.analyzer.utc_now")
    def test_expired_spike_other_issues_remain(self, mock_now):
        """Spike expired but other critical issues exist — health stays poor."""
        from app.analyzer import apply_spike_suppression
        mock_now.return_value = "2026-03-01T15:00:00Z"
        analysis = self._make_analysis_with_uncorr(
            extra_issues=["snr_critical"]
        )
        apply_spike_suppression(analysis, "2026-02-27T14:00:00Z")
        assert analysis["summary"]["ds_uncorr_pct"] == 0.0
        assert "uncorr_errors_critical" not in analysis["summary"]["health_issues"]
        assert "snr_critical" in analysis["summary"]["health_issues"]
        assert analysis["summary"]["health"] == "critical"
        assert analysis["summary"]["spike_suppression"]["active"] is True

    @patch("app.analyzer.utc_now")
    def test_expired_spike_warning_issues_marginal(self, mock_now):
        """Spike expired, only marginal issues remain — health becomes marginal."""
        from app.analyzer import apply_spike_suppression
        mock_now.return_value = "2026-03-01T15:00:00Z"
        analysis = self._make_analysis_with_uncorr(
            extra_issues=["snr_marginal"]
        )
        apply_spike_suppression(analysis, "2026-02-27T14:00:00Z")
        assert analysis["summary"]["health"] == "marginal"

    @patch("app.analyzer.utc_now")
    def test_spike_at_exact_boundary(self, mock_now):
        """Spike exactly 48h ago — suppressed (>= boundary)."""
        from app.analyzer import apply_spike_suppression
        mock_now.return_value = "2026-03-01T14:00:00Z"
        analysis = self._make_analysis_with_uncorr()
        apply_spike_suppression(analysis, "2026-02-27T14:00:00Z")
        assert analysis["summary"]["ds_uncorr_pct"] == 0.0
        assert analysis["summary"]["spike_suppression"]["active"] is True


# -- Per-metric health extraction --

class TestMetricHealths:
    """Tests for _metric_healths() helper."""

    def test_empty_issues(self):
        assert _metric_healths([]) == {}

    def test_power_critical(self):
        result = _metric_healths(["power critical"])
        assert result == {"power_health": "critical"}

    def test_power_warning(self):
        result = _metric_healths(["power warning"])
        assert result == {"power_health": "warning"}

    def test_power_tolerated(self):
        result = _metric_healths(["power tolerated"])
        assert result == {"power_health": "tolerated"}

    def test_snr_critical(self):
        result = _metric_healths(["snr critical"])
        assert result == {"snr_health": "critical"}

    def test_modulation_warning(self):
        result = _metric_healths(["modulation warning"])
        assert result == {"modulation_health": "warning"}

    def test_multiple_metrics(self):
        result = _metric_healths(["power critical", "snr warning"])
        assert result == {"power_health": "critical", "snr_health": "warning"}

    def test_directional_us_power(self):
        """US power issues with direction suffix are matched correctly."""
        result = _metric_healths(["power critical low"])
        assert result == {"power_health": "critical"}

    def test_critical_beats_warning(self):
        """If both critical and warning exist for same metric, critical wins."""
        result = _metric_healths(["power critical", "power warning"])
        assert result == {"power_health": "critical"}


class TestChannelMetricHealthFields:
    """Test that channel dicts contain per-metric health fields."""

    def test_ds_good_has_no_metric_health(self):
        """Good DS channel has no *_health keys."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0)],
        )
        ch = analyze(data)["ds_channels"][0]
        assert ch["health"] == "good"
        assert "power_health" not in ch
        assert "snr_health" not in ch

    def test_ds_power_critical_field(self):
        """DS channel with bad power has power_health='critical'."""
        data = _make_data(
            ds30=[_make_ds30(1, power=21.0, mse="-35")],
            us30=[_make_us30(1, power=42.0)],
        )
        ch = analyze(data)["ds_channels"][0]
        assert ch["power_health"] == "critical"
        assert "snr_health" not in ch

    def test_ds_snr_tolerated_field(self):
        """DS channel with marginal SNR has snr_health='tolerated'."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-32")],
            us30=[_make_us30(1, power=42.0)],
        )
        ch = analyze(data)["ds_channels"][0]
        assert ch["snr_health"] == "tolerated"

    def test_us_modulation_critical_field(self):
        """US channel with 4-QAM has modulation_health='critical'."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0, modulation="4QAM")],
        )
        ch = analyze(data)["us_channels"][0]
        assert ch["modulation_health"] == "critical"

    def test_us_power_warning_field(self):
        """US channel with low power has power_health='warning'."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=36.0)],
        )
        ch = analyze(data)["us_channels"][0]
        assert ch["power_health"] == "warning"

    def test_us_combined_fields(self):
        """US channel with bad power AND bad modulation has both fields."""
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=55.0, modulation="4QAM")],
        )
        ch = analyze(data)["us_channels"][0]
        assert ch["power_health"] == "critical"
        assert ch["modulation_health"] == "critical"
