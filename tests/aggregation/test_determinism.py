import hashlib
import json
import random

from app.aggregation import ThresholdContext, Window, aggregate_snapshot_period


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_one_hundred_seeded_permutations_have_one_digest_and_do_not_mutate_context():
    snapshots = [
        {
            "timestamp": f"2026-05-01T00:00:0{index % 3}Z",
            "summary": {"health": "good", "ds_power_avg": index, "ds_uncorrectable_errors": 0},
            "ds_channels": [],
            "us_channels": [],
        }
        for index in range(6)
    ]
    context = ThresholdContext.from_analyzer_snapshot({
        "thresholds": {"downstream_power": {}, "upstream_power": {}, "snr": {}},
        "profile": {"id": "test", "version": "1"},
    })
    before = _digest(dict(context.raw))
    window = Window("2026-05-01T00:00:00Z", "2026-05-01T23:59:59Z")
    digests = set()
    for seed in range(100):
        shuffled = list(snapshots)
        random.Random(seed).shuffle(shuffled)
        digests.add(_digest(aggregate_snapshot_period(shuffled, window=window, thresholds=context)))

    assert len(digests) == 1
    assert _digest(dict(context.raw)) == before
