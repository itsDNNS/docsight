import hashlib
import json
import random

from app.aggregation import (
    ThresholdContext,
    Window,
    aggregate_snapshot_period,
    derive_historical,
)


def _context(ds_critical):
    return ThresholdContext.from_analyzer_snapshot({
        "thresholds": {
            "downstream_power": {
                "_default": "256QAM",
                "256QAM": {
                    "good": list(ds_critical),
                    "warning": list(ds_critical),
                    "critical": list(ds_critical),
                },
            },
            "upstream_power": {},
            "snr": {},
        },
        "profile": {"id": "injected", "version": "1"},
    })


def _snapshot(*, analyzer_meta=False):
    snapshot = {
        "timestamp": "2026-05-01T00:00:00Z",
        "summary": {"health": "critical"},
        "ds_channels": [{
            "channel_id": 7,
            "modulation": "256QAM",
            "power": 12.0,
            "health": "critical",
        }],
        "us_channels": [],
    }
    if analyzer_meta:
        snapshot["analysis_meta"] = {
            "analyzer_schema": 3,
            "threshold_profile": {"id": "missing", "version": "1"},
        }
        snapshot["ds_channels"][0].update({
            "power_health": "critical",
            "health_detail": "power critical high",
        })
    return snapshot


def test_legacy_fallback_uses_only_the_injected_threshold_context():
    permissive = derive_historical([_snapshot()], thresholds=_context((-20, 20)))
    restrictive = derive_historical([_snapshot()], thresholds=_context((-5, 5)))

    assert permissive["diagnostic_notes"] == []
    assert restrictive["diagnostic_notes"][0]["type"] == "ds_power_high"


def test_analyzer_era_snapshot_does_not_fall_back_to_active_thresholds():
    first = derive_historical([_snapshot(analyzer_meta=True)], thresholds=_context((-20, 20)))
    second = derive_historical([_snapshot(analyzer_meta=True)], thresholds=_context((-5, 5)))

    assert first == second
    assert "deviation_pct" not in first["diagnostic_notes"][0]


def test_aggregate_provenance_is_counted_sanitized_and_permutation_stable():
    shared_meta = {
        "analyzer_schema": 3,
        "app_version": "2026.7-test",
        "threshold_profile": {"id": "builtin.default", "version": "1.1.0"},
        "locale": "private-locale",
    }
    snapshots = [
        {
            "timestamp": "2026-05-01T00:00:00Z",
            "summary": {"health": "good"},
            "analysis_meta": shared_meta,
            "raw_data": {"password": "secret"},
            "ds_channels": [],
            "us_channels": [],
        },
        {
            "timestamp": "2026-05-02T00:00:00Z",
            "summary": {"health": "good"},
            "analysis_meta": dict(shared_meta),
            "ds_channels": [],
            "us_channels": [],
        },
        {
            "timestamp": "2026-05-03T00:00:00Z",
            "summary": {"health": "good"},
            "analysis_meta": {
                "analyzer_schema": 2,
                "app_version": "2026.6-test",
                "threshold_profile": {"id": "builtin.legacy", "version": "1.0.0"},
            },
            "ds_channels": [],
            "us_channels": [],
        },
        {
            "timestamp": "2026-05-04T00:00:00Z",
            "summary": {"health": "good"},
            "analysis_meta": None,
            "ds_channels": [],
            "us_channels": [],
        },
    ]
    context = _context((-20, 20))
    window = Window("2026-05-01T00:00:00Z", "2026-05-04T00:00:00Z")

    digests = set()
    provenance = None
    for seed in range(25):
        shuffled = list(snapshots)
        random.Random(seed).shuffle(shuffled)
        aggregate = aggregate_snapshot_period(shuffled, window=window, thresholds=context)
        provenance = aggregate["provenance"]
        encoded = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode()
        digests.add(hashlib.sha256(encoded).hexdigest())

    assert len(digests) == 1
    assert provenance == {
        "source": "stored_snapshots",
        "active_threshold_profile": {"id": "injected", "version": "1"},
        "stored_snapshot_analyzers": {
            "legacy_no_metadata": 1,
            "metadata": [
                {
                    "analyzer_schema": 2,
                    "app_version": "2026.6-test",
                    "threshold_profile": {"id": "builtin.legacy", "version": "1.0.0"},
                    "count": 1,
                },
                {
                    "analyzer_schema": 3,
                    "app_version": "2026.7-test",
                    "threshold_profile": {"id": "builtin.default", "version": "1.1.0"},
                    "count": 2,
                },
            ],
        },
    }
    analyzer_summary = provenance["stored_snapshot_analyzers"]
    assert analyzer_summary["legacy_no_metadata"] + sum(
        item["count"] for item in analyzer_summary["metadata"]
    ) == len(snapshots)
    serialized = json.dumps(provenance)
    assert "raw_data" not in serialized
    assert "secret" not in serialized
    assert "locale" not in serialized
    assert "private-locale" not in serialized
