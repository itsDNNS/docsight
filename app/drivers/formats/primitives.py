"""Small pure value primitives shared only where modem semantics agree."""

from __future__ import annotations

import math
import re
from types import MappingProxyType


_MOD_TOKEN_SPLIT = re.compile(r"[\s_\-]+")
_FIRST_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")

# Annex B (6 MHz) downstream tables often omit the symbol rate. Without these
# the analyzer falls back to the EuroDOCSIS 8 MHz default and every downstream
# capacity estimate reads ~30% high.
ANNEX_B_DOWNSTREAM_SYMBOL_RATES = MappingProxyType({"64QAM": 5057, "256QAM": 5361})


def parse_number(value: str) -> float | None:
    """Parse the leading finite number; empty, unreadable or non-finite text is None, never 0."""
    parts = (value or "").split()
    return parse_optional_finite_float(parts[0]) if parts else None


def parse_first_number(value: str) -> float | None:
    """Parse the first number in a cell, ignoring thousands separators; missing is None."""
    if not value:
        return None
    match = _FIRST_NUMBER.search(value.replace(",", ""))
    return float(match.group(0)) if match else None


def parse_optional_finite_float(value: object) -> float | None:
    """Parse a finite float and preserve missing/invalid values as unsupported."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def hz_to_mhz(freq: object) -> str:
    """Convert numeric or unit-bearing frequency input to the legacy MHz string."""
    if isinstance(freq, (int, float)) and math.isfinite(freq):
        return _format_mhz(float(freq) / 1_000_000)

    freq_str = str(freq).strip()
    mhz = _optional_mhz(freq_str)
    return freq_str if mhz is None else _format_mhz(mhz)


def _format_mhz(mhz: float) -> str:
    return f"{int(mhz)} MHz" if mhz == int(mhz) else f"{mhz:.1f} MHz"


def normalize_modulation(modulation: object) -> str:
    """Normalize the finite modulation spellings used across compatible profiles."""
    if modulation is None:
        return ""
    raw = str(modulation).strip()
    if not raw:
        return ""
    mod = _MOD_TOKEN_SPLIT.sub("", raw).lower()
    if not mod:
        return raw.upper()
    if "qpsk" in mod:
        return "QPSK"
    if "ofdma" in mod:
        return "OFDMA"
    if "ofdm" in mod:
        return "OFDM"
    if "atdma" in mod:
        return "ATDMA"
    if mod == "tdma":
        return "TDMA"
    if "qam" in mod:
        number = mod.replace("qam", "")
        if number.isdigit():
            return f"{number}QAM"
        return "QAM" if not number else f"{number.upper()}QAM"
    return raw.upper()


def normalize_mhz(freq_str: str) -> str:
    """Normalize an already-MHz value to the established display string."""
    number = parse_number(freq_str)
    return freq_str if number is None else _format_mhz(number)


def parse_mhz_value(freq_str: str) -> float:
    """Parse Hz/kHz/MHz input to a numeric MHz value with the legacy zero fallback."""
    mhz = _optional_mhz(freq_str)
    return 0.0 if mhz is None else mhz


def _optional_mhz(freq_str: str) -> float | None:
    value = parse_number(freq_str)
    if value is None:
        return None
    parts = freq_str.split()
    unit = parts[1].lower() if len(parts) > 1 else ""
    if unit == "hz":
        return value / 1_000_000
    if unit == "khz":
        return value / 1_000
    if unit == "mhz":
        return value
    if value > 1_000_000:
        return value / 1_000_000
    if value > 1_000:
        return value / 1_000
    return value
