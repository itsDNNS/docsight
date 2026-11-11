"""Focused MQTT regressions for error-counter null and raw semantics."""

import json
from unittest.mock import MagicMock, call

from app.analyzer import analyze
from app.modules.mqtt.publisher import MQTTPublisher


def test_publish_data_preserves_raw_error_values_and_missing_channel_counter():
    publisher = object.__new__(MQTTPublisher)
    publisher.topic_prefix = "docsight"
    publisher.client = MagicMock()
    analysis = {
        "summary": {
            "health": "good",
            "health_issues": [],
            "ds_correctable_errors": None,
            "ds_uncorrectable_errors": 1000,
            "ds_comparable_correctable_errors": None,
            "ds_comparable_uncorrectable_errors": None,
            "ds_uncorr_pct": None,
        },
        "ds_channels": [{
            "channel_id": 100,
            "power": 0.0,
            "frequency": "159 MHz",
            "modulation": "OFDM",
            "snr": 38.0,
            "correctable_errors": None,
            "uncorrectable_errors": 1000,
            "docsis_version": "3.1",
            "health": "good",
        }],
        "us_channels": [],
    }

    publisher.publish_data(analysis)

    published = {call.args[0]: call.args[1] for call in publisher.client.publish.call_args_list}
    assert published["docsight/ds_correctable_errors"] == "None"
    assert published["docsight/ds_uncorrectable_errors"] == "1000"
    assert published["docsight/ds_uncorr_pct"] == "None"
    channel = json.loads(published["docsight/channel/ds_ch100"])
    assert channel["correctable_errors"] is None
    assert channel["uncorrectable_errors"] == 1000


def test_missing_gaming_measurement_clears_retained_score_and_grade():
    publisher = object.__new__(MQTTPublisher)
    publisher.topic_prefix = "docsight"
    publisher.client = MagicMock()
    analysis = {"summary": {"health": "good"}, "ds_channels": [], "us_channels": []}
    publisher.publish_data(analysis, gaming_index={"score": 100, "grade": "A"})
    publisher.client.publish.assert_any_call("docsight/gaming_quality_score", "100", retain=True)
    publisher.client.reset_mock()

    publisher.publish_data(analysis)
    publisher.client.publish.assert_has_calls([
        call("docsight/gaming_quality_score", "", retain=True),
        call("docsight/gaming_quality_grade", "", retain=True),
    ])


def test_only_low_upstream_power_publishes_marginal_health():
    publisher = object.__new__(MQTTPublisher)
    publisher.topic_prefix = "docsight"
    publisher.client = MagicMock()
    analysis = analyze({
        "channelDs": {"docsis30": [{
            "channelID": 1, "frequency": "602 MHz", "powerLevel": "3.0",
            "modulation": "256QAM", "mse": "-35.0", "corrErrors": 0, "nonCorrErrors": 0,
        }], "docsis31": []},
        "channelUs": {"docsis30": [{
            "channelID": 3, "frequency": "37 MHz", "powerLevel": "34.8",
            "modulation": "64QAM", "multiplex": "ATDMA",
        }], "docsis31": []},
    })

    publisher.publish_data(analysis)

    published = {call.args[0]: call.args[1] for call in publisher.client.publish.call_args_list}
    assert published["docsight/health"] == "marginal"
    assert published["docsight/health_details"] == "US power below ideal"
    assert json.loads(published["docsight/channel/us_ch3"])["health"] == "warning"
