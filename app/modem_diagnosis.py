"""Explain why a modem connection test failed.

Drivers report most problems as plain exceptions with free-form messages, so
the reason is derived from what can be checked: whether the address answers
at all, HTTP status codes and connection errors in the exception chain, and
which step (login or reading the device) failed.
"""

from __future__ import annotations

import re
import socket
from urllib.parse import urlsplit

import requests

REACHABILITY_TIMEOUT_SECONDS = 3.0

UNREACHABLE = "unreachable"
AUTH = "auth"
UNEXPECTED = "unexpected"

HELP_URLS = {
    UNREACHABLE: "https://github.com/itsDNNS/docsight/wiki/Bridge-Mode-Compatibility#modem-not-reachable",
    AUTH: "https://github.com/itsDNNS/docsight/wiki/Supported-Modems",
    UNEXPECTED: "https://github.com/itsDNNS/docsight/wiki/Requesting-Modem-Support",
}

_CONNECTION_MESSAGE = re.compile(
    r"connection (refused|reset|aborted)|timed out|timeout|unreachable|no route to host"
    r"|name or service not known|nodename nor servname|failed to establish",
    re.IGNORECASE,
)
_AUTH_MESSAGE = re.compile(
    r"authenticat|credential|password|unauthori[sz]ed|forbidden|login (failed|rejected)|invalid login",
    re.IGNORECASE,
)


def host_reachable(url: str, connect=socket.create_connection) -> bool:
    """True when something accepts a TCP connection at the URL's host and port."""
    try:
        parts = urlsplit(url if "://" in url else f"http://{url}")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if not parts.hostname:
            return False
        connect((parts.hostname, port), timeout=REACHABILITY_TIMEOUT_SECONDS).close()
        return True
    except (OSError, ValueError):
        return False


def _chain(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def classify_failure(exc: BaseException, stage: str) -> str:
    """'unreachable', 'auth' or 'unexpected' for a failure in 'login' or 'read'."""
    chain = list(_chain(exc))
    for error in chain:
        response = getattr(error, "response", None)
        if isinstance(error, requests.HTTPError) and getattr(response, "status_code", None) in (401, 403):
            return AUTH
    if any(isinstance(error, (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError, socket.timeout))
           for error in chain):
        return UNREACHABLE
    messages = " ".join(str(error) for error in chain)
    if _CONNECTION_MESSAGE.search(messages):
        return UNREACHABLE
    if stage == "login" and _AUTH_MESSAGE.search(messages):
        return AUTH
    return UNEXPECTED
