import json

from app import analyzer
from app.aggregation import ThresholdContext


def test_public_resolvers_are_equivalent_to_existing_analyzer_helpers(monkeypatch):
    thresholds = {
        "downstream_power": {
            "_default": "64QAM",
            "64QAM": {"good": [-7, 7], "warning": [-9, 9], "critical": [-11, 11]},
            "ofdm": {"good": [-5, 5], "warning": [-8, 8], "critical": [-12, 12]},
        },
        "snr": {
            "_default": "64QAM",
            "64QAM": {"good_min": 29, "warning_min": 27, "critical_min": 25},
            "ofdm": {"good_min": 30, "warning_min": 28, "critical_min": 26},
        },
    }
    monkeypatch.setattr(analyzer, "_thresholds", thresholds)

    for modulation, family in ((None, None), ("64QAM", "sc_qam"), ("OFDM", "ofdm")):
        assert analyzer.resolve_ds_power_thresholds(
            modulation, channel_family=family, thresholds=thresholds
        ) == analyzer._get_ds_power_thresholds(modulation, channel_family=family)
        assert analyzer.resolve_snr_thresholds(
            modulation, channel_family=family, thresholds=thresholds
        ) == analyzer._get_snr_thresholds(modulation, channel_family=family)


def test_threshold_snapshot_and_context_are_independent_deep_copies(monkeypatch):
    source = {
        "downstream_power": {
            "_default": "256QAM",
            "256QAM": {"critical": [-8.0, 16.0]},
        }
    }
    monkeypatch.setattr(analyzer, "_thresholds", source)
    monkeypatch.setattr(analyzer, "_threshold_profile", {"id": "test", "version": "1"})

    snapshot = analyzer.threshold_snapshot()
    context = ThresholdContext.from_analyzer_snapshot(snapshot)
    before = json.dumps(dict(context.raw), sort_keys=True)
    source["downstream_power"]["256QAM"]["critical"][1] = 99
    snapshot["thresholds"]["downstream_power"]["256QAM"]["critical"][0] = -99

    assert json.dumps(dict(context.raw), sort_keys=True) == before
    assert context.profile_id == "test"
    assert context.profile_version == "1"
