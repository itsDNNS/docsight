"""Built-in DOCSIS analyzer threshold profiles.

Threshold profiles are DOCSight-owned analyzer configuration, not community
module wrappers.  Community modules may still contribute additional threshold
profiles through the module loader, but shipped defaults live here.
"""

from __future__ import annotations

BUILTIN_THRESHOLD_PROFILES: tuple[dict[str, object], ...] = (
    {
        "id": "docsight.thresholds_vfkd",
        "name": "VFKD Thresholds",
        "description": "Signal thresholds based on the official Vodafone pNTP Interface Specification v1.06",
        "version": "1.0.0",
        "author": "itsDNNS",
        "minAppVersion": "2026.2",
        "thresholds": {
            "_meta": {
                "region": "Germany",
                "operator": "Vodafone Kabel Deutschland",
                "docsis_variant": "eurodocsis",
                "source": "https://www.vodafone.de/media/downloads/pdf/VF-DOCSIS-Interface-Specification-v1.06.pdf",
                "notes": "Based on Vodafone pNTP Interface Specification v1.06 (13.09.2021). Power values converted from dBuV to dBmV (dBmV = dBuV - 60). SNR/MER in dB. Warning/critical boundaries derived from spec nominal vs absolute maximum ranges.",
            },
            "downstream_power": {
                "_default": "256QAM",
                "64QAM": {"good": [-10.0, 7.0], "warning": [-12.0, 12.0], "critical": [-14.0, 16.0]},
                "256QAM": {"good": [-4.0, 13.0], "warning": [-6.0, 15.0], "critical": [-8.0, 16.0]},
                "1024QAM": {"good": [-2.0, 15.0], "warning": [-4.0, 16.0], "critical": [-6.0, 16.0]},
                "4096QAM": {"good": [-2.0, 15.0], "warning": [-4.0, 16.0], "critical": [-6.0, 16.0]},
            },
            "upstream_power": {
                "_default": "sc_qam",
                "sc_qam": {"good": [41.1, 47.0], "warning": [37.1, 51.0], "critical": [35.0, 53.0]},
                "ofdma": {"good": [44.1, 47.0], "warning": [40.1, 48.0], "critical": [38.0, 50.0]},
            },
            "snr": {
                "_default": "256QAM",
                "64QAM": {"good_min": 27.0, "warning_min": 25.0, "critical_min": 23.0},
                "256QAM": {"good_min": 33.0, "warning_min": 31.0, "critical_min": 29.0},
                "ofdm": {"good_min": 27.0, "warning_min": 25.5, "critical_min": 24.5},
                "1024QAM": {"good_min": 39.0, "warning_min": 37.0, "critical_min": 36.0},
                "4096QAM": {"good_min": 40.0, "warning_min": 38.0, "critical_min": 36.0},
            },
            "upstream_modulation": {
                "critical_max_qam": 4,
                "warning_max_qam": 16,
            },
            "errors": {
                "uncorrectable_pct": {"warning": 1.0, "critical": 3.0},
                "spike_expiry_hours": 48,
            },
        },
    },
)
