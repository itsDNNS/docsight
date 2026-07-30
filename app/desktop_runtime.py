"""Loopback and token policy for the desktop-only runtime endpoint."""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Mapping

from .desktop_runtime_contract import (
    DESKTOP_MODE_ENV,
    INSTANCE_TOKEN_ENV,
    RuntimeState,
    is_valid_instance_token,
)


def desktop_runtime_payload(
    *,
    env: Mapping[str, str],
    remote_address: str | None,
    authorization: str | None,
) -> tuple[dict[str, object], int]:
    """Return the desktop runtime payload only for an authenticated loopback peer."""
    if env.get(DESKTOP_MODE_ENV) != "1":
        return {"status": "not_found"}, 404
    if not _is_loopback(remote_address):
        return {"status": "forbidden"}, 403

    token = env.get(INSTANCE_TOKEN_ENV, "")
    if not is_valid_instance_token(token) or not _authorization_matches(
        authorization,
        token,
    ):
        return {"status": "not_found"}, 404

    try:
        state = RuntimeState.from_environment(env)
    except ValueError:
        return {"status": "not_found"}, 404

    return {"status": "ok", **state.to_mapping()}, 200


def _is_loopback(address: str | None) -> bool:
    try:
        return address is not None and ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def _authorization_matches(authorization: str | None, token: str) -> bool:
    if authorization is None:
        return False
    try:
        observed = authorization.encode("ascii")
    except UnicodeEncodeError:
        return False
    expected = f"Bearer {token}".encode("ascii")
    return secrets.compare_digest(observed, expected)
