"""Worker-safe port, readiness, diagnostics, and process cleanup ownership."""

from __future__ import annotations

import multiprocessing
import os
import re
import socket
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

_MP_CTX = multiprocessing.get_context("spawn")
_IDENTITY_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class ReadinessError(RuntimeError):
    """A child exited or failed to become healthy."""


class HarnessCleanupError(RuntimeError):
    """One or more child processes or listening ports leaked."""


@dataclass
class PortReservation:
    """A localhost port held by an OS-bound socket until child handoff."""

    _socket: socket.socket
    _closed: bool = False

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._socket.getsockname()[:2]
        return str(host), int(port)

    @property
    def port(self) -> int:
        return self.address[1]

    @property
    def socket(self) -> socket.socket:
        if self._closed:
            raise RuntimeError("port reservation is already closed")
        return self._socket

    def close(self) -> None:
        if not self._closed:
            self._socket.close()
            self._closed = True


def reserve_local_port() -> PortReservation:
    """Ask the OS for and retain one isolated IPv4 localhost port."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    return PortReservation(listener)


@dataclass(frozen=True)
class ServerEndpoint:
    identity: str
    port: int
    mount_path: str
    log_path: Path | None
    readiness_headers: tuple[tuple[str, str], ...] = ()

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.mount_path}/health"


@dataclass(frozen=True)
class ProcessSpec:
    """Everything needed to start and diagnose one isolated child."""

    identity: str
    reservation: PortReservation = field(repr=False, compare=False)
    process_target: Callable[..., None] = field(repr=False, compare=False)
    args: tuple[Any, ...] = field(default=(), repr=False, compare=False)
    readiness_path: str = ""
    readiness_headers: tuple[tuple[str, str], ...] = ()
    log_path: Path | None = None
    secrets: tuple[str, ...] = field(default=(), repr=False, compare=False)
    data_path: str | None = None

    @property
    def endpoint(self) -> ServerEndpoint:
        return ServerEndpoint(
            self.identity,
            self.reservation.port,
            self.readiness_path,
            self.log_path,
            self.readiness_headers,
        )


class _RedactingWriter:
    def __init__(self, stream, secrets: Sequence[str]):
        self._stream = stream
        self._secrets = tuple(secret for secret in secrets if secret)

    def write(self, value):
        for secret in self._secrets:
            value = value.replace(secret, "<redacted>")
        return self._stream.write(value)

    def flush(self):
        return self._stream.flush()


def _run_logged(
    log_path: str | None,
    secrets: tuple[str, ...],
    process_target: Callable[..., None],
    args: tuple[Any, ...],
    listener_socket: socket.socket | None,
) -> None:
    if log_path is None:
        process_target(*args, listener_socket=listener_socket)
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as raw_log:
        log = _RedactingWriter(raw_log, secrets)
        with redirect_stdout(log), redirect_stderr(log):
            try:
                process_target(*args, listener_socket=listener_socket)
            except BaseException:  # noqa: BLE001 - redact every child-boundary failure
                traceback.print_exc()
                raise SystemExit(1) from None


def _log_tail(path: Path | None, limit: int = 4000) -> str:
    if path is None:
        return "<log capture disabled>"
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        return f"<log unavailable: {exc}>"


def wait_for_server(
    endpoint: ServerEndpoint,
    process,
    *,
    timeout: float = 150,
    request_get: Callable[..., Any] = requests.get,
) -> None:
    """Wait for health, failing immediately on child exit with diagnostics."""

    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        if process.exitcode is not None:
            raise ReadinessError(
                f"{endpoint.identity} exited with exit code {process.exitcode} "
                f"before {endpoint.health_url} became ready. Log tail:\n"
                f"{_log_tail(endpoint.log_path)}"
            )
        try:
            response = request_get(
                endpoint.health_url,
                timeout=2,
                headers=dict(endpoint.readiness_headers),
            )
            last_status = response.status_code
            if last_status == 200:
                return
        except requests.RequestException as exc:
            last_status = type(exc).__name__
        time.sleep(0.3)
    raise ReadinessError(
        f"{endpoint.identity} did not become ready at {endpoint.health_url} "
        f"within {timeout}s (last result: {last_status}). Log tail:\n"
        f"{_log_tail(endpoint.log_path)}"
    )


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def cleanup_processes(
    processes: Sequence[tuple[Any, ServerEndpoint]],
    *,
    join_timeout: float = 5,
    port_is_open: Callable[[int], bool] = _port_is_open,
) -> None:
    """Terminate, join, kill if required, and prove every port is closed."""

    for process, _endpoint in processes:
        if process.is_alive():
            process.terminate()
    for process, _endpoint in processes:
        process.join(join_timeout)
    for process, _endpoint in processes:
        if process.is_alive():
            process.kill()
            process.join(join_timeout)

    failures = []
    for process, endpoint in processes:
        if process.is_alive():
            failures.append(
                f"{endpoint.identity} process remained alive after kill"
            )
            continue
        deadline = time.monotonic() + join_timeout
        while port_is_open(endpoint.port) and time.monotonic() < deadline:
            time.sleep(0.05)
        if port_is_open(endpoint.port):
            failures.append(
                f"{endpoint.identity} port {endpoint.port} remained open"
            )
    if failures:
        raise HarnessCleanupError("; ".join(failures))


def _validate_specs(specs: Sequence[ProcessSpec]) -> None:
    identities = [spec.identity for spec in specs]
    ports = [spec.reservation.port for spec in specs]
    if len(set(identities)) != len(identities):
        raise ValueError("process identities must be unique")
    if len(set(ports)) != len(ports):
        raise ValueError("process ports must be unique")
    data_paths = [spec.data_path for spec in specs if spec.data_path is not None]
    if len(set(data_paths)) != len(data_paths):
        raise ValueError("application data paths must be unique")


@contextmanager
def running_processes(specs: Sequence[ProcessSpec]) -> Iterator[None]:
    """Run a healthy isolated process group and enforce clean teardown."""

    _validate_specs(specs)
    started = []
    try:
        for spec in specs:
            endpoint = spec.endpoint
            listener = spec.reservation.socket
            process = _MP_CTX.Process(
                name=spec.identity,
                target=_run_logged,
                args=(
                    str(spec.log_path) if spec.log_path else None,
                    spec.secrets,
                    spec.process_target,
                    spec.args,
                    listener,
                ),
                daemon=True,
            )
            process.start()
            spec.reservation.close()
            started.append((process, endpoint))
        for process, endpoint in started:
            wait_for_server(endpoint, process)
        yield
    finally:
        for spec in specs:
            spec.reservation.close()
        cleanup_processes(started)


def artifact_log_path(identity: str) -> Path:
    root = Path(os.environ.get("E2E_ARTIFACT_DIR", "test-results/e2e"))
    safe_identity = _IDENTITY_PATTERN.sub("-", identity).strip("-")
    return root / "server-logs" / f"{safe_identity}.log"
