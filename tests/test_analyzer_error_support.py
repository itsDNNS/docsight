"""Regression tests for DOCSIS error-counter support semantics."""

from app.analyzer import analyze


def test_unsupported_downstream_error_counters_remain_none_in_summary():
    result = analyze({
        "channelDs": {
            "docsis30": [{
                "channelID": "1",
                "frequency": "114 MHz",
                "powerLevel": "0.1",
                "mse": "-37.0",
                "modulation": "256QAM",
            }],
            "docsis31": [],
        },
        "channelUs": {"docsis30": [], "docsis31": []},
    })

    assert result["summary"]["errors_supported"] is False
    assert result["summary"]["ds_correctable_errors"] is None
    assert result["summary"]["ds_uncorrectable_errors"] is None


def test_supported_zero_downstream_error_counters_remain_zero_in_summary():
    result = analyze({
        "channelDs": {
            "docsis30": [{
                "channelID": "1",
                "frequency": "114 MHz",
                "powerLevel": "0.1",
                "mse": "-37.0",
                "modulation": "256QAM",
                "corrErrors": 0,
                "nonCorrErrors": 0,
            }],
            "docsis31": [],
        },
        "channelUs": {"docsis30": [], "docsis31": []},
    })

    assert result["summary"]["errors_supported"] is True
    assert result["summary"]["ds_correctable_errors"] == 0
    assert result["summary"]["ds_uncorrectable_errors"] == 0
