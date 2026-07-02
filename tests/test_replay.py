"""Tests for replaying stored raw snapshot evidence."""

from app.analyzer import analyze
from app.replay import replay_snapshot
from app.storage import SnapshotStorage


def _storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "replay.db"), max_days=7)


def test_replay_snapshot_matches_fritz_style_payload(tmp_path):
    storage = _storage(tmp_path)
    raw_payload = {
        "channelDs": {
            "docsis30": [
                {
                    "channelID": 1,
                    "frequency": "602 MHz",
                    "powerLevel": "2.5",
                    "modulation": "256QAM",
                    "mse": "-38.0",
                    "corrErrors": 10,
                    "nonCorrErrors": 0,
                    "symbolRate": 6952,
                }
            ],
            "docsis31": [],
        },
        "channelUs": {
            "docsis30": [
                {
                    "channelID": 1,
                    "frequency": "45 MHz",
                    "powerLevel": "42.0",
                    "modulation": "64QAM",
                    "multiplex": "ATDMA",
                    "symbolRate": 5120,
                }
            ],
            "docsis31": [],
        },
    }
    analysis = analyze(raw_payload)

    storage.save_snapshot(analysis, raw_data=raw_payload)
    timestamp = storage.get_snapshot_list()[0]
    comparison = replay_snapshot(storage, timestamp)

    assert comparison["available"] is True
    assert comparison["matches"] is True
    assert comparison["differences"] == []


def test_replay_snapshot_matches_flat_payload(tmp_path):
    storage = _storage(tmp_path)
    raw_payload = {
        "docsis": "3.1",
        "downstream": [
            {
                "channelID": 193,
                "frequency": "794 MHz",
                "powerLevel": "1.0",
                "type": "OFDM",
                "modulation": "OFDM",
                "mer": "40.0",
                "corrErrors": 0,
                "nonCorrErrors": 0,
            }
        ],
        "upstream": [
            {
                "channelID": 9,
                "frequency": "37 MHz",
                "powerLevel": "43.0",
                "type": "OFDMA",
                "modulation": "OFDMA",
                "multiplex": "OFDMA",
            }
        ],
    }
    analysis = analyze(raw_payload)

    storage.save_snapshot(analysis, raw_data=raw_payload)
    timestamp = storage.get_snapshot_list()[0]
    comparison = replay_snapshot(storage, timestamp)

    assert comparison["available"] is True
    assert comparison["matches"] is True
    assert comparison["differences"] == []


def test_replay_snapshot_reports_missing_raw_payload(tmp_path):
    storage = _storage(tmp_path)
    raw_payload = {
        "docsis": "3.1",
        "downstream": [],
        "upstream": [],
    }
    storage.save_snapshot(analyze(raw_payload))
    timestamp = storage.get_snapshot_list()[0]

    comparison = replay_snapshot(storage, timestamp)

    assert comparison["available"] is False
    assert comparison["matches"] is False
    assert comparison["differences"] == ["raw_data_missing"]
    assert comparison["replayed"] is None


def test_replay_snapshot_reports_changed_analysis(tmp_path):
    storage = _storage(tmp_path)
    raw_payload = {
        "docsis": "3.1",
        "downstream": [],
        "upstream": [],
    }
    stored = analyze(raw_payload)
    storage.save_snapshot(stored, raw_data=raw_payload)
    timestamp = storage.get_snapshot_list()[0]

    def changed_analyzer(_raw):
        replayed = analyze(raw_payload)
        replayed["summary"] = dict(replayed["summary"])
        replayed["summary"]["health"] = "critical"
        return replayed

    comparison = replay_snapshot(storage, timestamp, analyzer_fn=changed_analyzer)

    assert comparison["available"] is True
    assert comparison["matches"] is False
    assert comparison["differences"] == ["summary"]
