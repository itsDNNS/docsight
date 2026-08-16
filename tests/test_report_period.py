"""Focused historical report derivation regressions."""

import io
from unittest.mock import patch

import pytest
from pypdf import PdfReader

from app.threshold_profiles import BUILTIN_THRESHOLD_PROFILES


def _pdf_text(pdf_bytes):
    return "\n".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(pdf_bytes)).pages
    )


def _snapshot(timestamp, *, health="good", ds_channels=None, us_channels=None, summary=None):
    return {
        "timestamp": timestamp,
        "summary": {"health": health, **(summary or {})},
        "ds_channels": ds_channels or [],
        "us_channels": us_channels or [],
    }


def _builtin_analysis_meta(version=None):
    profile = BUILTIN_THRESHOLD_PROFILES[0]
    return {
        "analyzer_schema": 3,
        "threshold_profile": {
            "id": profile["id"],
            "version": version if version is not None else profile["version"],
        },
    }


def _conflicting_thresholds(
    *, ds_critical=(-100.0, 100.0), us_critical=(0.0, 100.0), snr_critical_min=0.0
):
    return {
        "downstream_power": {
            "_default": "256QAM",
            "256QAM": {
                "good": list(ds_critical),
                "warning": list(ds_critical),
                "critical": list(ds_critical),
            },
            "ofdm": {
                "good": list(ds_critical),
                "warning": list(ds_critical),
                "critical": list(ds_critical),
            },
        },
        "upstream_power": {
            "_default": "sc_qam",
            "sc_qam": {
                "good": list(us_critical),
                "warning": list(us_critical),
                "critical": list(us_critical),
            },
            "ofdma": {
                "good": list(us_critical),
                "warning": list(us_critical),
                "critical": list(us_critical),
            },
        },
        "snr": {
            "_default": "256QAM",
            "256QAM": {
                "good_min": snr_critical_min,
                "warning_min": snr_critical_min,
                "critical_min": snr_critical_min,
            },
            "ofdm": {
                "good_min": snr_critical_min,
                "warning_min": snr_critical_min,
                "critical_min": snr_critical_min,
            },
        },
    }


def test_unavailable_community_profile_keeps_stored_critical_without_numeric_claim(monkeypatch):
    from app import analyzer
    from app.modules.reports.report import derive_historical_report_data

    snapshot = _snapshot(
        "2026-05-01T01:02:03Z",
        ds_channels=[{
            "channel_id": 4,
            "type": "SC-QAM",
            "modulation": "256QAM",
            "power": 10.0,
            "power_health": "critical",
            "health_detail": "power critical high",
        }],
    )
    snapshot["analysis_meta"] = {
        "analyzer_schema": 3,
        "threshold_profile": {"id": "community.strict", "version": "9.4.0"},
    }

    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds())
    permissive = derive_historical_report_data([snapshot])["diagnostic_notes"]
    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds(ds_critical=(-1.0, 1.0)))
    restrictive = derive_historical_report_data([snapshot])["diagnostic_notes"]

    assert permissive == restrictive
    assert len(permissive) == 1
    assert permissive[0]["type"] == "ds_power_high"
    assert permissive[0]["value"] == 10.0
    assert permissive[0]["observed_at"] == "2026-05-01T01:02:03Z"
    assert "spec_max" not in permissive[0]
    assert "spec_min" not in permissive[0]
    assert "deviation_pct" not in permissive[0]


@pytest.mark.parametrize("stored_health", ["good", "tolerated", "warning"])
def test_noncritical_stored_power_health_never_becomes_report_diagnosis(monkeypatch, stored_health):
    from app import analyzer
    from app.modules.reports.report import derive_historical_report_data

    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds(ds_critical=(-1.0, 1.0)))
    snapshot = _snapshot(
        "2026-05-01T00:00:00Z",
        ds_channels=[{
            "channel_id": 1,
            "type": "SC-QAM",
            "modulation": "256QAM",
            "power": 30.0,
            "power_health": stored_health,
            "health_detail": f"power {stored_health} high",
        }],
    )
    snapshot["analysis_meta"] = _builtin_analysis_meta()

    assert derive_historical_report_data([snapshot])["diagnostic_notes"] == []


@pytest.mark.parametrize(
    ("direction", "channel", "metric", "value", "detail", "expected_type", "expected_spec"),
    [
        ("ds", {"type": "SC-QAM", "modulation": "256QAM"}, "power", 20.0, "power critical high", "ds_power_high", 16.0),
        ("ds", {"type": "SC-QAM", "modulation": "256QAM"}, "power", -10.0, "power critical low", "ds_power_low", -8.0),
        ("ds", {"type": "OFDM", "docsis_version": "3.1", "modulation": "4096QAM"}, "snr", 20.0, "snr critical", "snr_low", 24.5),
        ("us", {"type": "SC-QAM", "docsis_version": "3.0"}, "power", 60.0, "power critical high", "us_power_high", 53.0),
        ("us", {"type": "OFDMA", "docsis_version": "3.1"}, "power", 30.0, "power critical low", "us_power_low", 38.0),
    ],
)
def test_exact_builtin_profile_reconstructs_family_threshold_and_direction(
    monkeypatch, direction, channel, metric, value, detail, expected_type, expected_spec
):
    from app import analyzer
    from app.modules.reports.report import derive_historical_report_data

    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds())
    stored_channel = {
        "channel_id": 8,
        **channel,
        metric: value,
        f"{metric}_health": "critical",
        "health_detail": detail,
    }
    snapshot = _snapshot(
        "2026-05-01T00:00:00Z",
        ds_channels=[stored_channel] if direction == "ds" else [],
        us_channels=[stored_channel] if direction == "us" else [],
    )
    snapshot["analysis_meta"] = _builtin_analysis_meta()

    note = derive_historical_report_data([snapshot])["diagnostic_notes"][0]

    assert note["type"] == expected_type
    assert note.get("spec_max", note.get("spec_min")) == expected_spec
    assert note["deviation_pct"] > 0


def test_builtin_profile_version_mismatch_uses_neutral_stored_critical(monkeypatch):
    from app import analyzer
    from app.modules.reports.report import derive_historical_report_data

    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds(ds_critical=(-1.0, 1.0)))
    snapshot = _snapshot(
        "2026-05-01T00:00:00Z",
        ds_channels=[{
            "channel_id": 1,
            "type": "SC-QAM",
            "modulation": "256QAM",
            "power": 30.0,
            "power_health": "critical",
            "health_detail": "power critical high",
        }],
    )
    snapshot["analysis_meta"] = _builtin_analysis_meta(version="0.0.0-mismatch")

    note = derive_historical_report_data([snapshot])["diagnostic_notes"][0]

    assert note["type"] == "ds_power_high"
    assert "spec_max" not in note
    assert "deviation_pct" not in note


def test_analyzer_snapshot_missing_sparse_good_health_ignores_active_thresholds(monkeypatch):
    from app import analyzer
    from app.modules.reports.report import derive_historical_report_data

    monkeypatch.setattr(
        analyzer,
        "_thresholds",
        _conflicting_thresholds(
            ds_critical=(-1.0, 1.0),
            us_critical=(-1.0, 1.0),
            snr_critical_min=50.0,
        ),
    )
    snapshot = _snapshot(
        "2026-05-01T00:00:00Z",
        ds_channels=[{
            "channel_id": 1,
            "type": "SC-QAM",
            "modulation": "256QAM",
            "power": 10.0,
            "snr": 40.0,
        }],
        us_channels=[{
            "channel_id": 2,
            "type": "SC-QAM",
            "power": 45.0,
        }],
    )
    snapshot["analysis_meta"] = {"analyzer_schema": 1}

    assert derive_historical_report_data([snapshot])["diagnostic_notes"] == []


@pytest.mark.parametrize(
    "analysis_meta",
    [None, {}, {"analyzer_schema": 0}, {"analyzer_schema": "1"}],
)
def test_legacy_snapshot_without_valid_schema_uses_active_thresholds(
    monkeypatch, analysis_meta
):
    from app import analyzer
    from app.modules.reports.report import derive_historical_report_data

    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds(ds_critical=(-1.0, 1.0)))
    snapshot = _snapshot(
        "2026-05-01T00:00:00Z",
        ds_channels=[{
            "channel_id": 1,
            "type": "SC-QAM",
            "modulation": "256QAM",
            "power": 30.0,
        }],
    )
    snapshot["analysis_meta"] = analysis_meta

    note = derive_historical_report_data([snapshot])["diagnostic_notes"][0]

    assert note["type"] == "ds_power_high"
    assert note["spec_max"] == 1.0
    assert note["deviation_pct"] == 2900


def test_exact_numeric_provenance_wins_over_neutral_candidate(monkeypatch):
    from app import analyzer
    from app.modules.reports.report import derive_historical_report_data

    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds())
    neutral = _snapshot("2026-05-01T00:00:00Z", ds_channels=[{
        "channel_id": 1,
        "type": "SC-QAM",
        "modulation": "256QAM",
        "power": 100.0,
        "power_health": "critical",
        "health_detail": "power critical high",
    }])
    neutral["analysis_meta"] = {"threshold_profile": {"id": "community", "version": "1"}}
    numeric = _snapshot("2026-05-02T00:00:00Z", ds_channels=[{
        "channel_id": 2,
        "type": "SC-QAM",
        "modulation": "256QAM",
        "power": 20.0,
        "power_health": "critical",
        "health_detail": "power critical high",
    }])
    numeric["analysis_meta"] = _builtin_analysis_meta()

    note = derive_historical_report_data([neutral, numeric])["diagnostic_notes"][0]

    assert note["channel_id"] == 2
    assert note["spec_max"] == 16.0


def test_neutral_fallback_selection_uses_directional_value_then_stable_ties():
    from app.modules.reports.report import derive_historical_report_data

    snapshots = []
    for timestamp, channel_id, power in [
        ("2026-05-02T00:00:00Z", 9, 40.0),
        ("2026-05-03T00:00:00Z", 7, 60.0),
        ("2026-05-01T00:00:00Z", 2, 60.0),
    ]:
        snapshot = _snapshot(timestamp, us_channels=[{
            "channel_id": channel_id,
            "type": "SC-QAM",
            "power": power,
            "power_health": "critical",
            "health_detail": "power critical high",
        }])
        snapshot["analysis_meta"] = {"threshold_profile": {"id": "community", "version": "1"}}
        snapshots.append(snapshot)

    note = derive_historical_report_data(snapshots)["diagnostic_notes"][0]

    assert note["value"] == 60.0
    assert note["observed_at"] == "2026-05-01T00:00:00Z"
    assert note["channel_id"] == 2


def test_pdf_and_complaint_render_neutral_fallback_without_invented_threshold(monkeypatch):
    from app import analyzer
    from app.modules.reports import report

    monkeypatch.setattr(analyzer, "_thresholds", _conflicting_thresholds())
    snapshot = _snapshot("2026-05-01T01:02:03Z", ds_channels=[{
        "channel_id": 4,
        "type": "SC-QAM",
        "modulation": "256QAM",
        "power": 10.0,
        "power_health": "critical",
        "health_detail": "power critical high",
    }])
    snapshot["analysis_meta"] = {
        "threshold_profile": {"id": "community.strict", "version": "9.4.0"}
    }

    pdf_text = " ".join(_pdf_text(report.generate_report([snapshot])).split())
    complaint = report.generate_complaint_text([snapshot])
    expected = (
        "Channel 4 (SC-QAM): downstream power of 10.0 dBmV was recorded as "
        "critically high by the stored analyzer result; the exact historical "
        "threshold is unavailable. Observed at 2026-05-01T01:02:03Z UTC."
    )

    assert expected in pdf_text
    assert expected in complaint
    assert "10.0 dBmV exceeds expected maximum" not in pdf_text
    assert "10.0 dBmV exceeds expected maximum" not in complaint


def test_historical_derivation_uses_latest_snapshot_and_worst_note_per_type():
    from app.modules.reports.report import derive_historical_report_data

    snapshots = [
        {
            "timestamp": "2026-05-02T00:00:00Z",
            "summary": {"health": "critical"},
            "ds_channels": [{
                "channel_id": 7,
                "modulation": "256QAM",
                "power": 30.0,
                "snr": 20.0,
                "power_health": "critical",
                "snr_health": "critical",
                "health_detail": "power critical high + snr critical",
            }],
            "us_channels": [],
            "analysis_meta": _builtin_analysis_meta(),
        },
        {
            "timestamp": "2026-05-03T00:00:00Z",
            "summary": {"health": "good"},
            "ds_channels": [],
            "us_channels": [],
        },
        {
            "timestamp": "2026-05-01T00:00:00Z",
            "summary": {"health": "marginal"},
            "ds_channels": [{
                "channel_id": 3,
                "modulation": "256QAM",
                "power": 30.0,
                "snr": 20.0,
                "power_health": "critical",
                "snr_health": "critical",
                "health_detail": "power critical high + snr critical",
            }],
            "us_channels": [],
            "analysis_meta": _builtin_analysis_meta(),
        },
    ]

    historical = derive_historical_report_data(snapshots)

    assert historical["latest_snapshot"]["timestamp"] == "2026-05-03T00:00:00Z"
    assert [note["type"] for note in historical["diagnostic_notes"]] == [
        "ds_power_high", "snr_low"
    ]
    assert {note["observed_at"] for note in historical["diagnostic_notes"]} == {
        "2026-05-01T00:00:00Z"
    }
    assert {note["channel_id"] for note in historical["diagnostic_notes"]} == {3}


def test_historical_note_tie_breaks_by_channel_identity_after_timestamp():
    from app.modules.reports.report import derive_historical_report_data

    snapshots = [_snapshot(
        "2026-05-01T00:00:00+00:00",
        us_channels=[
            {
                "channel_id": 9,
                "type": "SC-QAM",
                "power": 60.0,
                "power_health": "critical",
                "health_detail": "power critical high",
            },
            {
                "channel_id": 2,
                "type": "SC-QAM",
                "power": 60.0,
                "power_health": "critical",
                "health_detail": "power critical high",
            },
        ],
    )]
    snapshots[0]["analysis_meta"] = _builtin_analysis_meta()
    historical = derive_historical_report_data(snapshots)

    assert len(historical["diagnostic_notes"]) == 1
    assert historical["diagnostic_notes"][0]["type"] == "us_power_high"
    assert historical["diagnostic_notes"][0]["channel_id"] == 2
    assert historical["diagnostic_notes"][0]["observed_at"] == "2026-05-01T00:00:00Z"


def test_error_counters_never_create_historical_diagnostic_notes():
    from app.modules.reports.report import derive_historical_report_data

    historical = derive_historical_report_data([_snapshot(
        "2026-05-01T00:00:00Z",
        summary={
            "ds_correctable_errors": 999999999,
            "ds_uncorrectable_errors": 999999999,
        },
    )])

    assert historical["diagnostic_notes"] == []


def test_partial_snapshot_keeps_missing_historical_metrics_unavailable():
    from app.modules.reports.report import generate_complaint_text

    complaint = generate_complaint_text([_snapshot(
        "2026-05-01T00:00:00Z",
        summary={"errors_supported": False},
    )])

    assert "Worst downstream power: N/A dBmV" in complaint
    assert "Worst upstream power: N/A dBmV" in complaint
    assert "Worst downstream SNR: N/A dB" in complaint
    assert "Worst downstream power: 0" not in complaint


def test_pdf_uses_latest_recorded_status_and_requested_bounds():
    from app.modules.reports.report import generate_report

    snapshots = [
        _snapshot("2026-05-02T12:00:00Z", health="critical"),
        _snapshot("2026-05-01T12:00:00Z", health="marginal"),
    ]

    text = _pdf_text(generate_report(
        snapshots,
        report_start="2026-05-01T00:00:00Z",
        report_end="2026-05-03T00:00:00Z",
    ))

    assert "Latest Recorded Status in Report Period" in text
    assert "Observed at: 2026-05-02T12:00:00Z" in text
    assert "Connection Health: CRITICAL" in text
    assert "Current Status" not in text
    assert "2026-05-01T00:00:00Z  to  2026-05-03T00:00:00Z" in text


def test_empty_pdf_prints_requested_window_zero_count_and_neutral_text():
    from app.modules.reports.report import generate_report

    text = _pdf_text(generate_report(
        [],
        report_start="2026-05-01T00:00:00Z",
        report_end="2026-05-03T00:00:00Z",
    ))

    assert "2026-05-01T00:00:00Z  to  2026-05-03T00:00:00Z" in text
    assert "Data Points: 0" in text
    assert "No stored DOCSIS measurements are available for the requested report period." in text


def test_pdf_and_text_complaint_use_one_period_aggregate_per_artifact():
    from app.modules.reports import report

    snapshots = [_snapshot(
        "2026-05-01T01:02:03Z",
        ds_channels=[{
            "channel_id": 4,
            "modulation": "256QAM",
            "power": 30.0,
            "snr": 40.0,
            "power_health": "critical",
            "snr_health": "good",
            "health_detail": "power critical high",
        }],
    )]
    snapshots[0]["analysis_meta"] = _builtin_analysis_meta()
    real_aggregate = report.aggregate_snapshot_period

    with patch.object(
        report, "aggregate_snapshot_period", wraps=real_aggregate
    ) as aggregate:
        pdf_text = _pdf_text(report.generate_report(
            snapshots,
            report_start="2026-05-01T00:00:00Z",
            report_end="2026-05-02T00:00:00Z",
        ))
    assert aggregate.call_count == 1

    with patch.object(
        report, "aggregate_snapshot_period", wraps=real_aggregate
    ) as aggregate:
        complaint = report.generate_complaint_text(
            snapshots,
            report_start="2026-05-01T00:00:00Z",
            report_end="2026-05-02T00:00:00Z",
        )
    assert aggregate.call_count == 1

    expected = (
        "Channel 4 (SC-QAM): downstream power of 30.0 dBmV exceeds expected "
        "maximum (16.0 dBmV) by 88%. Observed at 2026-05-01T01:02:03Z UTC."
    )
    assert expected in " ".join(pdf_text.split())
    assert expected in complaint


def test_empty_complaint_is_neutral_without_bnetz_data():
    from app.modules.reports.report import generate_complaint_text

    complaint = generate_complaint_text(
        [],
        report_start="2026-05-01T00:00:00Z",
        report_end="2026-05-03T00:00:00Z",
    )

    assert "No stored DOCSIS measurements are available" in complaint
    assert "persistent signal quality issues" not in complaint
    assert "Signal Quality Issues" not in complaint
    assert "attached monitoring data" not in complaint


def test_empty_complaint_is_neutral_and_keeps_bnetz_evidence():
    from app.modules.reports.report import generate_complaint_text

    complaint = generate_complaint_text(
        [],
        report_start="2026-05-01T00:00:00Z",
        report_end="2026-05-03T00:00:00Z",
        bnetz_data={
            "date": "2026-05-02",
            "provider": "Example ISP",
            "tariff": "1000/50",
            "download_max_tariff": 1000,
            "download_measured_avg": 400,
            "upload_max_tariff": 50,
            "upload_measured_avg": 45,
            "verdict_download": "deviation",
            "verdict_upload": "ok",
        },
    )

    assert "No stored DOCSIS measurements are available" in complaint
    assert "Official Broadband Measurement (Bundesnetzagentur)" in complaint
    assert "2026-05-02" in complaint
    assert "persistent signal quality issues" not in complaint
    assert "Signal Quality Issues" not in complaint
