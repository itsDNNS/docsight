"""Shared utility functions for modem drivers.

These helpers are duplicated across many drivers. Centralising them here
ensures consistent parsing behaviour and makes future changes propagate
automatically.
"""

import hashlib
import logging
import ssl

from requests.adapters import HTTPAdapter

from .formats.primitives import (
    hz_to_mhz,
    normalize_mhz,
    normalize_modulation,
    parse_number,
    parse_optional_finite_float,
)

__all__ = [
    "hz_to_mhz",
    "make_legacy_tls_adapter",
    "normalize_mhz",
    "normalize_modulation",
    "parse_number",
    "parse_optional_finite_float",
    "pbkdf2_sha256",
]

log = logging.getLogger("docsis.drivers.utils")


def pbkdf2_sha256(key_material: bytes, salt: bytes, *, length: int = 16, iterations: int = 1000) -> bytes:
    """Derive PBKDF2-HMAC-SHA256 bytes.

    Args:
        key_material: Password or other secret bytes to derive from.
        salt: Salt bytes used for the derivation.
        length: Derived key length in bytes.
        iterations: PBKDF2 iteration count.
    """
    return hashlib.pbkdf2_hmac("sha256", key_material, salt, iterations, dklen=length)


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
