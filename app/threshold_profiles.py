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
        # Label for the reference column of report threshold tables.
        "short_name": "VFKD",
        "description": "Signal thresholds based on the Vodafone pNTP and referenced DOCSIS specifications, with DOCSight conventions for values the specification does not define",
        "version": "1.3.0",
        # Earlier versions with identical threshold numbers. Snapshots stored
        # with them keep exact numeric provenance in reports. Clear this when
        # any threshold number changes.
        "same_thresholds_as": ("1.2.0", "1.1.0"),
        "author": "itsDNNS",
        "minAppVersion": "2026.2",
        "thresholds": {
            "_meta": {
                "region": "Germany",
                "operator": "Vodafone Kabel Deutschland",
                "docsis_variant": "eurodocsis",
                "source": "https://www.vodafone.de/media/downloads/pdf/VF-DOCSIS-Interface-Specification-v1.06.pdf",
                "cablelabs_source": "https://www.cablelabs.com/specifications/physical-layer-specification?v=I08",
                "notes": "Based primarily on the Vodafone pNTP Interface Specification, document titled Version 1.05 (13.09.2021), published as VF-DOCSIS-Interface-Specification-v1.06.pdf. Power values converted from dBuV to dBmV (dBmV = dBuV - 60). SNR/MER in dB. For 64QAM and 256QAM downstream power, good ranges follow the spec nominal ranges and the critical maximum follows the spec absolute maximum. Upstream power: table 9 (network types 1 and 2) only gives a nominal range at installation time of 98.1 to 110 dBuV per 3.2 MHz reference bandwidth (nominal values valid for 99.5 % of the time) and an absolute maximum of 114 dBuV; for OFDM it gives no nominal range, only an absolute maximum of 125 dBuV. It defines no absolute lower upstream limit; 98.1 dBuV is only the lower edge of that nominal range, so DOCSight rates low upstream power at most as a warning and only high upstream power as critical. Low OFDMA upstream power is not rated at all: table 9 gives no nominal OFDM level range, table 10 footnote 1 states that with OFDMA a range cannot be defined, and CableLabs CM-SP-PHYv3.1-I08 section 7.4.12.2 only defines what a modem can transmit (P1.6min of 17 dBmV per 1.6 MHz up to P1.6hi = Pmax - 10log10(Neq) with Pmax at least 65 dBmV). The OFDMA good, warning and critical minimums only scale displays; OFDMA levels below P1.6min are rated as a warning because no modem transmits them. The OFDMA maximums remain DOCSight conventions until the reference bandwidth of each driver's OFDMA power is known. upstream_power_sources records the origin of every upstream value: conversion is a table 9 value in dBmV plus 3 dB for a 6.4 MHz SC-QAM channel, convention is a DOCSight choice that the specification does not define, carried over from the community level table on vodafonekabelforum.de that earlier DOCSight versions used. OFDM downstream power bands use CableLabs DOCSIS 3.1 PHY CM-SP-PHYv3.1-I08-151210 Table 7-40 and section 9.3.9. Table 7-40 defines an equivalent PSD to SC-QAM level range of -15 to +15 dBmV per 6 MHz; section 9.3.9 specifies +/-3 dB measurement accuracy from -12 to +12 dBmV and +/-5 dB accuracy from -15 to +15 dBmV. DOCSight maps the tighter range to good and the remaining documented level range to tolerated. Warning and critical use the same outer range, so there is no invented warning-only band. Table 7-40 states that its level range does not imply BER performance or capability versus QAM, and the 4096QAM minimum-P6AVG table is not used as a generic downstream power health limit. Aggregate OFDM channel MER is assessed against the ofdm row; 1024QAM/4096QAM SNR entries remain profile-support references, and the 25.5 dB warning is DOCSight-derived.",
                "upstream_power_sources": {
                    "sc_qam": {
                        "good_min": {
                            "source": "conversion",
                            "basis": "Table 9 nominal minimum 98.1 dBuV (38.1 dBmV) at 3.2 MHz, plus 3 dB for 6.4 MHz",
                            "spec_dbuv": 98.1,
                            "bandwidth_offset_db": 3.0,
                        },
                        "good_max": {"source": "convention", "basis": "Community level table; the converted nominal window reaches 53 dBmV"},
                        "warning_min": {"source": "convention", "basis": "Community level table, 4 dB below the good range"},
                        "warning_max": {"source": "convention", "basis": "Community level table, 4 dB above the good range"},
                        "critical_min": {"source": "convention", "basis": "Community level table; the specification defines no absolute lower limit, so values below it are rated at most as a warning"},
                        "critical_max": {
                            "source": "conversion",
                            "basis": "Table 9 nominal maximum 110 dBuV (50 dBmV) at 3.2 MHz, plus 3 dB for 6.4 MHz; using the nominal rather than the absolute maximum is a DOCSight choice",
                            "spec_dbuv": 110.0,
                            "bandwidth_offset_db": 3.0,
                        },
                    },
                    "ofdma": {
                        "good_min": {"source": "convention", "basis": "Community level table; display scale only, low OFDMA power is not rated because table 9 gives no nominal OFDM level range"},
                        "good_max": {"source": "convention", "basis": "Community level table; table 9 gives no nominal OFDM level range"},
                        "warning_min": {"source": "convention", "basis": "Community level table; display scale only, low OFDMA power is not rated"},
                        "warning_max": {"source": "convention", "basis": "Community level table; table 9 gives no nominal OFDM level range"},
                        "critical_min": {"source": "convention", "basis": "Community level table; display scale only, the specification defines no OFDM level range"},
                        "critical_max": {"source": "convention", "basis": "Community level table; table 9 only gives an absolute maximum total OFDM output power of 125 dBuV (65 dBmV), not a per-channel limit"},
                        "plausible_min": {
                            "source": "specification",
                            "basis": "CableLabs CM-SP-PHYv3.1-I08 section 7.4.12.2: P1.6min = 17 dBmV per 1.6 MHz; lower OFDMA levels are rated as a warning",
                            "value_dbmv": 17.0,
                        },
                    },
                },
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
