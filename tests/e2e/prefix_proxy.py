"""Test-only network proxy for prefix-stripping browser qualification."""

from __future__ import annotations

import http.client
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


def serve_prefix_proxy(
    listen_port: int,
    upstream_port: int,
    mount_path: str,
    forwarded_prefix_chain: str | None,
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
                response_connection_tokens = {
                    item.strip().lower()
                    for name, value in response.getheaders()
                    if name.lower() == "connection"
                    for item in value.split(",")
                    if item.strip()
                }
                response_excluded = (
                    _HOP_BY_HOP_HEADERS
                    | response_connection_tokens
                    | {"content-length"}
                )
            except (OSError, http.client.HTTPException):
                self._plain_response(502, b"Bad Gateway\n")
                return
            finally:
                connection.close()

            try:
                self.send_response(response.status, response.reason)
                for name, value in response.getheaders():
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
        ("127.0.0.1", listen_port), PrefixProxyHandler
    )
    server.serve_forever()
