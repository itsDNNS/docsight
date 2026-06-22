"""Shared DOCSIS utilities — QAM parsing, hierarchy, and modulation labels."""

from __future__ import annotations

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


_QAM_RE = re.compile(r"(?:(\d+)\s*QAM|QAM\s*(\d+))")


def parse_qam_order(modulation: object) -> int | None:
    """Extract numeric QAM order from a modulation value.

    Returns ``None`` for non-QAM values such as OFDM/OFDMA or unknown strings.
    ``QPSK`` is treated as 4-QAM because both carry two bits per symbol in the
    analyzer and modulation statistics.
    """
    if not modulation:
        return None

    mod = str(modulation).upper().replace("-", "").replace("_", "").strip()
    if mod == "QPSK":
        return 4

    match = _QAM_RE.fullmatch(mod)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def canonical_modulation_label(modulation: object) -> tuple[str, int | None]:
    """Return a display label and numeric QAM order for a modulation value."""
    if not modulation:
        return ("Unknown", None)

    raw = str(modulation).upper().replace("-", "").strip()
    qam_order = parse_qam_order(modulation)
    if qam_order is not None:
        return (f"{qam_order}QAM", qam_order)

    if raw in ("OFDM", "OFDMA"):
        return (raw, None)

    return ("Unknown", None)


def qam_rank(modulation):
    """Get QAM rank for any modulation format.

    Handles both driver formats: "256QAM" (Ultra Hub 7, CM3500)
    and "qam_256" (Vodafone Station, CH7465, TC4400).

    Returns 0 for unknown/empty modulation.
    """
    qam_order = parse_qam_order(modulation)
    if qam_order is None:
        return 0
    return QAM_ORDER.get(f"{qam_order}QAM", 0)
