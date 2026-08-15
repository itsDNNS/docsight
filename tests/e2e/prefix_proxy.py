"""Test-only network proxy for prefix-stripping browser qualification."""

from __future__ import annotations

import http.client
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_MAX_REASON_LENGTH = 256
_MAX_HEADER_NAME_LENGTH = 128
_MAX_HEADER_VALUE_LENGTH = 8192
_HEADER_NAME_TEXT = (
    "!#$%&'*+-.^_`|~ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)
_HEADER_NAME_CHARACTERS = frozenset(_HEADER_NAME_TEXT)
_LATIN1_CHARACTERS = tuple(chr(codepoint) for codepoint in range(256))


def _validated_field_text(value: object, max_length: int) -> str:
    """Return a bounded, reconstructed field value without splitting bytes."""

    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError("invalid upstream response metadata")
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError("invalid upstream response metadata") from exc
    if not all(
        character == "\t"
        or 0x20 <= ord(character) <= 0x7E
        or ord(character) >= 0x80
        for character in value
    ):
        raise ValueError("invalid upstream response metadata")
    return "".join(_LATIN1_CHARACTERS[ord(character)] for character in value)


def _validated_header_name(value: object) -> str:
    """Return a reconstructed RFC token suitable for ``send_header``."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_HEADER_NAME_LENGTH
        or any(character not in _HEADER_NAME_CHARACTERS for character in value)
    ):
        raise ValueError("invalid upstream response metadata")
    return "".join(_LATIN1_CHARACTERS[ord(character)] for character in value)


def _validate_upstream_response_metadata(
    status: object,
    reason: object,
    headers: list[tuple[str, str]],
) -> tuple[int, str, list[tuple[str, str]]]:
    """Validate upstream metadata before it reaches BaseHTTPRequestHandler."""

    if (
        isinstance(status, bool)
        or not isinstance(status, int)
        or not 100 <= status <= 599
    ):
        raise ValueError("invalid upstream response metadata")
    safe_reason = _validated_field_text(reason, _MAX_REASON_LENGTH)

    validated_headers = []
    for name, value in headers:
        safe_name = _validated_header_name(name)
        safe_value = _validated_field_text(value, _MAX_HEADER_VALUE_LENGTH)
        validated_headers.append((safe_name, safe_value))
    return status, safe_reason, validated_headers


def serve_prefix_proxy(
    listen_port: int,
    upstream_port: int,
    mount_path: str,
    forwarded_prefix_chain: str | None,
    *,
    listener_socket: socket.socket | None = None,
) -> None:
    """Serve one quiet same-origin prefix boundary until terminated."""

    class PrefixProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            return

        def _plain_response(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self.close_connection = True

        def _proxy(self) -> None:
            parsed = urlsplit(self.path)
            if (
                parsed.scheme
                or parsed.netloc
                or self.headers.get("Host") != f"127.0.0.1:{listen_port}"
            ):
                self._plain_response(400, b"Bad Request\n")
                return
            if not (
                parsed.path == mount_path
                or parsed.path.startswith(mount_path + "/")
            ):
                self._plain_response(404, b"Not Found\n")
                return
            if self.headers.get("Transfer-Encoding"):
                self._plain_response(400, b"Bad Request\n")
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length < 0:
                    raise ValueError
            except ValueError:
                self._plain_response(400, b"Bad Request\n")
                return
            body = self.rfile.read(content_length) if content_length else None

            connection_tokens = {
                item.strip().lower()
                for item in self.headers.get("Connection", "").split(",")
                if item.strip()
            }
            excluded = _HOP_BY_HOP_HEADERS | connection_tokens | {
                "content-length",
                "host",
                "x-forwarded-prefix",
            }
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() not in excluded
            }
            if body is not None:
                headers["Content-Length"] = str(len(body))
            if forwarded_prefix_chain is not None:
                headers["X-Forwarded-Prefix"] = forwarded_prefix_chain

            upstream_path = parsed.path[len(mount_path) :] or "/"
            if parsed.query:
                upstream_path = f"{upstream_path}?{parsed.query}"

            connection = http.client.HTTPConnection(
                "127.0.0.1", upstream_port, timeout=15
            )
            try:
                connection.request(
                    self.command,
                    upstream_path,
                    body=body,
                    headers=headers,
                )
                response = connection.getresponse()
                response_body = response.read()
                response_headers = response.getheaders()
                response_status, response_reason, response_headers = (
                    _validate_upstream_response_metadata(
                        response.status,
                        response.reason,
                        response_headers,
                    )
                )
                response_connection_tokens = {
                    item.strip().lower()
                    for name, value in response_headers
                    if name.lower() == "connection"
                    for item in value.split(",")
                    if item.strip()
                }
                response_excluded = (
                    _HOP_BY_HOP_HEADERS
                    | response_connection_tokens
                    | {"content-length"}
                )
            except (OSError, ValueError, http.client.HTTPException):
                self._plain_response(502, b"Bad Gateway\n")
                return
            finally:
                connection.close()

            try:
                self.send_response(response_status, response_reason)
                for name, value in response_headers:
                    if name.lower() not in response_excluded:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(response_body)
                self.close_connection = True
            except OSError:
                return

        do_DELETE = _proxy
        do_GET = _proxy
        do_HEAD = _proxy
        do_OPTIONS = _proxy
        do_PATCH = _proxy
        do_POST = _proxy
        do_PUT = _proxy

    class QuietThreadingHTTPServer(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            return

    server = QuietThreadingHTTPServer(
        ("127.0.0.1", listen_port),
        PrefixProxyHandler,
        bind_and_activate=listener_socket is None,
    )
    if listener_socket is not None:
        server.socket.close()
        server.socket = listener_socket
        server.server_address = listener_socket.getsockname()
        server.server_activate()
    server.serve_forever()
