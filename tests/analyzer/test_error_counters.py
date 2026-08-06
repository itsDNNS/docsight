"""Regression tests for downstream error-counter cohort semantics."""

from app.analyzer import analyze, apply_cumulative_error_baseline


def _data(*channels):
    return {
        "channelDs": {"docsis30": [ch for ch in channels if ch["docsis"] == "3.0"],
                      "docsis31": [ch for ch in channels if ch["docsis"] == "3.1"]},
        "channelUs": {"docsis30": [], "docsis31": []},
    }


def _channel(channel_id, docsis, corr, uncorr, *, family):
    channel = {
        "channelID": channel_id,
        "docsis": docsis,
        "frequency": f"{channel_id} MHz",
        "powerLevel": "0",
        "modulation": "256QAM" if family == "sc_qam" else "OFDM",
        "type": "SC-QAM" if family == "sc_qam" else "OFDM",
        "mse": "-35",
        "mer": "38",
    }
    if corr is not None:
        channel["corrErrors"] = corr
    if uncorr is not None:
        channel["nonCorrErrors"] = uncorr
    return channel


def test_mixed_support_preserves_raw_totals_and_scores_only_comparable_channels():
    result = analyze(_data(
        _channel(1, "3.0", 9900, 100, family="sc_qam"),
        _channel(100, "3.1", None, 1000, family="ofdm"),
    ))

    summary = result["summary"]
    assert summary["ds_correctable_errors"] == 9900
    assert summary["ds_uncorrectable_errors"] == 1100
    assert summary["ds_comparable_correctable_errors"] == 9900
    assert summary["ds_comparable_uncorrectable_errors"] == 100
    assert summary["ds_uncorr_pct"] == 1.0
    assert "uncorr_errors_critical" not in summary["health_issues"]
    assert summary["error_counter_coverage"] == {
        "total_channels": 2,
        "correctable_channels": 1,
        "uncorrectable_channels": 2,
        "comparable_channels": 1,
        "partial_channels": 1,
        "unsupported_channels": 0,
        "families": {
            "ofdm": {
                "total_channels": 1,
                "correctable_channels": 0,
                "uncorrectable_channels": 1,
                "comparable_channels": 0,
                "partial_channels": 1,
                "unsupported_channels": 0,
            },
            "sc_qam": {
                "total_channels": 1,
                "correctable_channels": 1,
                "uncorrectable_channels": 1,
                "comparable_channels": 1,
                "partial_channels": 0,
                "unsupported_channels": 0,
            },
        },
    }


def test_uncorrectable_only_support_keeps_raw_value_but_ratio_unknown():
    summary = analyze(_data(_channel(100, "3.1", None, 1000, family="ofdm")))["summary"]

    assert summary["ds_correctable_errors"] is None
    assert summary["ds_uncorrectable_errors"] == 1000
    assert summary["ds_comparable_correctable_errors"] is None
    assert summary["ds_comparable_uncorrectable_errors"] is None
    assert summary["ds_uncorr_pct"] is None


def test_disjoint_partial_support_does_not_create_a_cross_channel_ratio():
    summary = analyze(_data(
        _channel(1, "3.0", 2000, None, family="sc_qam"),
        _channel(100, "3.1", None, 3000, family="ofdm"),
    ))["summary"]

    assert summary["ds_correctable_errors"] == 2000
    assert summary["ds_uncorrectable_errors"] == 3000
    assert summary["ds_comparable_correctable_errors"] is None
    assert summary["ds_comparable_uncorrectable_errors"] is None
    assert summary["ds_uncorr_pct"] is None
    assert summary["error_counter_coverage"]["comparable_channels"] == 0
    assert summary["error_counter_coverage"]["partial_channels"] == 2


def test_supported_zero_is_not_treated_as_missing():
    summary = analyze(_data(
        _channel(1, "3.0", 0, 0, family="sc_qam"),
        _channel(100, "3.1", None, None, family="ofdm"),
    ))["summary"]

    assert summary["ds_correctable_errors"] == 0
    assert summary["ds_uncorrectable_errors"] == 0
    assert summary["ds_comparable_correctable_errors"] == 0
    assert summary["ds_comparable_uncorrectable_errors"] == 0
    assert summary["ds_uncorr_pct"] == 0.0
    assert summary["error_counter_coverage"]["comparable_channels"] == 1
    assert summary["error_counter_coverage"]["unsupported_channels"] == 1


def test_schema_3_baseline_uses_comparable_growth_and_keeps_raw_growth_separate():
    previous = analyze(_data(
        _channel(1, "3.0", 9900, 100, family="sc_qam"),
        _channel(100, "3.1", None, 1000, family="ofdm"),
    ))
    previous["analysis_meta"] = {"analyzer_schema": 3}
    current = analyze(_data(
        _channel(1, "3.0", 10800, 200, family="sc_qam"),
        _channel(100, "3.1", None, 3500, family="ofdm"),
    ))

    apply_cumulative_error_baseline(current, previous)

    baseline = current["summary"]["error_baseline"]
    assert current["summary"]["ds_uncorrectable_errors"] == 3700
    assert current["summary"]["ds_uncorr_pct"] == 10.0
    assert baseline["ds_comparable_correctable_recent_delta"] == 900
    assert baseline["ds_comparable_uncorrectable_recent_delta"] == 100
    assert baseline["ds_raw_uncorrectable_recent_delta"] == 2600


def test_uncorrectable_only_growth_stays_out_of_ratio_health():
    previous = analyze(_data(
        _channel(1, "3.0", 10000, 0, family="sc_qam"),
        _channel(100, "3.1", None, 1000, family="ofdm"),
    ))
    previous["analysis_meta"] = {"analyzer_schema": 3}
    current = analyze(_data(
        _channel(1, "3.0", 10000, 0, family="sc_qam"),
        _channel(100, "3.1", None, 3000, family="ofdm"),
    ))

    apply_cumulative_error_baseline(current, previous)

    summary = current["summary"]
    assert summary["ds_uncorrectable_errors"] == 3000
    assert summary["ds_uncorr_pct"] == 0.0
    assert "uncorr_errors_high" not in summary["health_issues"]
    assert "uncorr_errors_critical" not in summary["health_issues"]
    assert summary["error_baseline"]["ds_comparable_uncorrectable_recent_delta"] == 0
    assert summary["error_baseline"]["ds_raw_uncorrectable_recent_delta"] == 2000


def test_schema_2_predecessor_establishes_safe_schema_3_baseline():
    previous = analyze(_data(_channel(1, "3.0", 9900, 100, family="sc_qam")))
    previous["analysis_meta"] = {"analyzer_schema": 2}
    previous["summary"].pop("error_counter_coverage", None)
    previous["summary"].pop("ds_comparable_correctable_errors", None)
    previous["summary"].pop("ds_comparable_uncorrectable_errors", None)
    current = analyze(_data(_channel(1, "3.0", 10800, 200, family="sc_qam")))

    apply_cumulative_error_baseline(current, previous)

    baseline = current["summary"]["error_baseline"]
    assert baseline["counter_reset"] is False
    assert baseline["basis"] == "comparable_channel_baseline_delta"
    assert baseline["schema_baseline"] is True
    assert baseline["ds_comparable_correctable_delta"] == 0
    assert baseline["ds_comparable_uncorrectable_delta"] == 0
    assert current["summary"]["ds_uncorr_pct"] == 0.0
