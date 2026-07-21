"""Tests for analyzer modulation, bitrate, and capacity calculations."""

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

    @pytest.mark.parametrize(
        ("mer", "expected_health"),
        [
            (24.4, "critical"),
            (24.5, "warning"),
            (25.5, "tolerated"),
            (27.0, "good"),
        ],
    )
    def test_ofdm_mer_boundaries_use_ofdm_thresholds(self, mer, expected_health):
        data = _make_data(
            ds31=[_make_ds31(100, power=5.0, mer=str(mer))],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        channel = result["ds_channels"][0]
        family = result["summary"]["signal_families"]["downstream"]["families"]["ofdm"]
        assert channel.get("snr_health", "good") == expected_health
        assert channel["health"] == expected_health
        assert family["mer"]["health"] == expected_health

    @pytest.mark.parametrize("mer", [33.0, 38.0])
    def test_docsis31_ofdm_labelled_4096qam_uses_ofdm_thresholds(self, mer):
        data = _make_data(
            ds31=[_make_ds31(100, power=5.0, mer=str(mer))],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        channel = result["ds_channels"][0]
        family = result["summary"]["signal_families"]["downstream"]["families"]["ofdm"]
        assert channel.get("snr_health", "good") == "good"
        assert family["mer"]["health"] == "good"

    def test_ofdm_type_field_uses_ofdm_thresholds(self):
        ds_ofdm = {
            "channelID": 200,
            "frequency": "134-325 MHz",
            "powerLevel": "5.0",
            "type": "OFDM",
            "mer": "33.0",
            "corrErrors": 0,
            "nonCorrErrors": 0,
        }
        data = _make_data(
            ds31=[ds_ofdm],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)
        ch = result["ds_channels"][0]
        assert ch["channel_family"] == "ofdm"
        assert ch.get("snr_health", "good") == "good"

    @pytest.mark.parametrize(
        ("mse", "expected_health"),
        [
            ("-28.9", "critical"),
            ("-29.0", "warning"),
            ("-31.0", "tolerated"),
            ("-33.0", "good"),
        ],
    )
    def test_sc_qam_snr_boundaries_are_unchanged(self, mse, expected_health):
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse=mse)],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        channel = result["ds_channels"][0]
        family = result["summary"]["signal_families"]["downstream"]["families"]["sc_qam"]
        assert channel.get("snr_health", "good") == expected_health
        assert family["snr"]["health"] == expected_health


# -- Family-level signal summaries --

class TestSignalFamilySummaries:
    def test_sc_qam_only_downstream_summary_uses_sc_qam_snr(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=1.0, mse="-35"), _make_ds30(2, power=3.0, mse="-37")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)

        families = result["summary"]["signal_families"]["downstream"]["families"]
        assert set(families) == {"sc_qam"}
        assert families["sc_qam"]["power"]["avg"] == 2.0
        assert families["sc_qam"]["snr"]["avg"] == 36.0
        assert families["sc_qam"]["modulation"]["value"] == "256QAM"
        assert result["ds_channels"][0]["channel_family"] == "sc_qam"

    def test_mixed_downstream_keeps_sc_qam_snr_and_ofdm_mer_separate(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=1.0, mse="-36")],
            ds31=[_make_ds31(33, power=0.5, mer="37.0")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)

        downstream = result["summary"]["signal_families"]["downstream"]
        families = downstream["families"]
        assert set(families) == {"sc_qam", "ofdm"}
        assert families["sc_qam"]["snr"]["avg"] == 36.0
        assert families["ofdm"]["mer"]["avg"] == 37.0
        assert families["ofdm"]["mer"]["health"] == "good"
        assert downstream["health"] == "good"

    def test_docsis31_high_qam_profile_is_ofdm_not_sc_qam(self):
        data = _make_data(
            ds31=[_make_ds31(33, power=1.0, mer="41.0")],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)

        families = result["summary"]["signal_families"]["downstream"]["families"]
        assert set(families) == {"ofdm"}
        assert result["ds_channels"][0]["channel_family"] == "ofdm"
        assert families["ofdm"]["mer"]["avg"] == 41.0

    def test_docsis31_explicit_low_qam_modulation_stays_sc_qam(self):
        data = _make_data(
            ds31=[{
                "channelID": 33,
                "frequency": "159 MHz",
                "powerLevel": "1.0",
                "modulation": "256QAM",
                "mer": "34.0",
            }],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)

        families = result["summary"]["signal_families"]["downstream"]["families"]
        assert set(families) == {"sc_qam"}
        assert result["ds_channels"][0]["channel_family"] == "sc_qam"
        assert result["ds_channels"][0]["modulation_health"] == "good"
        assert result["ds_channels"][0]["health"] == "good"
        assert families["sc_qam"]["modulation"]["health"] == "good"
        assert families["sc_qam"]["modulation"]["value"] == "256QAM"

    def test_docsis31_profile_only_low_qam_stays_ofdm_not_sc_qam(self):
        data = _make_data(
            ds31=[{
                "channelID": 33,
                "frequency": "159 MHz",
                "powerLevel": "1.0",
                "profile_modulation": "256QAM",
                "mer": "34.0",
            }],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)

        families = result["summary"]["signal_families"]["downstream"]["families"]
        assert set(families) == {"ofdm"}
        assert result["ds_channels"][0]["channel_family"] == "ofdm"
        assert families["ofdm"]["mer"]["avg"] == 34.0
        assert families["ofdm"]["modulation"]["value"] == "256QAM"

    def test_docsis31_upstream_profile_only_low_qam_stays_ofdma_not_sc_qam(self):
        us_ofdma = {
            "channelID": 5,
            "frequency": "30-65 MHz",
            "profile_modulation": "64QAM",
        }
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us31=[us_ofdma],
        )
        result = analyze(data)

        upstream = result["summary"]["signal_families"]["upstream"]["families"]
        assert set(upstream) == {"ofdma"}
        assert result["us_channels"][0]["channel_family"] == "ofdma"
        assert upstream["ofdma"]["modulation"]["value"] == "64QAM"

    def test_docsis31_upstream_profile_only_camel_case_profile_key_stays_ofdma(self):
        us_ofdma = {
            "channelID": 5,
            "frequency": "30-65 MHz",
            "profileModulation": "64QAM",
        }
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us31=[us_ofdma],
        )
        result = analyze(data)

        upstream = result["summary"]["signal_families"]["upstream"]["families"]
        assert set(upstream) == {"ofdma"}
        assert result["us_channels"][0]["channel_family"] == "ofdma"
        assert upstream["ofdma"]["modulation"]["value"] == "64QAM"

    def test_docsis31_upstream_qam_modulation_without_type_stays_ofdma(self):
        """Some modems expose an OFDMA profile QAM value only as `modulation`."""
        us_ofdma = {
            "channelID": 41,
            "frequency": "46.500 MHz",
            "powerLevel": "50.5",
            "modulation": "128QAM",
        }
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[
                _make_us30(channel_id, power=power, modulation="64QAM")
                for channel_id, power in [(1, 40.5), (2, 41.8), (3, 42.5), (4, 43.0)]
            ],
            us31=[us_ofdma],
        )

        result = analyze(data)

        upstream = result["summary"]["signal_families"]["upstream"]["families"]
        assert set(upstream) == {"sc_qam", "ofdma"}
        assert result["us_channels"][-1]["channel_family"] == "ofdma"
        assert result["us_channels"][-1]["power_health"] == "critical"
        assert result["us_channels"][-1]["modulation_health"] == "tolerated"
        assert upstream["sc_qam"]["count"] == 4
        assert upstream["sc_qam"]["power"]["avg"] == 42.0
        assert upstream["ofdma"]["count"] == 1
        assert upstream["ofdma"]["power"]["avg"] == 50.5
        assert result["summary"]["us_scqam_power_avg"] == 42.0
        assert result["summary"]["us_ofdma_power_avg"] == 50.5

    def test_docsis31_upstream_explicit_atdma_type_stays_sc_qam(self):
        us_sc_qam = {
            "channelID": 42,
            "frequency": "46.500 MHz",
            "powerLevel": "42.5",
            "type": "ATDMA",
            "modulation": "128QAM",
        }
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us31=[us_sc_qam],
        )

        result = analyze(data)

        upstream = result["summary"]["signal_families"]["upstream"]["families"]
        assert set(upstream) == {"sc_qam"}
        assert result["us_channels"][0]["channel_family"] == "sc_qam"
        assert result["summary"]["us_scqam_power_avg"] == 42.5
        assert result["summary"].get("us_ofdma_power_avg") is None

    def test_docsis31_profile_only_camel_case_profile_key_stays_ofdm(self):
        data = _make_data(
            ds31=[{
                "channelID": 33,
                "frequency": "159 MHz",
                "powerLevel": "1.0",
                "profileModulation": "256QAM",
                "mer": "34.0",
            }],
            us30=[_make_us30(1, power=42.0)],
        )
        result = analyze(data)

        families = result["summary"]["signal_families"]["downstream"]["families"]
        assert set(families) == {"ofdm"}
        assert result["ds_channels"][0]["channel_family"] == "ofdm"
        assert families["ofdm"]["modulation"]["value"] == "256QAM"

    def test_missing_ofdm_mer_stays_unavailable_not_zero(self):
        ds_ofdm = _make_ds31(33, power=1.0, mer="38.0")
        ds_ofdm.pop("mer")
        data = _make_data(ds31=[ds_ofdm], us30=[_make_us30(1, power=42.0)])
        result = analyze(data)

        ofdm = result["summary"]["signal_families"]["downstream"]["families"]["ofdm"]
        assert ofdm["mer"]["available"] is False
        assert ofdm["mer"]["avg"] is None
        assert ofdm["mer"]["health"] == "missing"

    def test_upstream_ofdma_missing_power_and_low_profile_modulation_are_visible(self):
        us_ofdma = {
            "channelID": 5,
            "frequency": "30-65 MHz",
            "type": "OFDMA",
            "profile_modulation": "64QAM",
        }
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=43.0, modulation="64QAM")],
            us31=[us_ofdma],
        )
        result = analyze(data)

        upstream = result["summary"]["signal_families"]["upstream"]["families"]
        assert set(upstream) == {"sc_qam", "ofdma"}
        assert upstream["ofdma"]["power"]["available"] is False
        assert upstream["ofdma"]["power"]["avg"] is None
        assert upstream["ofdma"]["modulation"]["value"] == "64QAM"
        assert upstream["ofdma"]["modulation"]["health"] == "warning"

    def test_upstream_ofdma_family_health_surfaces_critical_modulation_cause(self):
        us_ofdma = {
            "channelID": 5,
            "frequency": "30-65 MHz",
            "type": "OFDMA",
            "powerLevel": "49.5",
            "profile_modulation": "32QAM",
        }
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us31=[us_ofdma],
        )

        result = analyze(data)

        ofdma = result["summary"]["signal_families"]["upstream"]["families"]["ofdma"]
        assert ofdma["power"]["health"] == "warning"
        assert ofdma["modulation"]["health"] == "critical"
        assert ofdma["health"] == "critical"
        assert ofdma["health_cause"] == "modulation"

    def test_upstream_sc_qam_family_keeps_health_per_distinct_modulation_value(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[
                _make_us30(1, power=42.0, modulation="4QAM"),
                _make_us30(2, power=42.0, modulation="64QAM"),
            ],
        )

        result = analyze(data)

        sc_qam = result["summary"]["signal_families"]["upstream"]["families"]["sc_qam"]
        assert sc_qam["modulation"]["value"] == "4QAM"
        assert sc_qam["modulation"]["secondary"] == "64QAM"
        assert sc_qam["modulation"]["health"] == "critical"
        assert sc_qam["modulation"]["values"] == [
            {"value": "4QAM", "health": "critical"},
            {"value": "64QAM", "health": "good"},
        ]

    def test_modulation_value_healths_keep_worst_health_for_duplicate_values(self):
        channels = [
            {"modulation": "64QAM", "modulation_health": "good"},
            {"modulation": "64QAM", "modulation_health": "warning"},
        ]

        values = analyzer._distinct_modulation_healths(channels)

        assert values == [{"value": "64QAM", "health": "warning"}]

    def test_upstream_ofdma_family_keeps_health_per_distinct_profile_modulation_value(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us31=[
                {
                    "channelID": 5,
                    "frequency": "30-65 MHz",
                    "type": "OFDMA",
                    "powerLevel": "49.5",
                    "profile_modulation": "32QAM",
                },
                {
                    "channelID": 6,
                    "frequency": "65-85 MHz",
                    "type": "OFDMA",
                    "powerLevel": "49.0",
                    "profile_modulation": "256QAM",
                },
            ],
        )

        result = analyze(data)

        ofdma = result["summary"]["signal_families"]["upstream"]["families"]["ofdma"]
        assert ofdma["modulation"]["health"] == "critical"
        assert ofdma["modulation"]["values"] == [
            {"value": "32QAM", "health": "critical"},
            {"value": "256QAM", "health": "good"},
        ]

    def test_downstream_family_health_cause_is_none_when_all_metrics_are_good(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        sc_qam = result["summary"]["signal_families"]["downstream"]["families"]["sc_qam"]
        assert sc_qam["health"] == "good"
        assert sc_qam["health_cause"] is None
        assert sc_qam["health_counts"] == {"good": 1, "tolerated": 0, "warning": 0, "critical": 0}
        assert sc_qam["health_driver"] is None

    def test_downstream_ofdm_family_counts_and_driver_explain_power_outlier(self):
        data = _make_data(
            ds31=[
                _make_ds31(193, power=9.1, mer="42.0"),
                {
                    "channelID": 194,
                    "frequency": "167 MHz",
                    "powerLevel": "-15.1",
                    "modulation": "1024QAM",
                    "mer": "33.0",
                },
            ],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        ofdm = result["summary"]["signal_families"]["downstream"]["families"]["ofdm"]
        assert ofdm["power"]["avg"] == -3.0
        assert ofdm["health"] == "critical"
        assert ofdm["health_cause"] == "power"
        assert ofdm["health_counts"] == {"good": 1, "tolerated": 0, "warning": 0, "critical": 1}
        assert ofdm["health_driver"] == {
            "channel_id": 194,
            "dimension": "power",
            "family": "ofdm",
            "direction": "downstream",
            "health": "critical",
            "unit": "dBmV",
            "value": -15.1,
        }

    @pytest.mark.parametrize(
        ("power", "expected_health"),
        [
            (-15.1, "critical"),
            (-15.0, "tolerated"),
            (-12.1, "tolerated"),
            (-12.0, "good"),
            (12.0, "good"),
            (12.1, "tolerated"),
            (15.0, "tolerated"),
            (15.1, "critical"),
        ],
    )
    def test_ofdm_power_boundaries_use_ofdm_family_profile(self, power, expected_health):
        data = _make_data(
            ds31=[_make_ds31(193, power=power, mer="38.0")],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        channel = result["ds_channels"][0]
        family = result["summary"]["signal_families"]["downstream"]["families"]["ofdm"]
        assert channel.get("power_health", "good") == expected_health
        assert family["power"]["health"] == expected_health

    def test_reported_ofdm_fixture_is_good_for_mer_and_power(self):
        data = _make_data(
            ds31=[
                _make_ds31(193, power=-2.6, mer="38.0"),
                _make_ds31(194, power=-8.1, mer="33.0"),
            ],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        channels = result["ds_channels"]
        family = result["summary"]["signal_families"]["downstream"]["families"]["ofdm"]
        assert [
            (channel["channel_id"], channel["power"], channel["snr"], channel["modulation"])
            for channel in channels
        ] == [
            (193, -2.6, 38.0, "4096QAM"),
            (194, -8.1, 33.0, "4096QAM"),
        ]
        assert [channel.get("snr_health", "good") for channel in channels] == ["good", "good"]
        assert family["mer"] == {
            "available": True,
            "min": 33.0,
            "avg": 35.5,
            "max": 38.0,
            "health": "good",
        }
        assert family["power"] == {
            "available": True,
            "min": -8.1,
            "avg": -5.3,
            "max": -2.6,
            "health": "good",
        }
        assert "snr_critical" not in result["summary"]["health_issues"]
        assert "ds_power_critical" not in result["summary"]["health_issues"]
        assert family["health"] == "good"
        assert family["health_cause"] is None
        assert result["summary"]["health"] == "good"
        assert family["health_driver"] is None

    def test_upstream_sc_qam_family_counts_and_driver_explain_modulation_outlier(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-35")],
            us30=[
                _make_us30(1, power=42.0, modulation="16QAM"),
                _make_us30(2, power=42.0, modulation="16QAM"),
                _make_us30(3, power=42.0, modulation="16QAM"),
                _make_us30(4, power=42.0, modulation="QPSK"),
            ],
        )

        result = analyze(data)

        sc_qam = result["summary"]["signal_families"]["upstream"]["families"]["sc_qam"]
        assert sc_qam["power"]["health"] == "good"
        assert sc_qam["modulation"]["health"] == "critical"
        assert sc_qam["health"] == "critical"
        assert sc_qam["health_cause"] == "modulation"
        assert sc_qam["health_counts"] == {"good": 0, "tolerated": 0, "warning": 3, "critical": 1}
        assert sc_qam["health_driver"] == {
            "channel_id": 4,
            "dimension": "modulation",
            "family": "sc_qam",
            "direction": "upstream",
            "health": "critical",
            "unit": None,
            "value": "QPSK",
        }

    def test_downstream_sc_qam_family_health_surfaces_snr_cause(self):
        data = _make_data(
            ds30=[_make_ds30(1, power=2.0, mse="-25")],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        sc_qam = result["summary"]["signal_families"]["downstream"]["families"]["sc_qam"]
        assert sc_qam["power"]["health"] == "good"
        assert sc_qam["snr"]["health"] == "critical"
        assert sc_qam["modulation"]["health"] == "good"
        assert sc_qam["health"] == "critical"
        assert sc_qam["health_cause"] == "snr"
        assert sc_qam["health_driver"] == {
            "channel_id": 1,
            "dimension": "snr",
            "family": "sc_qam",
            "direction": "downstream",
            "health": "critical",
            "unit": "dB",
            "value": 25.0,
        }

    def test_downstream_ofdm_family_health_surfaces_mer_cause(self):
        data = _make_data(
            ds31=[_make_ds31(100, power=5.0, mer="24.4")],
            us30=[_make_us30(1, power=42.0)],
        )

        result = analyze(data)

        ofdm = result["summary"]["signal_families"]["downstream"]["families"]["ofdm"]
        assert ofdm["power"]["health"] == "good"
        assert ofdm["mer"]["health"] == "critical"
        assert ofdm["modulation"]["health"] == "good"
        assert ofdm["health"] == "critical"
        assert ofdm["health_cause"] == "mer"
        assert ofdm["health_driver"] == {
            "channel_id": 100,
            "dimension": "mer",
            "family": "ofdm",
            "direction": "downstream",
            "health": "critical",
            "unit": "dB",
            "value": 24.4,
        }


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
