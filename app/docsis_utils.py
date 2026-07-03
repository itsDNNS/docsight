"""Shared DOCSIS utilities — channel families, QAM parsing, and modulation labels."""

from __future__ import annotations

import re
from typing import Literal

Direction = Literal["ds", "us", "downstream", "upstream", "DS", "US"]
DocsisChannelFamily = Literal["sc_qam", "ofdm", "ofdma", "unknown"]

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
_MODULATION_THRESHOLD_ALIASES = {
    "OFDM": "4096QAM",
    "OFDMA": "4096QAM",
}


def _compact_text(*values: object) -> str:
    return " ".join(str(value) for value in values if value not in (None, "")).upper().replace("-", "").replace("_", "")


def _direction_key(direction: Direction) -> Literal["ds", "us"]:
    value = str(direction).strip().lower()
    if value in {"ds", "downstream"}:
        return "ds"
    if value in {"us", "upstream"}:
        return "us"
    raise ValueError(f"Unsupported DOCSIS direction: {direction!r}")


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


def classify_channel_family(direction: Direction, channel: dict) -> DocsisChannelFamily:
    """Classify a DOCSIS channel into the shared signal family taxonomy.

    This helper is the single interpretation point for downstream/upstream
    channel-family semantics used by analyzer, events, reports, and modulation
    analytics. It intentionally keeps degraded OFDM/OFDMA profile QAM labels on
    the OFDM/OFDMA family when DOCSIS 3.1/4.0 context or profile metadata says
    the channel is an OFDM-family carrier.
    """
    direction_key = _direction_key(direction)
    docsis_version = str(channel.get("docsis_version", "") or "")
    is_docsis31_plus = "3.1" in docsis_version or "4.0" in docsis_version
    type_text = _compact_text(channel.get("type"), channel.get("channel_type"))
    multiplex_text = _compact_text(channel.get("multiplex"))
    modulation_text = _compact_text(channel.get("modulation"))
    profile_text = _compact_text(channel.get("profile_modulation"), channel.get("profileModulation"))

    if direction_key == "ds":
        if "OFDM" in type_text or "OFDMA" in type_text:
            return "ofdm"
        if "SCQAM" in type_text or type_text == "QAM":
            return "sc_qam"
        if "OFDM" in modulation_text or "OFDMA" in modulation_text:
            return "ofdm"

        modulation_order = parse_qam_order(modulation_text)
        if modulation_order:
            if modulation_order >= 1024 and is_docsis31_plus:
                return "ofdm"
            return "sc_qam"

        # Profile modulation is an OFDM profile signal, not necessarily an
        # SC-QAM channel type. Degraded 3.1 OFDM profiles must remain on OFDM.
        if profile_text and is_docsis31_plus:
            return "ofdm"
        if parse_qam_order(profile_text):
            return "sc_qam"

        if is_docsis31_plus:
            return "ofdm"
        if "3.0" in docsis_version:
            return "sc_qam"
        return "unknown"

    if "OFDMA" in type_text or "OFDMA" in multiplex_text:
        return "ofdma"
    if any(token in f"{type_text} {multiplex_text}" for token in ("ATDMA", "SCQAM", "TDMA")):
        return "sc_qam"
    if "OFDMA" in modulation_text:
        return "ofdma"
    if profile_text and is_docsis31_plus:
        return "ofdma"
    if is_docsis31_plus:
        return "ofdma"
    if parse_qam_order(modulation_text):
        return "sc_qam"
    if "3.0" in docsis_version:
        return "sc_qam"
    return "unknown"


def channel_type_label(direction: Direction, channel: dict, fallback: dict | None = None) -> str:
    """Return a concise family label for event/report details."""
    fallback = fallback or {}
    merged = {**fallback, **{k: v for k, v in channel.items() if v not in (None, "")}}
    family = classify_channel_family(direction, merged)
    if family == "sc_qam":
        return "SC-QAM"
    if family == "ofdm":
        return "OFDM"
    if family == "ofdma":
        return "OFDMA"
    return ""


def modulation_threshold_key(modulation: object, section: dict, *, default: str = "256QAM") -> str:
    """Resolve a modulation value to the key used by a threshold section."""
    value = str(modulation or "").upper().replace("-", "").replace("_", "").strip()
    if value in section:
        return value
    fallback = section.get("_default", default)
    if not isinstance(fallback, str) or not fallback:
        fallback = default
    return _MODULATION_THRESHOLD_ALIASES.get(value, fallback)


def sc_qam_capacity_family(direction: Direction, channel: dict) -> Literal["sc_qam", "unsupported"]:
    """Return whether a channel can use the SC-QAM Layer-1 capacity formula."""
    return "sc_qam" if classify_channel_family(direction, channel) == "sc_qam" else "unsupported"
