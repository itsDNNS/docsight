"""Small pure value primitives shared only where modem semantics agree."""

from __future__ import annotations

import math
import re


_MOD_TOKEN_SPLIT = re.compile(r"[\s_\-]+")


def parse_number(value: str) -> float:
    """Parse the leading number, preserving the established zero fallback."""
    if not value:
        return 0.0
    parts = value.strip().split()
    try:
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def parse_optional_finite_float(value: object) -> float | None:
    """Parse a finite float and preserve missing/invalid values as unsupported."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def hz_to_mhz(freq: object) -> str:
    """Convert numeric or unit-bearing frequency input to the legacy MHz string."""
    if isinstance(freq, (int, float)):
        if freq == 0:
            return "0 MHz"
        mhz = float(freq) / 1_000_000
        if mhz == int(mhz):
            return f"{int(mhz)} MHz"
        return f"{mhz:.1f} MHz"

    freq_str = str(freq).strip()
    if not freq_str:
        return ""
    parts = freq_str.split()
    try:
        val = float(parts[0])
    except (ValueError, IndexError):
        return freq_str

    unit = parts[1].lower() if len(parts) > 1 else ""
    if unit == "hz":
        mhz = val / 1_000_000
    elif unit == "khz":
        mhz = val / 1_000
    elif unit == "mhz":
        mhz = val
    elif val > 1_000_000:
        mhz = val / 1_000_000
    elif val > 1_000:
        mhz = val / 1_000
    else:
        mhz = val

    if mhz == int(mhz):
        return f"{int(mhz)} MHz"
    return f"{mhz:.1f} MHz"


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
    if not freq_str:
        return ""
    parts = freq_str.strip().split()
    try:
        mhz = float(parts[0])
        if mhz == int(mhz):
            return f"{int(mhz)} MHz"
        return f"{mhz:.1f} MHz"
    except (ValueError, IndexError):
        return freq_str


def parse_mhz_value(freq_str: str) -> float:
    """Parse Hz/kHz/MHz input to a numeric MHz value with the legacy zero fallback."""
    if not freq_str:
        return 0.0
    parts = freq_str.strip().split()
    try:
        value = float(parts[0])
    except (IndexError, ValueError):
        return 0.0
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
