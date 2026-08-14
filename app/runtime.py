"""Typed, per-application runtime state for DOCSight."""

from __future__ import annotations

import os
import secrets
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeVar

import requests
from flask import Flask, current_app


DOCSIGHT_EXTENSION_KEY = "docsight"
_GITHUB_RELEASE_URL = "https://api.github.com/repos/itsDNNS/docsight/releases/latest"
_T = TypeVar("_T")


def _write_private_file(path: str, value: bytes) -> None:
    """Atomically replace a private state file with mode 0600."""
    data_dir = os.path.dirname(path)
    os.makedirs(data_dir, exist_ok=True)
    temp_path = f"{path}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    fd = None
    try:
        fd = os.open(
            temp_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            directory_fd = os.open(data_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def _version_newer(latest: str, current: str) -> bool:
    """Compare date-based release versions with a numeric build suffix."""
    def parts(value: str) -> tuple[str, int]:
        dot = value.rfind(".")
        if dot == -1:
            return value, 0
        try:
            build = int(value[dot + 1:])
        except ValueError:
            build = 0
        return value[:dot], build

    return parts(latest) > parts(current)


def _fetch_latest_release() -> str:
    response = requests.get(
        _GITHUB_RELEASE_URL,
        headers={"Accept": "application/vnd.github.v3+json"},
        timeout=5,
    )
    if response.status_code != 200:
        return ""
    return str(response.json().get("tag_name", ""))


def _spawn_daemon(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True).start()


class RuntimeState:
    """Lock-protected dashboard state shared with collector threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, object] = {
            "analysis": None,
            "last_update": None,
            "poll_interval": 900,
            "error": None,
            "connection_info": None,
            "device_info": None,
            "speedtest_latest": None,
        }

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return dict(self._values)

    def update(
        self,
        *,
        analysis=None,
        error=None,
        poll_interval=None,
        connection_info=None,
        device_info=None,
        speedtest_latest=None,
        weather_latest=None,
    ) -> None:
        with self._lock:
            if analysis is not None:
                self._values["analysis"] = analysis
                self._values["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._values["error"] = None
            if error is not None:
                self._values["error"] = str(error)
            if poll_interval is not None:
                self._values["poll_interval"] = poll_interval
            if connection_info is not None:
                self._values["connection_info"] = connection_info
            if device_info is not None:
                self._values["device_info"] = device_info
            if speedtest_latest is not None:
                self._values["speedtest_latest"] = speedtest_latest
            if weather_latest is not None:
                self._values["weather_latest"] = weather_latest

    def clear_speedtest_latest(self) -> None:
        with self._lock:
            self._values["speedtest_latest"] = None

    def reset_modem(self) -> None:
        with self._lock:
            self._values.update({
                "analysis": None,
                "last_update": None,
                "error": None,
                "connection_info": None,
                "device_info": None,
            })


class LoginRateLimiter:
    """Bounded, lock-protected login failure buckets for one application."""

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window: float = 900,
        lockout_base: float = 30,
        max_tracked_ips: int = 2048,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window
        self._lockout_base = lockout_base
        self._max_tracked_ips = max_tracked_ips
        self._clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def _prune_locked(self, now: float) -> None:
        for ip, attempts in list(self._attempts.items()):
            current = [stamp for stamp in attempts if now - stamp < self._window]
            if current:
                self._attempts[ip] = current
            else:
                self._attempts.pop(ip, None)
        if len(self._attempts) > self._max_tracked_ips:
            oldest = sorted(
                self._attempts,
                key=lambda ip: self._attempts[ip][-1] if self._attempts[ip] else 0,
            )
            for ip in oldest[:len(self._attempts) - self._max_tracked_ips]:
                self._attempts.pop(ip, None)

    def prune(self, now: float | None = None) -> None:
        with self._lock:
            self._prune_locked(self._clock() if now is None else now)

    def retry_after(self, ip: str) -> float:
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            attempts = self._attempts.get(ip, [])
            if len(attempts) < self._max_attempts:
                return 0
            excess = len(attempts) - self._max_attempts
            lockout = self._lockout_base * (2 ** min(excess, 8))
            return max(0, lockout - (now - attempts[-1]))

    def record_failure(self, ip: str) -> None:
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            self._attempts.setdefault(ip, []).append(now)
            self._prune_locked(now)

    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)

    def snapshot(self) -> dict[str, list[float]]:
        with self._lock:
            return {ip: list(attempts) for ip, attempts in self._attempts.items()}


class UpdateChecker:
    """One application's non-blocking release-check cache."""

    def __init__(
        self,
        *,
        app_version: str,
        is_enabled: Callable[[], bool],
        fetch: Callable[[], str] = _fetch_latest_release,
        clock: Callable[[], float] = time.time,
        spawn: Callable[[Callable[[], None]], None] = _spawn_daemon,
        ttl: float = 3600,
    ) -> None:
        self._app_version = app_version
        self._is_enabled = is_enabled
        self._fetch = fetch
        self._clock = clock
        self._spawn = spawn
        self._ttl = ttl
        self._lock = threading.Lock()
        self._latest: str | None = None
        self._checked_at = 0.0
        self._checking = False

    def latest(self) -> str | None:
        if not self._is_enabled() or self._app_version == "dev":
            return None
        now = self._clock()
        should_start = False
        with self._lock:
            if now - self._checked_at < self._ttl:
                return self._latest
            if not self._checking:
                self._checking = True
                should_start = True
            latest = self._latest
        if should_start:
            self._spawn(self._refresh)
        return latest

    def _refresh(self) -> None:
        try:
            tag = self._fetch()
            current = self._app_version.lstrip("v")
            latest = tag.lstrip("v")
            result = tag if latest and latest != current and _version_newer(latest, current) else None
            with self._lock:
                self._latest = result
        except Exception:
            pass
        finally:
            with self._lock:
                self._checked_at = self._clock()
                self._checking = False

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "latest": self._latest,
                "checked_at": self._checked_at,
                "checking": self._checking,
            }


class AuthStateStore:
    """Persistent signing and authentication state scoped to one data directory."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self.key_path = os.path.join(data_dir, ".session_key")
        self.auth_state_path = os.path.join(data_dir, ".auth_state")

    def load_or_create_session_key(self) -> bytes:
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as handle:
                return handle.read()
        key = os.urandom(32)
        _write_private_file(self.key_path, key)
        return key

    def rotate_session_key(self) -> bytes:
        key = os.urandom(32)
        _write_private_file(self.key_path, key)
        return key

    def read_fingerprint(self) -> str | None:
        try:
            with open(self.auth_state_path, "r", encoding="ascii") as handle:
                value = handle.read().strip()
        except (FileNotFoundError, OSError, UnicodeError):
            return None
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            return None
        return value

    def write_fingerprint(self, value: str) -> None:
        _write_private_file(self.auth_state_path, value.encode("ascii"))


class DerivedStorageCache:
    """Lock-protected cache for objects derived from one application's runtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, Any] = {}

    def get(self, key: str, factory: Callable[[], _T]) -> _T:
        with self._lock:
            if key not in self._values:
                self._values[key] = factory()
            return self._values[key]

    def value(self, key: str, default: _T) -> _T:
        with self._lock:
            return self._values.get(key, default)

    def set_value(self, key: str, value: Any) -> None:
        with self._lock:
            self._values[key] = value


@dataclass(repr=False)
class DocsightRuntime:
    """All mutable runtime collaborators belonging to one Flask application."""

    config_manager: Any = field(repr=False)
    auth_state: AuthStateStore = field(repr=False)
    update_checker: UpdateChecker = field(repr=False)
    storage: Any | None = field(default=None, repr=False)
    on_config_changed: Callable[[], None] | None = field(default=None, repr=False)
    state: RuntimeState = field(default_factory=RuntimeState, repr=False)
    login_rate_limiter: LoginRateLimiter = field(default_factory=LoginRateLimiter, repr=False)
    derived_storage: DerivedStorageCache = field(default_factory=DerivedStorageCache, repr=False)
    module_loader: Any | None = field(default=None, repr=False)
    modem_collector: Any | None = field(default=None, repr=False)
    collectors: list[Any] = field(default_factory=list, repr=False)
    last_manual_poll: float = field(default=0.0, repr=False)
    _last_manual_poll_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def __repr__(self) -> str:
        return "DocsightRuntime(<redacted>)"

    def update_state(self, **fields: Any) -> None:
        self.state.update(**fields)

    def clear_speedtest_latest(self) -> None:
        self.state.clear_speedtest_latest()

    def reset_modem_state(self) -> None:
        self.state.reset_modem()

    def get_state(self) -> dict[str, object]:
        return self.state.snapshot()

    def get_module_loader(self):
        return self.module_loader

    def get_last_manual_poll(self) -> float:
        with self._last_manual_poll_lock:
            return self.last_manual_poll

    def set_last_manual_poll(self, value: float) -> None:
        with self._last_manual_poll_lock:
            self.last_manual_poll = value

    @property
    def _state(self) -> Mapping[str, object]:
        """Read-only snapshot retained for collector duck-type compatibility."""
        return MappingProxyType(self.get_state())


def attach_runtime(app: Flask, runtime: DocsightRuntime) -> None:
    if DOCSIGHT_EXTENSION_KEY in app.extensions:
        raise RuntimeError("DOCSight runtime is already attached")
    app.extensions[DOCSIGHT_EXTENSION_KEY] = runtime


def get_runtime(app: Flask) -> DocsightRuntime:
    try:
        runtime = app.extensions[DOCSIGHT_EXTENSION_KEY]
    except KeyError as exc:
        raise RuntimeError("DOCSight runtime is not attached") from exc
    if not isinstance(runtime, DocsightRuntime):
        raise TypeError("DOCSight extension has an invalid runtime")
    return runtime


def current_runtime() -> DocsightRuntime:
    return get_runtime(current_app._get_current_object())
