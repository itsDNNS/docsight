"""Durable runtime state and owner/follower desktop coordination."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from desktop_platform import (
    MutexHandle,
    ProcessIdentity,
    ProcessInspector,
    Win32NamedMutex,
    Win32ProcessInspector,
    mutex_name_for_user,
)

from app.desktop_runtime_contract import (
    DESKTOP_RUNTIME_ENV_NAMES,
    RuntimeState,
)

RUNTIME_ENDPOINT_PATH = "/desktop-runtime"
MAX_COORDINATION_WAIT_SECONDS = 10.0
_SHARING_VIOLATION_WINERRORS = frozenset({5, 32, 33})


class DesktopInstanceError(RuntimeError):
    """Base error for desktop runtime ownership failures."""


class InstanceUnavailableError(DesktopInstanceError):
    """Raised when another owner never becomes safely reusable."""


class RuntimeStateError(DesktopInstanceError):
    """Raised when durable runtime state cannot be safely maintained."""


class RuntimeStateStore:
    """Strict runtime-state I/O with bounded Windows sharing retries."""

    def __init__(
        self,
        path: Path,
        *,
        retry_attempts: int = 4,
        retry_delay_seconds: float = 0.025,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self.path = path
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._sleep = sleep

    def load(self) -> RuntimeState | None:
        try:
            raw = self._retry_sharing_violation(
                lambda: self.path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return None
        except UnicodeError:
            return None
        except OSError as exc:
            raise RuntimeStateError("unable to read desktop runtime state") from exc

        try:
            return RuntimeState.from_mapping(json.loads(raw))
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return None

    def replace(self, state: RuntimeState) -> None:
        validated = RuntimeState.from_mapping(state.to_mapping())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(
                    validated.to_mapping(),
                    handle,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._retry_sharing_violation(
                lambda: os.replace(temporary_path, self.path)
            )
        except OSError as exc:
            raise RuntimeStateError("unable to replace desktop runtime state") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def remove(self, *, expected_token: str | None = None) -> None:
        if expected_token is not None:
            current = self.load()
            if current is None or not secrets.compare_digest(
                current.instance_token.encode("ascii"),
                expected_token.encode("ascii"),
            ):
                return
        try:
            self._retry_sharing_violation(
                lambda: self.path.unlink(missing_ok=True)
            )
        except OSError as exc:
            raise RuntimeStateError("unable to remove desktop runtime state") from exc

    def _retry_sharing_violation(self, operation: Callable[[], Any]) -> Any:
        for attempt in range(self._retry_attempts):
            try:
                return operation()
            except OSError as exc:
                if (
                    getattr(exc, "winerror", None)
                    not in _SHARING_VIOLATION_WINERRORS
                    or attempt + 1 >= self._retry_attempts
                ):
                    raise
                self._sleep(self._retry_delay_seconds)
        raise AssertionError("unreachable sharing retry state")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject every redirect so the runtime bearer token stays on loopback."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl


def _proxyless_opener() -> Any:
    """Build an opener that never uses proxies or follows redirects."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )


def probe_runtime_endpoint(
    state: RuntimeState,
    *,
    timeout_seconds: float = 0.75,
    opener: Any | None = None,
) -> bool:
    """Validate the authenticated loopback desktop endpoint against state."""
    url = f"http://127.0.0.1:{state.port}{RUNTIME_ENDPOINT_PATH}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {state.instance_token}",
        },
    )
    endpoint_opener = opener if opener is not None else _proxyless_opener()
    try:
        with endpoint_opener.open(request, timeout=timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                return False
            raw = response.read(8192).decode("utf-8")
    except (
        OSError,
        TimeoutError,
        UnicodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ):
        return False

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return False
        runtime_payload = dict(payload)
        runtime_payload.pop("status")
        observed = RuntimeState.from_mapping(runtime_payload)
    except (json.JSONDecodeError, ValueError):
        return False
    return observed == state


class InstanceRole(str, Enum):
    OWNER = "owner"
    FOLLOWER = "follower"


@dataclass(frozen=True)
class InstanceDecision:
    """Result of bounded ownership coordination."""

    role: InstanceRole
    port: int | None = None


class DesktopInstance:
    """Coordinate one per-user owner and authenticated follower handoff."""

    def __init__(
        self,
        *,
        store: RuntimeStateStore,
        mutex: MutexHandle,
        inspector: ProcessInspector,
        current_user_id: str,
        env: MutableMapping[str, str],
        current_pid: int | None = None,
        token_factory: Callable[[], str] | None = None,
        endpoint_probe: Callable[[RuntimeState], bool] = probe_runtime_endpoint,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self.store = store
        self._mutex = mutex
        self._inspector = inspector
        self._current_user_id = current_user_id
        self._env = env
        self._current_pid = current_pid if current_pid is not None else os.getpid()
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._endpoint_probe = endpoint_probe
        self._monotonic = monotonic
        self._sleep = sleep
        self._owner = False
        self._closed = False
        self._identity: ProcessIdentity | None = None
        self._state: RuntimeState | None = None

    def coordinate(
        self,
        *,
        wait_seconds: float = MAX_COORDINATION_WAIT_SECONDS,
        poll_seconds: float = 0.1,
    ) -> InstanceDecision:
        """Become owner or return a fully validated existing owner."""
        if self._closed:
            raise DesktopInstanceError("desktop instance coordinator is closed")
        bounded_wait = min(
            max(0.0, wait_seconds),
            MAX_COORDINATION_WAIT_SECONDS,
        )
        deadline = self._monotonic() + bounded_wait
        while True:
            if self._mutex.acquire(0):
                self._become_owner()
                return InstanceDecision(InstanceRole.OWNER)

            state = self.store.load()
            if state is not None and self._is_valid_running_state(state):
                self._mutex.close()
                self._closed = True
                return InstanceDecision(InstanceRole.FOLLOWER, port=state.port)

            now = self._monotonic()
            if now >= deadline:
                self._mutex.close()
                self._closed = True
                raise InstanceUnavailableError(
                    "existing desktop instance did not become ready"
                )
            self._sleep(min(max(0.01, poll_seconds), deadline - now))

    def publish(self, *, port: int, application_version: str) -> RuntimeState:
        """Publish this owner's endpoint contract after final port selection."""
        if not self._owner or self._identity is None or self._closed:
            raise DesktopInstanceError("desktop runtime is not owned")
        state = RuntimeState.create(
            pid=self._identity.pid,
            port=port,
            application_version=application_version,
            process_start_time=self._identity.start_time,
            instance_token=self._token_factory(),
        )
        self._env.update(state.export_environment())
        try:
            self.store.replace(state)
        except BaseException:
            self._clear_environment()
            raise
        self._state = state
        return state

    def validate_published_runtime(self) -> bool:
        """Return whether this owner's published endpoint is exactly ready."""
        return self._state is not None and self._is_valid_running_state(self._state)

    def cleanup(self) -> None:
        """Remove only this owner's state and release ownership resources."""
        if self._closed:
            return
        cleanup_error: BaseException | None = None
        try:
            if self._owner:
                if self._state is not None:
                    try:
                        self.store.remove(
                            expected_token=self._state.instance_token
                        )
                    except Exception as exc:
                        cleanup_error = exc
                self._clear_environment()
        finally:
            try:
                self._mutex.close()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            self._owner = False
            self._closed = True
        if cleanup_error is not None:
            raise cleanup_error

    def _become_owner(self) -> None:
        self._owner = True
        try:
            self.store.remove()
            identity = self._inspector.inspect(self._current_pid)
            if (
                identity is None
                or identity.pid != self._current_pid
                or identity.owner_id != self._current_user_id
                or identity.start_time <= 0
            ):
                raise DesktopInstanceError(
                    "unable to validate desktop owner process"
                )
            self._identity = identity
        except BaseException:
            try:
                self.cleanup()
            except BaseException:  # noqa: S110 - preserve the owner setup failure
                pass
            raise

    def _is_valid_running_state(self, state: RuntimeState) -> bool:
        observed = self._inspector.inspect(state.pid)
        if (
            observed is None
            or observed.pid != state.pid
            or observed.owner_id != self._current_user_id
            or observed.start_time != state.process_start_time
        ):
            return False
        return self._endpoint_probe(state)

    def _clear_environment(self) -> None:
        for name in DESKTOP_RUNTIME_ENV_NAMES:
            self._env.pop(name, None)


def create_desktop_instance(
    runtime_path: Path,
    env: MutableMapping[str, str] | None = None,
) -> DesktopInstance:
    """Create the production Windows ownership coordinator."""
    runtime_env = env if env is not None else os.environ
    inspector = Win32ProcessInspector()
    current_pid = os.getpid()
    try:
        current_user_id = inspector.current_user_sid()
    except OSError:
        current_identity = inspector.inspect(current_pid)
        if (
            current_identity is None
            or current_identity.pid != current_pid
            or not current_identity.owner_id
        ):
            raise DesktopInstanceError(
                "unable to validate current process ownership"
            )
        current_user_id = current_identity.owner_id

    if not current_user_id:
        raise DesktopInstanceError("unable to validate current process ownership")
    mutex = Win32NamedMutex(mutex_name_for_user(current_user_id))
    return DesktopInstance(
        store=RuntimeStateStore(runtime_path),
        mutex=mutex,
        inspector=inspector,
        current_user_id=current_user_id,
        env=runtime_env,
        current_pid=current_pid,
    )
