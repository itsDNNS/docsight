import hashlib
import json
import random

import pytest

from app.aggregation import (
    ThresholdContext,
    Window,
    aggregate_snapshot_period,
    derive_diagnostic_notes,
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
    permissive = derive_diagnostic_notes([_snapshot()], thresholds=_context((-20, 20)))
    restrictive = derive_diagnostic_notes([_snapshot()], thresholds=_context((-5, 5)))

    assert permissive == []
    assert restrictive[0]["type"] == "ds_power_high"


def test_analyzer_era_snapshot_does_not_fall_back_to_active_thresholds():
    first = derive_diagnostic_notes([_snapshot(analyzer_meta=True)], thresholds=_context((-20, 20)))
    second = derive_diagnostic_notes([_snapshot(analyzer_meta=True)], thresholds=_context((-5, 5)))

    assert first == second
    assert "deviation_pct" not in first[0]


@pytest.mark.parametrize(("power", "expected"), [
    (34.9, [("us_power_low", "spec_min", 35.0)]),
    (53.1, [("us_power_high", "spec_max", 53.0)]),
    (35.0, []),
    (53.0, []),
])
def test_legacy_upstream_power_falls_back_to_default_critical_bounds(power, expected):
    snapshot = {**_snapshot(), "ds_channels": [], "us_channels": [{"channel_id": 1, "power": power}]}

    notes = derive_diagnostic_notes([snapshot], thresholds=_context((-20, 20)))

    assert [
        (note["type"], key, note[key]) for note in notes for key in ("spec_min", "spec_max") if key in note
    ] == expected


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
