"""Container-local health probe for DOCSight's HTTP endpoint."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from .base_path import normalize_base_path, parse_trusted_prefix_hops

_DEFAULT_WEB_PORT = "8765"
_SYNTHETIC_PROBE_PREFIX = "/container-health-probe"
_MAX_RESPONSE_BYTES = 64 * 1024
_PORT_RE = re.compile(r"[0-9]+\Z")
_FAILURE_MESSAGE = "DOCSight healthcheck failed"


def _probe_request(environ: Mapping[str, str]) -> urllib.request.Request:
    port = environ.get("WEB_PORT", _DEFAULT_WEB_PORT)
    if _PORT_RE.fullmatch(port) is None or not 1 <= int(port) <= 65535:
        raise ValueError("invalid healthcheck port")

    raw_base_path = environ.get("BASE_PATH")
    base_path = normalize_base_path(raw_base_path)
    explicit_base_path = raw_base_path is not None and raw_base_path != ""
    trusted_hops = parse_trusted_prefix_hops(environ.get("REVERSE_PROXY_PREFIX"))

    headers = {}
    if trusted_hops:
        selected_prefix = (
            base_path if explicit_base_path else _SYNTHETIC_PROBE_PREFIX
        )
        header_entry = selected_prefix or "/"
        headers["X-Forwarded-Prefix"] = ", ".join(
            [header_entry] * trusted_hops
        )

    return urllib.request.Request(
        f"http://localhost:{port}/health",
        headers=headers,
        method="GET",
    )


def _probe(
    environ: Mapping[str, str],
    open_url: Callable[..., Any],
) -> bool:
    request = _probe_request(environ)
    with open_url(request, timeout=4) as response:
        if not 200 <= response.status < 300:
            return False
        raw_payload = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw_payload) > _MAX_RESPONSE_BYTES:
        return False
    payload = json.loads(raw_payload)
    return isinstance(payload, dict) and payload.get("status") == "ok"


def main(
    environ: Mapping[str, str] | None = None,
    open_url: Callable[..., Any] | None = None,
) -> int:
    """Return a process exit code without reflecting sensitive probe inputs."""

    try:
        healthy = _probe(
            os.environ if environ is None else environ,
            urllib.request.urlopen if open_url is None else open_url,
        )
    except Exception:
        healthy = False
    if not healthy:
        print(_FAILURE_MESSAGE, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
