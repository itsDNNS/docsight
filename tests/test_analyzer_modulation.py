"""Regression tests for DOCSIS modulation health semantics."""

from app.analyzer import analyze


def test_docsis_30_downstream_64qam_is_healthy_not_marginal():
    """64QAM is valid for DOCSIS 3.0 downstream and must not create a DS warning."""
    result = analyze({
        "channelDs": {
            "docsis30": [{
                "channelID": "65",
                "frequency": "698 MHz",
                "powerLevel": "0.4",
                "mse": "-36.3",
                "modulation": "64QAM",
                "corrErrors": 0,
                "nonCorrErrors": 0,
            }],
            "docsis31": [],
        },
        "channelUs": {"docsis30": [], "docsis31": []},
    })

    channel = result["ds_channels"][0]
    assert channel.get("modulation_health") == "good"
    assert channel["health"] == "good"
    assert "modulation warning" not in channel["health_detail"]
    assert "ds_modulation_marginal" not in result["summary"]["health_issues"]
    assert result["summary"]["health"] == "good"


def test_docsis_31_downstream_ofdm_capacity_is_not_estimated_from_qam_profile():
    result = analyze({
        "channelDs": {
            "docsis30": [
                {
                    "channelID": "1",
                    "frequency": "602 MHz",
                    "powerLevel": "0.4",
                    "mse": "-36.3",
                    "modulation": "256QAM",
                    "corrErrors": 0,
                    "nonCorrErrors": 0,
                },
                {
                    "channelID": "2",
                    "frequency": "610 MHz",
                    "powerLevel": "0.5",
                    "mse": "-36.1",
                    "modulation": "256QAM",
                    "corrErrors": 0,
                    "nonCorrErrors": 0,
                },
            ],
            "docsis31": [{
                "channelID": "33",
                "frequency": "134.975 - 324.975",
                "powerLevel": "3.1",
                "mer": "38.5",
                "type": "OFDM",
                "modulation": "4096QAM",
                "symbolRate": 25000,
            }],
        },
        "channelUs": {"docsis30": [], "docsis31": []},
    })

    assert result["ds_channels"][0]["theoretical_bitrate"] == 55.62
    assert result["ds_channels"][1]["theoretical_bitrate"] == 55.62
    assert result["ds_channels"][2]["theoretical_bitrate"] is None
    assert result["summary"]["ds_capacity_mbps"] == 111.2
    assert result["summary"]["capacity_coverage"]["downstream"] == {
        "calculated": 2,
        "total": 3,
        "unsupported": 1,
    }


def test_upstream_capacity_compatibility_and_unknown_coverage():
    result = analyze({
        "channelDs": {"docsis30": [], "docsis31": []},
        "channelUs": {
            "docsis30": [{
                "channelID": "1",
                "frequency": "37 MHz",
                "powerLevel": "42.0",
                "modulation": "64QAM",
            }],
            "docsis31": [{
                "channelID": "5",
                "frequency": "18 - 44 MHz",
                "powerLevel": "45.0",
                "type": "OFDMA",
                "modulation": "1024QAM",
                "profile_modulation": "1024QAM",
                "symbolRate": 1000,
            }],
        },
    })

    assert result["us_channels"][0]["theoretical_bitrate"] == 30.72
    assert result["us_channels"][1]["theoretical_bitrate"] is None
    assert result["summary"]["us_capacity_mbps"] == 30.7
    assert result["summary"]["capacity_coverage"]["upstream"] == {
        "calculated": 1,
        "total": 2,
        "unsupported": 1,
    }
