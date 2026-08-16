from app.aggregation import ThresholdContext, Window, aggregate_snapshot_period

WINDOW = Window("2026-05-01T00:00:00Z", "2026-05-05T00:00:00Z")


def _thresholds():
    return ThresholdContext.from_analyzer_snapshot({
        "thresholds": {
            "downstream_power": {},
            "upstream_power": {},
            "snr": {
                "_default": "256QAM",
                "256QAM": {"good_min": 33, "warning_min": 31, "critical_min": 29},
                "ofdm": {"good_min": 27, "warning_min": 25.5, "critical_min": 24.5},
            },
        },
        "profile": {"id": "test", "version": "1"},
    })


def _snapshot(timestamp, **summary):
    return {
        "timestamp": timestamp,
        "summary": {"health": "good", **summary},
        "ds_channels": [],
        "us_channels": [],
    }


def test_semantic_nulls_supported_zero_and_metric_coverage_are_distinct():
    snapshots = [
        _snapshot(
            "2026-05-01T00:00:00Z",
            ds_power_avg=0,
            ds_power_max=0,
            ds_uncorrectable_errors=0,
            ds_correctable_errors=0,
        ),
        _snapshot(
            "2026-05-02T00:00:00Z",
            ds_power_avg=None,
            ds_power_max=None,
            ds_uncorrectable_errors=None,
            ds_correctable_errors=None,
        ),
        _snapshot(
            "2026-05-03T00:00:00Z",
            errors_supported=False,
            ds_uncorrectable_errors=99,
            ds_correctable_errors=99,
        ),
        _snapshot(
            "2026-05-04T00:00:00Z",
            ds_power_avg="invalid",
            ds_power_max="invalid",
            ds_uncorrectable_errors="invalid",
            ds_correctable_errors=float("inf"),
        ),
        _snapshot("2026-05-05T00:00:00Z"),
    ]

    aggregate = aggregate_snapshot_period(snapshots, window=WINDOW, thresholds=_thresholds())

    assert aggregate["averages"]["ds_power"] == 0
    assert aggregate["worst"]["ds_power_max"] == 0
    assert aggregate["worst"]["ds_uncorrectable_max"] == 0
    assert aggregate["metric_coverage"]["ds_power"] == {
        "samples": 1,
        "nulls": 1,
        "unsupported": 0,
        "invalid": 1,
        "missing": 2,
        "total": 5,
    }
    assert aggregate["metric_coverage"]["ds_power_max"] == {
        "samples": 1,
        "nulls": 1,
        "unsupported": 0,
        "invalid": 1,
        "missing": 2,
        "total": 5,
    }
    assert aggregate["metric_coverage"]["ds_uncorrectable_max"] == {
        "samples": 1,
        "nulls": 1,
        "unsupported": 1,
        "invalid": 1,
        "missing": 1,
        "total": 5,
    }
    assert aggregate["samples"][2]["uncorr_errors"] is None

    state_keys = {"samples", "nulls", "unsupported", "invalid", "missing"}
    raw_metrics = {
        "ds_power",
        "ds_snr",
        "us_power",
        "ds_power_max",
        "ds_power_min",
        "us_power_max",
        "ds_snr_min",
        "ds_uncorrectable_max",
        "ds_correctable_max",
    }
    assert raw_metrics <= aggregate["metric_coverage"].keys()
    for coverage in aggregate["metric_coverage"].values():
        assert set(coverage) == state_keys | {"total"}
        assert all(type(coverage[key]) is int for key in coverage)
        assert sum(coverage[key] for key in state_keys) == coverage["total"] == 5


def test_abs_magnitude_worst_and_supplying_channel_warning_threshold_are_preserved():
    first = _snapshot(
        "2026-05-01T00:00:00Z", ds_power_max=10, ds_power_min=-4, ds_snr_min=30
    )
    first["ds_channels"] = [{
        "channel_id": 3,
        "modulation": "256QAM",
        "snr": 30,
        "health": "critical",
    }]
    second = _snapshot(
        "2026-05-02T00:00:00Z", ds_power_max=-12, ds_power_min=8, ds_snr_min=32
    )

    aggregate = aggregate_snapshot_period([second, first], window=WINDOW, thresholds=_thresholds())

    assert aggregate["worst"]["ds_power_max"] == -12
    assert aggregate["worst"]["ds_power_min"] == 8
    assert aggregate["worst"]["ds_snr_min"] == 30
    assert aggregate["worst"]["ds_snr_warn_min"] == 31
    assert aggregate["worst_channels"]["ds"] == [(3, 1)]


def test_duplicate_timestamps_keep_multiplicity_and_content_tiebreak_selects_latest():
    first = _snapshot("2026-05-02T00:00:00Z", ds_power_avg=1, health="good")
    second = _snapshot("2026-05-02T00:00:00Z", ds_power_avg=2, health="critical")

    left = aggregate_snapshot_period([first, second, first], window=WINDOW, thresholds=_thresholds())
    right = aggregate_snapshot_period([first, first, second], window=WINDOW, thresholds=_thresholds())

    assert left == right
    assert left["snapshot_count"] == 3
    assert sum(left["health_distribution"].values()) == 3
    assert left["latest_snapshot"] in (first, second)


def test_good_period_average_keeps_the_stored_critical_channel_as_diagnostic_driver():
    snapshot = _snapshot(
        "2026-05-01T00:00:00Z",
        health="good",
        ds_power_avg=0.0,
    )
    snapshot["analysis_meta"] = {
        "analyzer_schema": 3,
        "app_version": "2026.7-test",
        "threshold_profile": {"id": "unavailable", "version": "1"},
    }
    snapshot["ds_channels"] = [{
        "channel_id": 41,
        "channel_family": "sc_qam",
        "modulation": "256QAM",
        "power": 12.0,
        "power_health": "critical",
        "health": "critical",
        "health_detail": "power critical high",
    }]

    aggregate = aggregate_snapshot_period([snapshot], window=WINDOW, thresholds=_thresholds())

    assert aggregate["health_distribution"] == {"good": 1}
    assert aggregate["averages"]["ds_power"] == 0.0
    assert len(aggregate["diagnostic_notes"]) == 1
    driver = aggregate["diagnostic_notes"][0]
    assert driver["type"] == "ds_power_high"
    assert driver["channel_id"] == 41
    assert driver["metric"] == "downstream power"
    assert driver["value"] == 12.0
    assert driver["unit"] == "dBmV"
    assert driver["severity"] == "critical"
