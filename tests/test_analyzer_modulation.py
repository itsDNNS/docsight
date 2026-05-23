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
