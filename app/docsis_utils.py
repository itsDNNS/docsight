"""Shared DOCSIS utilities — QAM hierarchy and modulation ranking."""

import re

# QAM hierarchy: higher value = better modulation
QAM_ORDER = {
    "QPSK": 1, "4QAM": 1,
    "8QAM": 2,
    "16QAM": 3,
    "32QAM": 4,
    "64QAM": 5,
    "128QAM": 6,
    "256QAM": 7,
    "512QAM": 8,
    "1024QAM": 9,
    "2048QAM": 10,
    "4096QAM": 11,
}


def qam_rank(modulation):
    """Get QAM rank for any modulation format.

    Handles both driver formats: "256QAM" (Ultra Hub 7, CM3500)
    and "qam_256" (Vodafone Station, CH7465, TC4400).

    Returns 0 for unknown/empty modulation.
    """
    if not modulation:
        return 0
    rank = QAM_ORDER.get(modulation)
    if rank is not None:
        return rank
    mod = modulation.upper().replace("-", "").replace("_", "")
    if mod == "QPSK":
        return QAM_ORDER["QPSK"]
    m = re.search(r"(\d+)", mod)
    if m and "QAM" in mod:
        return QAM_ORDER.get(f"{m.group(1)}QAM", 0)
    return 0
