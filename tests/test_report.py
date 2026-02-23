"""Tests for incident report generation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.report import (
    generate_report, generate_complaint_text,
    _compute_worst_values, _find_worst_channels,
    _format_threshold_table, _default_warn_thresholds,
)


MOCK_ANALYSIS = {
    "summary": {
        "ds_total": 2, "us_total": 1,
        "ds_power_min": -1.2, "ds_power_max": 5.3, "ds_power_avg": 2.1,
        "us_power_min": 42.0, "us_power_max": 48.5, "us_power_avg": 45.0,
        "ds_snr_min": 33.5, "ds_snr_avg": 37.2,
        "ds_correctable_errors": 12543, "ds_uncorrectable_errors": 23,
        "health": "good", "health_issues": [],
    },
    "ds_channels": [
        {"channel_id": 1, "frequency": "114 MHz", "power": 2.1, "snr": 37.2,
         "modulation": "256QAM", "correctable_errors": 100, "uncorrectable_errors": 0, "health": "good"},
        {"channel_id": 2, "frequency": "122 MHz", "power": -8.5, "snr": 26.1,
         "modulation": "256QAM", "correctable_errors": 5000, "uncorrectable_errors": 23, "health": "warning"},
    ],
    "us_channels": [
        {"channel_id": 1, "frequency": "37 MHz", "power": 45.0,
         "modulation": "64QAM", "multiplex": "ATDMA", "health": "good"},
    ],
}

MOCK_SNAPSHOTS = [
    {"timestamp": "2026-02-04T10:00:00", "summary": MOCK_ANALYSIS["summary"],
     "ds_channels": MOCK_ANALYSIS["ds_channels"], "us_channels": MOCK_ANALYSIS["us_channels"]},
    {"timestamp": "2026-02-05T10:00:00", "summary": {
        **MOCK_ANALYSIS["summary"], "health": "poor", "ds_snr_min": 22.0,
        "us_power_max": 55.0, "ds_uncorrectable_errors": 50000,
        "health_issues": ["snr_critical", "us_power_critical_high"]},
     "ds_channels": MOCK_ANALYSIS["ds_channels"], "us_channels": MOCK_ANALYSIS["us_channels"]},
]


def test_generate_report_returns_pdf():
    pdf = generate_report(MOCK_SNAPSHOTS, MOCK_ANALYSIS)
    assert isinstance(pdf, bytes)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_generate_report_no_snapshots():
    pdf = generate_report([], MOCK_ANALYSIS)
    assert pdf[:5] == b"%PDF-"


def test_generate_report_with_config():
    pdf = generate_report(MOCK_SNAPSHOTS, MOCK_ANALYSIS,
                          config={"isp_name": "Vodafone", "modem_type": "FRITZ!Box 6690"},
                          connection_info={"max_downstream_kbps": 1000000, "max_upstream_kbps": 50000})
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 5000


def test_compute_worst_values():
    worst = _compute_worst_values(MOCK_SNAPSHOTS)
    assert worst["health_poor_count"] == 1
    assert worst["total_snapshots"] == 2
    assert worst["us_power_max"] == 55.0
    assert worst["ds_snr_min"] == 22.0
    assert worst["ds_uncorrectable_max"] == 50000


def test_find_worst_channels():
    ds_worst, us_worst = _find_worst_channels(MOCK_SNAPSHOTS)
    # Channel 2 should appear as problematic (health: warning in both snapshots)
    assert len(ds_worst) > 0
    assert ds_worst[0][0] == 2  # channel_id 2


def test_format_threshold_table_uses_real_values():
    rows = _format_threshold_table()
    assert len(rows) > 0
    categories = {r["category"] for r in rows}
    assert "DS Power" in categories
    assert "US Power" in categories
    assert "SNR/MER" in categories
    # Check that values come from thresholds.json, not hardcoded
    ds_256 = [r for r in rows if r["category"] == "DS Power" and r["variant"] == "256QAM"]
    assert len(ds_256) == 1
    assert "-3.9" in ds_256[0]["good"]
    assert "13.0" in ds_256[0]["good"]
    # Upstream modulation thresholds
    us_mod = [r for r in rows if r["category"] == "US Modulation"]
    assert len(us_mod) == 1
    assert "16" in us_mod[0]["warn"]
    assert "4" in us_mod[0]["warn"]


def test_default_warn_thresholds():
    warn = _default_warn_thresholds()
    assert "ds_power" in warn
    assert "us_power" in warn
    assert "snr" in warn
    # 256QAM tolerated: -5.9 to 18.0
    assert "-5.9" in warn["ds_power"]
    assert "18.0" in warn["ds_power"]
    # EuroDOCSIS 3.0 tolerated: 37.1 to 51.0
    assert "37.1" in warn["us_power"]
    assert "51.0" in warn["us_power"]
    # SNR 256QAM tolerated_min: 32.0
    assert "32.0" in warn["snr"]


def test_complaint_text_uses_real_thresholds():
    text = generate_complaint_text(MOCK_SNAPSHOTS)
    # Should contain real threshold values from thresholds.json
    assert "-5.9 to 18.0 dBmV" in text
    assert "37.1 to 51.0 dBmV" in text
    assert ">= 32.0 dB" in text
