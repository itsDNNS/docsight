"""Tests for the built-in VFKD threshold profile values and their documented sources."""

from app import analyzer
from app.threshold_profiles import BUILTIN_THRESHOLD_PROFILES

_VFKD = next(p for p in BUILTIN_THRESHOLD_PROFILES if p["id"] == "docsight.thresholds_vfkd")
_THRESHOLDS = _VFKD["thresholds"]
_META = _THRESHOLDS["_meta"]

_SOURCE_CLASSES = {"specification", "conversion", "convention"}


def test_vfkd_threshold_values_are_pinned():
    """Documentation changes must not move any threshold value."""
    assert _THRESHOLDS["downstream_power"] == {
        "_default": "256QAM",
        "64QAM": {"good": [-10.0, 7.0], "warning": [-12.0, 12.0], "critical": [-14.0, 16.0]},
        "256QAM": {"good": [-4.0, 13.0], "warning": [-6.0, 15.0], "critical": [-8.0, 16.0]},
        "1024QAM": {"good": [-2.0, 15.0], "warning": [-4.0, 16.0], "critical": [-6.0, 16.0]},
        "4096QAM": {"good": [-2.0, 15.0], "warning": [-4.0, 16.0], "critical": [-6.0, 16.0]},
        "ofdm": {"good": [-12.0, 12.0], "warning": [-15.0, 15.0], "critical": [-15.0, 15.0]},
    }
    assert _THRESHOLDS["upstream_power"] == {
        "_default": "sc_qam",
        "sc_qam": {"good": [41.1, 47.0], "warning": [37.1, 51.0], "critical": [35.0, 53.0]},
        "ofdma": {"good": [44.1, 47.0], "warning": [40.1, 48.0], "critical": [38.0, 50.0]},
    }
    assert _THRESHOLDS["snr"] == {
        "_default": "256QAM",
        "64QAM": {"good_min": 27.0, "warning_min": 25.0, "critical_min": 23.0},
        "256QAM": {"good_min": 33.0, "warning_min": 31.0, "critical_min": 29.0},
        "ofdm": {"good_min": 27.0, "warning_min": 25.5, "critical_min": 24.5},
        "1024QAM": {"good_min": 39.0, "warning_min": 37.0, "critical_min": 36.0},
        "4096QAM": {"good_min": 40.0, "warning_min": 38.0, "critical_min": 36.0},
    }
    assert _THRESHOLDS["upstream_modulation"] == {"critical_max_qam": 4, "warning_max_qam": 16}
    assert _THRESHOLDS["errors"] == {
        "uncorrectable_pct": {"warning": 1.0, "critical": 3.0},
        "spike_expiry_hours": 48,
    }


def test_analyzer_fallback_uses_the_vfkd_profile_values():
    """The no-profile fallback must not drift from the shipped VFKD profile."""
    expected = {key: value for key, value in _THRESHOLDS.items() if key != "_meta"}
    assert analyzer._FALLBACK_THRESHOLDS == expected
    assert "_meta" not in analyzer._FALLBACK_THRESHOLDS


def test_every_upstream_power_value_names_its_source():
    sources = _META["upstream_power_sources"]
    bands = {band for band in _THRESHOLDS["upstream_power"] if not band.startswith("_")}
    assert set(sources) == bands
    for band in bands:
        for level in ("good", "warning", "critical"):
            for bound in ("min", "max"):
                entry = sources[band][f"{level}_{bound}"]
                assert entry["source"] in _SOURCE_CLASSES, (band, level, bound)
                assert entry["basis"].strip(), (band, level, bound)


def test_upstream_power_source_classes():
    sources = _META["upstream_power_sources"]
    classes = {
        band: {key: entry["source"] for key, entry in entries.items()}
        for band, entries in sources.items()
    }
    assert classes == {
        "sc_qam": {
            "good_min": "conversion",
            "good_max": "convention",
            "warning_min": "convention",
            "warning_max": "convention",
            "critical_min": "convention",
            "critical_max": "conversion",
        },
        "ofdma": {
            "good_min": "convention",
            "good_max": "convention",
            "warning_min": "convention",
            "warning_max": "convention",
            "critical_min": "convention",
            "critical_max": "convention",
        },
    }


def test_converted_upstream_values_follow_from_the_specification():
    """Table 9 nominal window 98.1 to 110 dBuV at 3.2 MHz, moved to dBmV and a 6.4 MHz channel."""
    sources = _META["upstream_power_sources"]["sc_qam"]
    sc_qam = _THRESHOLDS["upstream_power"]["sc_qam"]
    for key, spec_dbuv, value in (
        ("good_min", 98.1, sc_qam["good"][0]),
        ("critical_max", 110.0, sc_qam["critical"][1]),
    ):
        entry = sources[key]
        assert entry["spec_dbuv"] == spec_dbuv
        assert round(entry["spec_dbuv"] - 60.0 + entry["bandwidth_offset_db"], 1) == value


def test_vfkd_profile_cites_the_document_version_it_links():
    """The linked file is named v1.06 but its title page says Version 1.05."""
    assert _META["source"].endswith("VF-DOCSIS-Interface-Specification-v1.06.pdf")
    assert "Version 1.05" in _META["notes"]
    assert "Specification v1.06 (13.09.2021)" not in _META["notes"]


def test_vfkd_profile_description_does_not_claim_the_spec_for_all_values():
    assert "convention" in _VFKD["description"].lower()
