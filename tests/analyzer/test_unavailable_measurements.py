"""Regression tests for unavailable DOCSIS measurement semantics."""

import pytest

from app.analyzer import analyze
from tests.analyzer.factories import make_data, make_ds30, make_us30


def test_missing_and_invalid_power_values_remain_unavailable_and_excluded_from_summary():
    result = analyze({
        "channelDs": {
            "docsis30": [
                {
                    "channelID": "1",
                    "frequency": "602 MHz",
                    "modulation": "256QAM",
                    "mse": "-36.0",
                    "corrErrors": 0,
                    "nonCorrErrors": 0,
                },
                {
                    "channelID": "2",
                    "frequency": "610 MHz",
                    "powerLevel": "not-a-number",
                    "modulation": "256QAM",
                    "mse": "-36.0",
                    "corrErrors": 0,
                    "nonCorrErrors": 0,
                },
                {
                    "channelID": "3",
                    "frequency": "618 MHz",
                    "powerLevel": "4.0",
                    "modulation": "256QAM",
                    "mse": "-36.0",
                    "corrErrors": 0,
                    "nonCorrErrors": 0,
                },
            ],
            "docsis31": [
                {
                    "channelID": "33",
                    "frequency": "134.975 - 324.975 MHz",
                    "powerLevel": "bad-value",
                    "type": "OFDM",
                    "modulation": "4096QAM",
                    "mer": "38.0",
                }
            ],
        },
        "channelUs": {
            "docsis30": [
                {
                    "channelID": "1",
                    "frequency": "37 MHz",
                    "modulation": "64QAM",
                    "multiplex": "ATDMA",
                },
                {
                    "channelID": "2",
                    "frequency": "45 MHz",
                    "powerLevel": "invalid",
                    "modulation": "64QAM",
                    "multiplex": "ATDMA",
                },
                {
                    "channelID": "3",
                    "frequency": "52 MHz",
                    "powerLevel": "42.0",
                    "modulation": "64QAM",
                    "multiplex": "ATDMA",
                },
            ],
            "docsis31": [
                {
                    "channelID": "5",
                    "frequency": "18 - 44 MHz",
                    "powerLevel": "bad-value",
                    "type": "OFDMA",
                    "modulation": "OFDMA",
                    "profile_modulation": "256QAM",
                    "multiplex": "OFDMA",
                }
            ],
        },
    })

    ds_by_id = {channel["channel_id"]: channel for channel in result["ds_channels"]}
    us_by_id = {channel["channel_id"]: channel for channel in result["us_channels"]}

    assert ds_by_id[1]["power"] is None
    assert ds_by_id[2]["power"] is None
    assert ds_by_id[33]["power"] is None
    assert "power" not in ds_by_id[1]["health_detail"]
    assert "power" not in ds_by_id[2]["health_detail"]
    assert "power" not in ds_by_id[33]["health_detail"]

    assert us_by_id[1]["power"] is None
    assert us_by_id[2]["power"] is None
    assert us_by_id[5]["power"] is None
    assert "power" not in us_by_id[1]["health_detail"]
    assert "power" not in us_by_id[2]["health_detail"]
    assert "power" not in us_by_id[5]["health_detail"]

    assert result["summary"]["ds_power_min"] == 4.0
    assert result["summary"]["ds_power_max"] == 4.0
    assert result["summary"]["ds_power_avg"] == 4.0
    assert result["summary"]["us_power_min"] == 42.0
    assert result["summary"]["us_power_max"] == 42.0
    assert result["summary"]["us_power_avg"] == 42.0


def test_docsis_30_zero_mse_is_evaluated_as_real_snr_value():
    result = analyze({
        "channelDs": {
            "docsis30": [{
                "channelID": "1",
                "frequency": "602 MHz",
                "powerLevel": "2.0",
                "modulation": "256QAM",
                "mse": 0,
                "corrErrors": 0,
                "nonCorrErrors": 0,
            }],
            "docsis31": [],
        },
        "channelUs": {"docsis30": [], "docsis31": []},
    })

    channel = result["ds_channels"][0]
    assert channel["snr"] == 0.0
    assert channel.get("snr_health") == "critical"
    assert channel["health"] == "critical"
    assert "snr critical" in channel["health_detail"]
    assert "snr_critical" in result["summary"]["health_issues"]


@pytest.mark.parametrize(("data", "expected"), [
    (make_data(us30=[make_us30()]), {"ds_power": None, "ds_snr": None, "us_power": 42.0}),
    (make_data(ds30=[make_ds30()]), {"ds_power": 3.0, "ds_snr": 35.0, "us_power": None}),
    (make_data(ds30=[make_ds30(mse="n/a")], us30=[make_us30()]), {"ds_power": 3.0, "ds_snr": None, "us_power": 42.0}),
])
def test_summary_without_any_reported_value_is_unavailable_not_zero(data, expected):
    summary = analyze(data)["summary"]
    expected_fields = {f"{name}_{part}": value for name, value in expected.items() for part in ("min", "avg", "max")}

    assert {key: summary[key] for key in expected_fields} == expected_fields
