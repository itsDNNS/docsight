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
        "description": "Signal thresholds based on the official Vodafone pNTP and referenced DOCSIS specifications",
        "version": "1.1.0",
        "author": "itsDNNS",
        "minAppVersion": "2026.2",
        "thresholds": {
            "_meta": {
                "region": "Germany",
                "operator": "Vodafone Kabel Deutschland",
                "docsis_variant": "eurodocsis",
                "source": "https://www.vodafone.de/media/downloads/pdf/VF-DOCSIS-Interface-Specification-v1.06.pdf",
                "cablelabs_source": "https://www.cablelabs.com/specifications/physical-layer-specification?v=I08",
                "notes": "Based primarily on Vodafone pNTP Interface Specification v1.06 (13.09.2021). Power values converted from dBuV to dBmV (dBmV = dBuV - 60). SNR/MER in dB. Warning/critical boundaries derived from spec nominal vs absolute maximum ranges. OFDM downstream power bands use CableLabs DOCSIS 3.1 PHY CM-SP-PHYv3.1-I08-151210 Table 7-40 and section 9.3.9. Table 7-40 defines an equivalent PSD to SC-QAM level range of -15 to +15 dBmV per 6 MHz; section 9.3.9 specifies +/-3 dB measurement accuracy from -12 to +12 dBmV and +/-5 dB accuracy from -15 to +15 dBmV. DOCSight maps the tighter range to good and the remaining documented level range to tolerated. Warning and critical use the same outer range, so there is no invented warning-only band. Table 7-40 states that its level range does not imply BER performance or capability versus QAM, and the 4096QAM minimum-P6AVG table is not used as a generic downstream power health limit. Aggregate OFDM channel MER is assessed against the ofdm row; 1024QAM/4096QAM SNR entries remain profile-support references, and the 25.5 dB warning is DOCSight-derived.",
            },
            "downstream_power": {
                "_default": "256QAM",
                "64QAM": {"good": [-10.0, 7.0], "warning": [-12.0, 12.0], "critical": [-14.0, 16.0]},
                "256QAM": {"good": [-4.0, 13.0], "warning": [-6.0, 15.0], "critical": [-8.0, 16.0]},
                "1024QAM": {"good": [-2.0, 15.0], "warning": [-4.0, 16.0], "critical": [-6.0, 16.0]},
                "4096QAM": {"good": [-2.0, 15.0], "warning": [-4.0, 16.0], "critical": [-6.0, 16.0]},
                "ofdm": {"good": [-12.0, 12.0], "warning": [-15.0, 15.0], "critical": [-15.0, 15.0]},
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
