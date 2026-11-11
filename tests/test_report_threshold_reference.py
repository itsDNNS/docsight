"""Report threshold references name the profile that supplied the numbers."""

import io

from pypdf import PdfReader

from app import analyzer
from app.modules.reports.report import (
    _format_threshold_table,
    generate_complaint_text,
    generate_incident_report,
    generate_report,
)
from app.threshold_profiles import BUILTIN_THRESHOLD_PROFILES
from tests.threshold_profile_helpers import (
    COMMUNITY_PROFILE_ID,
    COMMUNITY_PROFILE_VERSION,
    no_registered_profile,
    registered_builtin_profiles,
    registered_community_profile,
)

_SUMMARY = {
    "ds_total": 2, "us_total": 2,
    "ds_power_min": -1.2, "ds_power_max": 5.3, "ds_power_avg": 2.1,
    "us_power_min": 42.0, "us_power_max": 48.5, "us_power_avg": 45.0,
    "ds_snr_min": 35.5, "ds_snr_avg": 37.2,
    "ds_correctable_errors": 100, "ds_uncorrectable_errors": 0,
    "health": "good", "health_issues": [],
}


def _snapshot(timestamp, **summary):
    return {
        "timestamp": timestamp,
        "summary": {**_SUMMARY, **summary},
        "ds_channels": [],
        "us_channels": [],
    }


def _pdf_text(pdf):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def _threshold_page(text):
    return text.split("Reference: DOCSIS Signal Thresholds", 1)[1].split("ISP Complaint Template", 1)[0]


def _references(rows):
    return {(row["category"], row["variant"]): row["ref"] for row in rows}


def test_vfkd_table_keeps_its_reference_and_marks_upstream_conventions():
    for context in (registered_builtin_profiles, no_registered_profile):
        with context():
            refs = _references(_format_threshold_table())
            page = _threshold_page(_pdf_text(generate_report([_snapshot("2026-11-01T10:00:00")])))

        assert refs[("DS Power", "256QAM")] == "VFKD"
        assert refs[("SNR/MER", "256QAM")] == "VFKD"
        assert refs[("US Modulation", "QAM Order")] == "VFKD"
        assert refs[("US Power", "sc_qam")] == "VFKD *"
        assert refs[("US Power", "ofdma")] == "VFKD *"
        assert "Threshold profile: VFKD Thresholds 1.2.0" in page
        assert "* Marked rows include values that are DOCSight conventions rather than specification values." in page


def test_community_profile_is_named_as_the_reference(tmp_path):
    with registered_community_profile(tmp_path):
        refs = _references(_format_threshold_table())
        snapshots = [_snapshot("2026-11-01T10:00:00")]
        report = _pdf_text(generate_report(snapshots))
        incident = _pdf_text(generate_incident_report(
            {"name": "Outage", "status": "open"}, [], snapshots, [], [],
        ))

    assert set(refs.values()) == {"Strict Cable"}
    page = _threshold_page(report)
    assert "Threshold profile: Strict Cable 2.3.0" in page
    assert "DOCSight conventions" not in page
    assert "VFKD" not in report
    assert "VFKD" not in incident


def test_community_profile_with_copied_vfkd_metadata_is_still_named_as_itself(tmp_path):
    vfkd_meta = BUILTIN_THRESHOLD_PROFILES[0]["thresholds"]["_meta"]
    with registered_community_profile(tmp_path, meta=vfkd_meta):
        refs = _references(_format_threshold_table())
        stored = analyzer.get_analysis_metadata()["threshold_profile"]

    assert refs[("DS Power", "256QAM")] == "Strict Cable"
    # The copied upstream sources are the profile's own claim and stay marked.
    assert refs[("US Power", "sc_qam")] == "Strict Cable *"
    # Stored snapshot provenance keeps its id and version shape.
    assert stored == {"id": COMMUNITY_PROFILE_ID, "version": COMMUNITY_PROFILE_VERSION}


def test_long_profile_name_is_shortened_in_the_table_and_named_in_full_below(tmp_path):
    name = "Regional Cable Operator Community Thresholds"
    with registered_community_profile(tmp_path, name=name):
        page = _threshold_page(_pdf_text(generate_report([_snapshot("2026-11-01T10:00:00")])))

    table, note = page.split("Threshold profile:", 1)
    assert "Regional Cabl…" in table
    assert name not in table
    assert f" {name} 2.3.0" in note


def test_report_warning_ranges_follow_the_analyzer_for_the_active_profile(tmp_path):
    with registered_community_profile(tmp_path):
        text = generate_complaint_text([_snapshot("2026-11-01T10:00:00")])

    # The profile has no 256QAM warning band, so the analyzer uses the good band.
    assert "(threshold: -3.0 to 10.0 dBmV)" in text
    assert "(threshold: 38.0 to 50.0 dBmV)" in text
    assert "(threshold: >= 34.0 dB)" in text
    assert "-5.9" not in text
    assert "18.0 dBmV" not in text


def test_threshold_table_tolerates_only_the_good_band_when_a_profile_has_no_warning_band(tmp_path):
    with registered_community_profile(tmp_path):
        rows = {(row["category"], row["variant"]): row for row in _format_threshold_table()}

    assert rows[("DS Power", "256QAM")]["tolerated"] == "-3.0 to 10.0 dBmV"
    assert rows[("SNR/MER", "256QAM")]["tolerated"] == ">= 34.0 dB"


def test_report_quotes_low_power_when_it_is_further_out_of_range():
    snapshots = [
        _snapshot("2026-11-01T10:00:00", us_power_min=33.0, us_power_max=44.0,
                  ds_power_min=-9.0, ds_power_max=5.0),
        _snapshot("2026-11-02T10:00:00", us_power_min=40.0, us_power_max=46.0),
    ]

    letter = generate_complaint_text(snapshots)
    report = _pdf_text(generate_report(snapshots))

    assert "Worst upstream power: 33.0 dBmV (threshold: 37.1 to 51.0 dBmV)" in letter
    assert "Worst downstream power: -9.0 dBmV (threshold: -6.0 to 15.0 dBmV)" in letter
    assert "US Power (worst): 33.0 dBmV" in report
    assert "DS Power (worst): -9.0 dBmV" in report


def test_report_quotes_low_downstream_power_next_to_hotter_snapshots():
    snapshots = [
        _snapshot("2026-11-01T10:00:00", ds_power_min=8.0, ds_power_max=12.0),
        _snapshot("2026-11-02T10:00:00", ds_power_min=-7.0, ds_power_max=3.0),
    ]

    letter = generate_complaint_text(snapshots)

    assert "Worst downstream power: -7.0 dBmV (threshold: -6.0 to 15.0 dBmV)" in letter


def test_report_keeps_high_power_when_it_is_further_out_of_range():
    snapshots = [_snapshot("2026-11-01T10:00:00", us_power_min=36.0, us_power_max=55.0)]

    letter = generate_complaint_text(snapshots)

    assert "Worst upstream power: 55.0 dBmV" in letter
    assert "Worst downstream power: 5.3 dBmV" in letter

