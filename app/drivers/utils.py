"""Shared utility functions for modem drivers.

These helpers are duplicated across many drivers. Centralising them here
ensures consistent parsing behaviour and makes future changes propagate
automatically.
"""

import logging
import ssl

from requests.adapters import HTTPAdapter

log = logging.getLogger("docsis.drivers.utils")


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------

def parse_number(value: str) -> float:
    """Parse a numeric value from a string with an optional unit suffix.

    Examples::

        '43.3 dBmV' -> 43.3
        '-0.32 dBmV' -> -0.32
        '41.8 dB' -> 41.8
        '10.50 dBmV' -> 10.5
        '5.120 Msym/sec' -> 5.12
        '' -> 0.0

    Duplicated in: cm3000, cm3500, tc4400, sb6141, sb6190, arris_html,
    ultrahub7 (_parse_power, _parse_snr, _parse_frequency).
    """
    if not value:
        return 0.0
    parts = value.strip().split()
    try:
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def hz_to_mhz(freq) -> str:
    """Convert a frequency value (Hz) to a human-readable MHz string.

    Accepts int, float, or string inputs.

    Examples::

        591000000   -> '591 MHz'
        495000000   -> '495 MHz'
        29200000    -> '29.2 MHz'
        '795000000 Hz' -> '795 MHz'
        '350000 kHz'   -> '350 MHz'  (string with kHz — handled via parse)
        0              -> '0 MHz'

    Duplicated in: cm3000, cm3500, surfboard, sb6141, sb6190, hitron,
    sagemcom, arris_html, cgm4981.
    """
    # Numeric input (int or float)
    if isinstance(freq, (int, float)):
        if freq == 0:
            return "0 MHz"
        mhz = float(freq) / 1_000_000
        if mhz == int(mhz):
            return f"{int(mhz)} MHz"
        return f"{mhz:.1f} MHz"

    # String input — parse Hz value and optional unit
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


def normalize_mhz(freq_str: str) -> str:
    """Normalise a frequency string already in MHz to a clean format.

    Examples::

        '465.00 MHz' -> '465 MHz'
        '17  MHz'    -> '17 MHz'
        '29.2'       -> '29.2 MHz'  (no unit)

    Used by sb6190, cm3500.
    """
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


# ---------------------------------------------------------------------------
# TLS adapters for modems with legacy/weak certificates
# ---------------------------------------------------------------------------

def make_legacy_tls_adapter(sec_level: int = 1) -> HTTPAdapter:
    """Create an HTTPS adapter that accepts weak modem certificates.

    Many cable modems ship with self-signed certificates using short RSA/DH
    keys that modern OpenSSL (3.x) rejects at the default security level.
    This factory returns an adapter that lowers the security level just
    enough for the modem's TLS stack.

    Args:
        sec_level: OpenSSL security level (0 for CM8200A, 1 for others).
                   The surfboard driver uses its own variant with
                   ssl.PROTOCOL_TLS_CLIENT and OP_LEGACY_SERVER_CONNECT.

    Duplicated in: sb6190, cm8200, hitron (all sec_level=1 except
    cm8200 which uses 0).
    """
    return _LegacyTLSAdapter(sec_level=sec_level)


class _LegacyTLSAdapter(HTTPAdapter):
    """HTTPS adapter for modems with weak TLS configurations.

    Consolidates the four near-identical _LegacyTLSAdapter classes from
    sb6190.py, cm8200.py, hitron.py. The surfboard driver uses a different
    approach (ssl.PROTOCOL_TLS_CLIENT + OP_LEGACY_SERVER_CONNECT) so it
    keeps its own implementation.
    """

    def __init__(self, sec_level: int = 1, **kwargs):
        self._sec_level = sec_level
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        from urllib3.util.ssl_ import create_urllib3_context
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers(f"DEFAULT:@SECLEVEL={self._sec_level}")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)
