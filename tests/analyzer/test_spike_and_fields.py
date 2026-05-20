"""Tests for spike handling and metric health fields."""

import pytest
from typing import cast
from unittest.mock import patch
from app import analyzer
from app.analyzer import analyze, _parse_float, _parse_qam_order, _resolve_modulation, _channel_bitrate_mbps, _metric_healths
from app.types import AnalysisResult


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
    @patch("app.analyzer.utc_now")
    def test_expired_spike_preserves_uncomputable_uncorr_pct(self, mock_now):
        """Spike expiry must not turn partial/unsupported error rates into fake 0%."""
        from app.analyzer import apply_spike_suppression
        mock_now.return_value = "2026-03-01T15:00:00Z"
        analysis = self._make_analysis_with_uncorr(uncorr_pct=None)
        analysis["summary"]["ds_correctable_errors"] = None
        analysis["summary"]["ds_uncorrectable_errors"] = 1000000
        analysis["summary"]["errors_supported"] = True

        apply_spike_suppression(analysis, "2026-02-27T14:00:00Z")

        assert analysis["summary"]["ds_uncorr_pct"] is None
        assert "uncorr_errors_critical" not in analysis["summary"]["health_issues"]
        assert analysis["summary"]["spike_suppression"]["active"] is True

    @patch("app.analyzer.utc_now")
    def test_expired_spike_does_not_hide_new_baseline_growth(self, mock_now):
        """Expired old spikes must not suppress new DOCSight-observed growth."""
        from app.analyzer import apply_cumulative_error_baseline, apply_spike_suppression
        mock_now.return_value = "2026-03-01T15:00:00Z"
        previous = {
            "summary": {
                "health": "good",
                "health_issues": [],
                "ds_uncorr_pct": 0.0,
                "ds_correctable_errors": 155000,
                "ds_uncorrectable_errors": 1000500,
                "errors_supported": True,
                "error_baseline": {
                    "active": True,
                    "basis": "docsight_baseline_delta",
                    "counter_reset": False,
                    "ds_correctable_baseline": 155000,
                    "ds_uncorrectable_baseline": 1000000,
                    "ds_correctable_recent_delta": 0,
                    "ds_uncorrectable_recent_delta": 500,
                    "ds_correctable_delta": 0,
                    "ds_uncorrectable_delta": 500,
                },
            },
            "ds_channels": [],
            "us_channels": [],
        }
        analysis = {
            "summary": {
                "health": "critical",
                "health_issues": ["uncorr_errors_critical"],
                "ds_uncorr_pct": 86.6,
                "ds_correctable_errors": 155000,
                "ds_uncorrectable_errors": 1001000,
                "errors_supported": True,
            },
            "ds_channels": [],
            "us_channels": [],
        }

        apply_cumulative_error_baseline(cast(AnalysisResult, analysis), cast(AnalysisResult, previous), recent_spike_active=False)
        apply_spike_suppression(cast(AnalysisResult, analysis), "2026-02-27T14:00:00Z")

        assert analysis["summary"]["ds_uncorr_pct"] == 100.0
        assert "uncorr_errors_critical" in analysis["summary"]["health_issues"]
        assert "spike_suppression" not in analysis["summary"]

    @patch("app.analyzer.utc_now")
    def test_expired_spike_still_suppresses_old_baseline_delta(self, mock_now):
        """An expired observed spike is suppressed when no newer errors grew."""
        from app.analyzer import apply_cumulative_error_baseline, apply_spike_suppression
        mock_now.return_value = "2026-03-01T15:00:00Z"
        previous = cast(AnalysisResult, {
            "summary": {
                "health": "critical",
                "health_issues": ["uncorr_errors_critical"],
                "ds_uncorr_pct": 100.0,
                "ds_correctable_errors": 155000,
                "ds_uncorrectable_errors": 1001000,
                "errors_supported": True,
                "error_baseline": {
                    "active": True,
                    "basis": "docsight_baseline_delta",
                    "counter_reset": False,
                    "ds_correctable_baseline": 155000,
                    "ds_uncorrectable_baseline": 1000000,
                    "ds_correctable_recent_delta": 0,
                    "ds_uncorrectable_recent_delta": 1000,
                    "ds_correctable_delta": 0,
                    "ds_uncorrectable_delta": 1000,
                },
            },
            "ds_channels": [],
            "us_channels": [],
        })
        analysis = cast(AnalysisResult, {
            "summary": {
                "health": "critical",
                "health_issues": ["uncorr_errors_critical"],
                "ds_uncorr_pct": 86.6,
                "ds_correctable_errors": 155000,
                "ds_uncorrectable_errors": 1001000,
                "errors_supported": True,
            },
            "ds_channels": [],
            "us_channels": [],
        })

        apply_cumulative_error_baseline(analysis, previous, recent_spike_active=False)
        apply_spike_suppression(analysis, "2026-02-27T14:00:00Z")

        assert analysis["summary"]["ds_uncorr_pct"] == 0.0
        assert "uncorr_errors_critical" not in analysis["summary"]["health_issues"]
        assert "spike_suppression" in analysis["summary"]
        assert analysis["summary"].get("spike_suppression", {})["active"] is True


class TestCumulativeErrorBaseline:
    """Tests for health scoring against observed cumulative counter growth."""

    def _analysis(self, corr, uncorr, health="critical", issues=None, baseline=None):
        summary = {
            "health": health,
            "health_issues": issues if issues is not None else ["uncorr_errors_critical"],
            "ds_uncorr_pct": round((uncorr / (corr + uncorr)) * 100, 2) if corr + uncorr else 0.0,
            "ds_correctable_errors": corr,
            "ds_uncorrectable_errors": uncorr,
            "errors_supported": True,
        }
        if baseline is not None:
            base_corr, base_uncorr = baseline
            summary["error_baseline"] = {
                "active": True,
                "basis": "docsight_baseline_delta",
                "counter_reset": False,
                "ds_correctable_baseline": base_corr,
                "ds_uncorrectable_baseline": base_uncorr,
                "ds_correctable_recent_delta": 0,
                "ds_uncorrectable_recent_delta": 0,
                "ds_correctable_delta": corr - base_corr,
                "ds_uncorrectable_delta": uncorr - base_uncorr,
            }
        return {
            "summary": summary,
            "ds_channels": [],
            "us_channels": [],
        }

    def test_high_first_observed_counters_recover_when_followup_is_flat(self):
        from app.analyzer import apply_cumulative_error_baseline
        previous = self._analysis(corr=155000, uncorr=1000000)
        current = self._analysis(corr=155000, uncorr=1000000)

        apply_cumulative_error_baseline(current, previous, recent_spike_active=False)

        summary = current["summary"]
        assert summary["ds_correctable_errors"] == 155000
        assert summary["ds_uncorrectable_errors"] == 1000000
        assert summary["ds_uncorr_pct"] == 0.0
        assert "uncorr_errors_critical" not in summary["health_issues"]
        assert summary["health"] == "good"
        assert summary["error_baseline"]["active"] is True
        assert summary["error_baseline"]["ds_correctable_baseline"] == 155000
        assert summary["error_baseline"]["ds_uncorrectable_baseline"] == 1000000
        assert summary["error_baseline"]["ds_correctable_delta"] == 0
        assert summary["error_baseline"]["ds_uncorrectable_delta"] == 0

    def test_growth_after_baseline_still_affects_health(self):
        from app.analyzer import apply_cumulative_error_baseline
        previous = self._analysis(corr=155000, uncorr=1000000)
        current = self._analysis(corr=155000, uncorr=1002000)

        apply_cumulative_error_baseline(current, previous, recent_spike_active=False)

        summary = current["summary"]
        assert summary["ds_uncorr_pct"] == 100.0
        assert "uncorr_errors_critical" in summary["health_issues"]
        assert summary["health"] == "critical"
        assert summary["error_baseline"]["ds_uncorrectable_delta"] == 2000

    def test_gradual_growth_accumulates_since_docsight_baseline(self):
        from app.analyzer import apply_cumulative_error_baseline
        previous = self._analysis(
            corr=155000,
            uncorr=1000500,
            health="good",
            issues=[],
            baseline=(155000, 1000000),
        )
        current = self._analysis(corr=155000, uncorr=1001000)

        apply_cumulative_error_baseline(current, previous, recent_spike_active=False)

        summary = current["summary"]
        assert summary["ds_uncorr_pct"] == 100.0
        assert "uncorr_errors_critical" in summary["health_issues"]
        assert summary["health"] == "critical"
        assert summary["error_baseline"]["ds_uncorrectable_baseline"] == 1000000
        assert summary["error_baseline"]["ds_uncorrectable_delta"] == 1000

    def test_mixed_growth_scores_from_docsight_baseline(self):
        from app.analyzer import apply_cumulative_error_baseline
        previous = self._analysis(
            corr=155400,
            uncorr=1000600,
            health="good",
            issues=[],
            baseline=(155000, 1000000),
        )
        current = self._analysis(corr=156000, uncorr=1001000)

        apply_cumulative_error_baseline(current, previous, recent_spike_active=False)

        summary = current["summary"]
        assert summary["ds_uncorr_pct"] == 50.0
        assert "uncorr_errors_critical" in summary["health_issues"]
        assert summary["error_baseline"]["ds_correctable_delta"] == 1000
        assert summary["error_baseline"]["ds_uncorrectable_delta"] == 1000

    def test_counter_reset_establishes_fresh_baseline_without_negative_deltas(self):
        from app.analyzer import apply_cumulative_error_baseline
        previous = self._analysis(corr=155000, uncorr=1000000)
        current = self._analysis(corr=50, uncorr=0, health="good", issues=[])

        apply_cumulative_error_baseline(current, previous, recent_spike_active=False)

        summary = current["summary"]
        assert summary["ds_uncorr_pct"] == 0.0
        assert summary["health"] == "good"
        assert summary["error_baseline"]["counter_reset"] is True
        assert summary["error_baseline"]["ds_correctable_delta"] == 0
        assert summary["error_baseline"]["ds_uncorrectable_delta"] == 0

    def test_recent_observed_spike_keeps_existing_spike_expiry_path(self):
        from app.analyzer import apply_cumulative_error_baseline
        previous = self._analysis(corr=155000, uncorr=1000000)
        current = self._analysis(corr=155000, uncorr=1000000)

        apply_cumulative_error_baseline(current, previous, recent_spike_active=True)

        summary = current["summary"]
        assert summary["ds_uncorr_pct"] == 86.58
        assert "uncorr_errors_critical" in summary["health_issues"]
        assert "error_baseline" not in summary


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
