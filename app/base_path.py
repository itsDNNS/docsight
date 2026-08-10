"""Safe base-path handling for proxy-stripped WSGI deployments."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from typing import Any

from flask import Flask, has_request_context, request
from flask.sessions import SecureCookieSessionInterface
from werkzeug.http import parse_list_header

_MAX_BASE_PATH_LENGTH = 1024
_MAX_SEGMENT_LENGTH = 128
_MAX_TRUSTED_PREFIX_HOPS = 32
_SEGMENT_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-"
)
_HOPS_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_BAD_REQUEST_BODY = b"Bad Request\n"


class BasePathConfigurationError(ValueError):
    """Raised when base-path trust configuration is unsafe or ambiguous."""


def _valid_segment(segment: str) -> bool:
    """Validate one bounded base-path segment with no regex backtracking."""

    return (
        bool(segment)
        and len(segment) <= _MAX_SEGMENT_LENGTH
        and segment not in {".", ".."}
        and all(character in _SEGMENT_CHARACTERS for character in segment)
    )


def normalize_base_path(value: str | None) -> str:
    """Validate and normalize a configured or request-supplied mount path."""

    if value is None or value == "" or value == "/":
        return ""
    if not isinstance(value, str) or len(value) > _MAX_BASE_PATH_LENGTH:
        raise BasePathConfigurationError("BASE_PATH is invalid")
    if value != value.strip() or not value.startswith("/") or value.endswith("/"):
        raise BasePathConfigurationError("BASE_PATH is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BasePathConfigurationError("BASE_PATH is invalid")
    if any(marker in value for marker in ("\\", "%", "?", "#", "//")):
        raise BasePathConfigurationError("BASE_PATH is invalid")

    segments = value[1:].split("/")
    if any(not _valid_segment(segment) for segment in segments):
        raise BasePathConfigurationError("BASE_PATH is invalid")
    return value


def parse_trusted_prefix_hops(value: str | None) -> int:
    """Parse the trusted X-Forwarded-Prefix hop count without coercion."""

    if value is None or value == "":
        return 0
    if not isinstance(value, str) or _HOPS_RE.fullmatch(value) is None:
        raise BasePathConfigurationError("REVERSE_PROXY_PREFIX is invalid")
    hops = int(value)
    if hops > _MAX_TRUSTED_PREFIX_HOPS:
        raise BasePathConfigurationError("REVERSE_PROXY_PREFIX is invalid")
    return hops


def _trusted_header_value(trusted_hops: int, value: str | None) -> str | None:
    """Select a list-header value with Werkzeug ProxyFix semantics."""

    if not trusted_hops:
        return None
    values = parse_list_header(value or "")
    if len(values) >= trusted_hops:
        return values[-trusted_hops] or None
    return None


def _bad_request(start_response: Callable[..., Any]) -> Iterable[bytes]:
    start_response(
        "400 Bad Request",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(_BAD_REQUEST_BODY))),
            ("Cache-Control", "no-store"),
        ],
    )
    return [_BAD_REQUEST_BODY]


class BasePathMiddleware:
    """Set SCRIPT_NAME for an external prefix already stripped by a proxy."""

    def __init__(
        self,
        app: Callable[..., Iterable[bytes]],
        *,
        fixed_prefix: str | None,
        trusted_hops: int,
    ) -> None:
        self.app = app
        self.fixed_prefix = fixed_prefix
        self.trusted_hops = trusted_hops

    def __call__(
        self,
        environ: MutableMapping[str, Any],
        start_response: Callable[..., Any],
    ) -> Iterable[bytes]:
        existing_raw = environ.get("SCRIPT_NAME", "")
        existing_present = existing_raw != ""
        selected_raw = _trusted_header_value(
            self.trusted_hops,
            environ.get("HTTP_X_FORWARDED_PREFIX"),
        )
        if self.trusted_hops and selected_raw is None:
            return _bad_request(start_response)

        try:
            existing = normalize_base_path(existing_raw) if existing_present else None
            selected = normalize_base_path(selected_raw) if selected_raw is not None else None
        except BasePathConfigurationError:
            return _bad_request(start_response)

        sources = []
        if self.fixed_prefix is not None:
            sources.append(self.fixed_prefix)
        if selected_raw is not None:
            sources.append(selected)
        if existing_present:
            sources.append(existing)
        if len(set(sources)) > 1:
            return _bad_request(start_response)

        chosen = next(
            (
                prefix
                for prefix in (self.fixed_prefix, selected, existing)
                if prefix is not None
            ),
            "",
        )
        environ["SCRIPT_NAME"] = chosen
        return self.app(environ, start_response)


class RequestScopedCookieSessionInterface(SecureCookieSessionInterface):
    """Scope default session cookies to the request's external mount path."""

    def get_cookie_path(self, app: Flask) -> str:
        configured = app.config.get("SESSION_COOKIE_PATH")
        if configured is not None:
            return configured
        if not has_request_context():
            return "/"
        script_name = request.environ.get("SCRIPT_NAME", "")
        return f"{script_name}/" if script_name else "/"


def configure_base_path(
    app: Flask,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Validate environment configuration and install base-path behavior."""

    env = os.environ if environ is None else environ
    raw_fixed_prefix = env.get("BASE_PATH")
    normalized_fixed_prefix = normalize_base_path(raw_fixed_prefix)
    fixed_prefix = (
        normalized_fixed_prefix
        if raw_fixed_prefix is not None and raw_fixed_prefix != ""
        else None
    )
    trusted_hops = parse_trusted_prefix_hops(env.get("REVERSE_PROXY_PREFIX"))

    app.wsgi_app = BasePathMiddleware(
        app.wsgi_app,
        fixed_prefix=fixed_prefix,
        trusted_hops=trusted_hops,
    )
    app.session_interface = RequestScopedCookieSessionInterface()
