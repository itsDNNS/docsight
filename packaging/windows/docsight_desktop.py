"""Native startup and recovery launcher for DOCSight on Windows.

Windows-specific behavior stays in ``packaging/windows`` so the core web
application remains platform-neutral. The launcher paints a small Tk window,
then prepares per-user paths, selects a loopback port, starts the application,
and opens the user's browser from a worker thread.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, replace
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, MutableMapping

WINDOWS_PACKAGING_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]
for import_root in (SOURCE_ROOT, WINDOWS_PACKAGING_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.desktop_runtime_contract import (  # noqa: E402
    DESKTOP_MODE_ENV,
    WEB_PORT_ENV,
)
from desktop_instance import (  # noqa: E402
    DesktopInstance,
    DesktopInstanceError,
    InstanceRole,
    InstanceUnavailableError,
    create_desktop_instance,
)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_PORT = 8775
HEALTH_TIMEOUT_SECONDS = 30
EVENT_POLL_MILLISECONDS = 75
RELAUNCH_HANDLE_OPTION = "--docsight-relaunch-handle="
BIND_RETRY_ENV = "DOCSIGHT_DESKTOP_BIND_RETRY"

LOG = logging.getLogger("docsight.desktop")


class StartupPhase(str, Enum):
    PREPARE = "Prepare local data"
    START = "Start DOCSight"
    WAIT = "Wait for readiness"
    OPEN = "Open browser"


PHASES = tuple(StartupPhase)


class EventKind(str, Enum):
    PHASE = "phase"
    READY = "ready"
    ERROR = "error"
    EXIT = "exit"


class RecoveryCode(str, Enum):
    NO_PORT = "no_free_port"
    TIMEOUT = "readiness_timeout"
    APP_FAILED = "app_thread_failure"
    BROWSER_FAILED = "browser_open_failure"
    STARTUP_FAILED = "startup_failure"
    RELAUNCH_FAILED = "relaunch_failure"
    HANDOFF_FAILED = "relaunch_handoff_failure"


RECOVERY_MESSAGES = {
    RecoveryCode.NO_PORT: "DOCSight could not find an available local port.",
    RecoveryCode.TIMEOUT: "DOCSight took too long to become ready.",
    RecoveryCode.APP_FAILED: "DOCSight stopped unexpectedly during startup.",
    RecoveryCode.BROWSER_FAILED: (
        "DOCSight is ready, but the browser could not be opened. "
        "Use the local address below."
    ),
    RecoveryCode.STARTUP_FAILED: "DOCSight could not finish starting.",
    RecoveryCode.RELAUNCH_FAILED: (
        "DOCSight could not restart. Close it and start DOCSight again."
    ),
    RecoveryCode.HANDOFF_FAILED: (
        "DOCSight could not safely finish restarting. "
        "Close it and start DOCSight again."
    ),
}

PHASE_MESSAGES = {
    StartupPhase.PREPARE: "Preparing your local DOCSight data…",
    StartupPhase.START: "Starting DOCSight on this PC…",
    StartupPhase.WAIT: "Waiting for the local web app to become ready…",
    StartupPhase.OPEN: "DOCSight is ready. Opening your browser…",
}


@dataclass(frozen=True)
class DesktopPaths:
    """Per-user paths used by the desktop preview launcher."""

    base_dir: Path
    data_dir: Path
    modules_dir: Path
    logs_dir: Path
    log_file: Path
    runtime_log_file: Path
    runtime_file: Path


@dataclass(frozen=True)
class PortSelection:
    """Selected free local web port for a new owner."""

    port: int


@dataclass(frozen=True)
class LauncherEvent:
    """Worker-to-UI event. The attempt prevents stale worker updates."""

    attempt: int
    kind: EventKind
    phase: StartupPhase | None = None
    url: str | None = None
    recovery: RecoveryCode | None = None
    owns_server: bool = False
    safe_exception_type: str | None = None


@dataclass(frozen=True)
class LauncherState:
    """Display-independent state rendered by the Tk view."""

    attempt: int
    phase: StartupPhase
    url: str
    status: str
    ready: bool = False
    recovery: RecoveryCode | None = None
    owns_server: bool = False
    closed: bool = False


@dataclass
class AppThreadHandle:
    """Application thread completion state without retaining an exception."""

    thread: threading.Thread | None
    stopped: threading.Event
    failure_type: str | None = None


class WaitOutcome(str, Enum):
    READY = "ready"
    TIMEOUT = "timeout"
    APP_FAILED = "app_failed"


class HandoffOutcome(str, Enum):
    COMPLETE = "complete"
    TIMEOUT = "timeout"
    FAILED = "failed"


class LauncherController:
    """Queue-backed launcher state machine with no dependency on Tk."""

    def __init__(self, initial_url: str) -> None:
        self.events: queue.Queue[LauncherEvent] = queue.Queue()
        self.state = LauncherState(
            attempt=0,
            phase=StartupPhase.PREPARE,
            url=initial_url,
            status=PHASE_MESSAGES[StartupPhase.PREPARE],
        )
        self.exit_code = 0

    def begin_attempt(self) -> int:
        attempt = self.state.attempt + 1
        self.state = LauncherState(
            attempt=attempt,
            phase=StartupPhase.PREPARE,
            url=self.state.url,
            status=PHASE_MESSAGES[StartupPhase.PREPARE],
        )
        return attempt

    def emit(self, event: LauncherEvent) -> None:
        """Publish from a worker; this method never touches Tk."""
        self.events.put(event)

    def drain_events(self) -> bool:
        """Apply queued events on the UI thread and report whether state changed."""
        changed = False
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return changed
            if event.attempt != self.state.attempt:
                continue
            self._apply(event)
            changed = True

    def _apply(self, event: LauncherEvent) -> None:
        url = event.url or self.state.url
        if event.kind is EventKind.PHASE and event.phase is not None:
            self.state = replace(
                self.state,
                phase=event.phase,
                url=url,
                status=PHASE_MESSAGES[event.phase],
            )
        elif event.kind is EventKind.READY:
            self.state = replace(
                self.state,
                phase=StartupPhase.OPEN,
                url=url,
                status="DOCSight is ready.",
                ready=True,
                owns_server=event.owns_server,
            )
        elif event.kind is EventKind.ERROR and event.recovery is not None:
            self.exit_code = 1
            self.state = replace(
                self.state,
                url=event.url,
                status=RECOVERY_MESSAGES[event.recovery],
                ready=event.recovery is RecoveryCode.BROWSER_FAILED,
                recovery=event.recovery,
            )
        elif event.kind is EventKind.EXIT:
            self.state = replace(self.state, closed=True)


def _local_app_data(env: MutableMapping[str, str], home: Path | None = None) -> Path:
    """Return the Windows LocalAppData root, with a deterministic fallback."""
    configured = env.get("LOCALAPPDATA")
    if configured:
        return Path(configured)
    home_dir = home or Path.home()
    return home_dir / "AppData" / "Local"


def resolve_desktop_paths(
    env: MutableMapping[str, str] | None = None,
    home: Path | None = None,
) -> DesktopPaths:
    """Resolve the per-user DOCSight desktop runtime paths."""
    runtime_env = env if env is not None else os.environ
    base_dir = _local_app_data(runtime_env, home=home) / "DOCSight"
    logs_dir = base_dir / "logs"
    return DesktopPaths(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        modules_dir=base_dir / "modules",
        logs_dir=logs_dir,
        log_file=logs_dir / "launcher.log",
        runtime_log_file=logs_dir / "runtime.log",
        runtime_file=base_dir / "runtime.json",
    )


def configure_desktop_environment(
    env: MutableMapping[str, str] | None = None,
    home: Path | None = None,
) -> DesktopPaths:
    """Create desktop runtime directories and export the app env contract."""
    runtime_env = env if env is not None else os.environ
    paths = resolve_desktop_paths(runtime_env, home=home)
    for directory in (paths.base_dir, paths.data_dir, paths.modules_dir, paths.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    runtime_env["DATA_DIR"] = str(paths.data_dir)
    runtime_env["MODULES_DIR"] = str(paths.modules_dir)
    runtime_env["WEB_HOST"] = DEFAULT_HOST
    runtime_env[DESKTOP_MODE_ENV] = "1"
    return paths


class _LauncherLogFilter(logging.Filter):
    """Keep traceback-bearing records out of the shareable launcher log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


_LOGGING_LOCK = threading.Lock()
_LOGGING_SIGNATURE: tuple[Path, Path] | None = None
_OWNED_HANDLER_ATTRIBUTE = "_docsight_desktop_handler"


def _remove_owned_handlers(logger: logging.Logger) -> None:
    """Close only handlers installed by this launcher."""
    for existing_handler in tuple(logger.handlers):
        if not getattr(existing_handler, _OWNED_HANDLER_ATTRIBUTE, False):
            continue
        logger.removeHandler(existing_handler)
        existing_handler.close()


def configure_logging(
    log_file: Path,
    runtime_log_file: Path | None = None,
) -> None:
    """Configure private launcher and root application diagnostics once."""
    global _LOGGING_SIGNATURE

    runtime_file = runtime_log_file or log_file.with_name("runtime.log")
    signature = (log_file.resolve(), runtime_file.resolve())
    with _LOGGING_LOCK:
        root_logger = logging.getLogger()
        if (
            _LOGGING_SIGNATURE == signature
            and any(
                getattr(handler, _OWNED_HANDLER_ATTRIBUTE, False)
                for handler in LOG.handlers
            )
            and any(
                getattr(handler, _OWNED_HANDLER_ATTRIBUTE, False)
                for handler in root_logger.handlers
            )
        ):
            return

        _remove_owned_handlers(LOG)
        _remove_owned_handlers(root_logger)

        log_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

        launcher_handler = RotatingFileHandler(
            log_file,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        setattr(launcher_handler, _OWNED_HANDLER_ATTRIBUTE, True)
        launcher_handler.addFilter(_LauncherLogFilter())
        launcher_handler.setFormatter(formatter)
        LOG.addHandler(launcher_handler)

        runtime_handler = RotatingFileHandler(
            runtime_file,
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        setattr(runtime_handler, _OWNED_HANDLER_ATTRIBUTE, True)
        runtime_handler.setFormatter(formatter)
        root_logger.addHandler(runtime_handler)

        level = getattr(
            logging,
            os.environ.get("LOG_LEVEL", "INFO").upper(),
            logging.INFO,
        )
        LOG.setLevel(level)
        root_logger.setLevel(level)
        LOG.propagate = False
        _LOGGING_SIGNATURE = signature


def local_url(port: int) -> str:
    return f"http://{DEFAULT_HOST}:{port}/"


def _can_bind_local_port(
    port: int,
    *,
    platform: str | None = None,
    socket_factory: Callable[..., Any] = socket.socket,
) -> bool:
    """Return whether loopback port can be bound by a new DOCSight instance."""
    current_platform = platform or sys.platform
    with socket_factory(socket.AF_INET, socket.SOCK_STREAM) as sock:
        option = (
            getattr(socket, "SO_EXCLUSIVEADDRUSE", -5)
            if current_platform == "win32"
            else socket.SO_REUSEADDR
        )
        sock.setsockopt(socket.SOL_SOCKET, option, 1)
        try:
            sock.bind((DEFAULT_HOST, port))
        except OSError:
            return False
    return True


def _preferred_port(env: MutableMapping[str, str]) -> int:
    raw = env.get(WEB_PORT_ENV, str(DEFAULT_PORT))
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def select_port(
    env: MutableMapping[str, str] | None = None,
    *,
    max_port: int = MAX_PORT,
) -> PortSelection:
    """Select a free loopback port for the mutex-owning desktop instance."""
    runtime_env = env if env is not None else os.environ
    preferred = _preferred_port(runtime_env)

    candidates = [preferred]
    candidates.extend(
        port
        for port in range(DEFAULT_PORT, max_port + 1)
        if port != preferred
    )

    seen: set[int] = set()
    for port in candidates:
        if port in seen:
            continue
        seen.add(port)
        if _can_bind_local_port(port):
            runtime_env[WEB_PORT_ENV] = str(port)
            return PortSelection(port=port)

    raise RuntimeError("No free loopback port")


def get_runtime_root() -> Path:
    """Return the root that contains bundled app data or the source checkout."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return SOURCE_ROOT


def _ensure_repo_on_path() -> None:
    runtime_root = str(get_runtime_root())
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)


def _safe_exception_type(exc: BaseException) -> str:
    """Return a bounded class name suitable for logs and worker events."""
    name = type(exc).__name__
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)[:80]
    return cleaned or "Exception"


def _start_app_thread(*, inject_smoke_failure: bool = False) -> AppThreadHandle:
    """Start the application behind a BaseException-safe completion handle."""
    stopped = threading.Event()
    handle = AppThreadHandle(thread=None, stopped=stopped)

    def run_app() -> None:
        try:
            if inject_smoke_failure:
                raise RuntimeError("injected startup failure")
            _ensure_repo_on_path()
            from app.main import main as app_main

            app_main()
        except BaseException as exc:
            handle.failure_type = _safe_exception_type(exc)
        finally:
            stopped.set()

    thread = threading.Thread(target=run_app, name="docsight-app", daemon=True)
    handle.thread = thread
    thread.start()
    return handle


def _wait_for_ready(
    port: int,
    app_handle: AppThreadHandle | None,
    timeout_seconds: float = HEALTH_TIMEOUT_SECONDS,
    *,
    readiness_probe: Callable[[], bool],
) -> WaitOutcome:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if app_handle is not None and app_handle.stopped.is_set():
            return WaitOutcome.APP_FAILED
        if readiness_probe():
            return WaitOutcome.READY
        time.sleep(0.5)
    if app_handle is not None and app_handle.stopped.is_set():
        return WaitOutcome.APP_FAILED
    return WaitOutcome.TIMEOUT


def open_browser(
    port: int,
    env: MutableMapping[str, str] | None = None,
    browser_open: Callable[[str], object] | None = None,
    *,
    platform: str | None = None,
    com_api: object | None = None,
) -> bool:
    """Attempt to open the local URL; browser skipping is a successful no-op."""
    runtime_env = env if env is not None else os.environ
    if runtime_env.get("DOCSIGHT_SKIP_BROWSER") == "1":
        LOG.info("Skipping browser launch because DOCSIGHT_SKIP_BROWSER=1")
        return True
    if browser_open is not None or (platform or sys.platform) != "win32":
        opener = browser_open or webbrowser.open
        return bool(opener(local_url(port)))

    api: Any = com_api
    if api is None:
        import ctypes

        api = getattr(ctypes, "windll").ole32
        api.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        api.CoInitializeEx.restype = ctypes.c_long
        api.CoUninitialize.argtypes = ()
        api.CoUninitialize.restype = None

    result = int(api.CoInitializeEx(None, 0x2))
    initialized = result in (0, 1)  # S_OK or S_FALSE.
    changed_mode = result in (-2147417850, 0x80010106)
    if not initialized and not changed_mode:
        raise OSError("COM apartment initialization failed")
    try:
        return bool(webbrowser.open(local_url(port)))
    finally:
        if initialized:
            api.CoUninitialize()


def copy_local_url(clipboard: object, url: str) -> None:
    """Copy a local URL using the small clipboard contract exposed by Tk."""
    clipboard.clipboard_clear()
    clipboard.clipboard_append(url)


def centered_window_geometry(
    requested_width: int,
    requested_height: int,
    screen_width: int,
    screen_height: int,
    *,
    minimum_width: int = 480,
    minimum_height: int = 300,
) -> str:
    """Return a DPI-safe centered geometry string for the launcher window."""
    width = max(minimum_width, requested_width)
    height = max(minimum_height, requested_height)
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 3)
    return f"{width}x{height}+{x}+{y}"


def open_log_folder(
    logs_dir: Path,
    *,
    platform: str | None = None,
    windows_open: Callable[[str], object] | None = None,
    process_open: Callable[..., object] | None = None,
) -> bool:
    """Open the log directory with the platform shell, using Explorer on Windows."""
    current_platform = platform or sys.platform
    if current_platform == "win32":
        opener = windows_open or getattr(os, "startfile")
        opener(str(logs_dir))
        return True

    command = ["open" if current_platform == "darwin" else "xdg-open", str(logs_dir)]
    launcher = process_open or subprocess.Popen
    launcher(command)
    return True


def launcher_command(parent_handle: int | None = None) -> list[str]:
    """Return the command used to start a fresh launcher attempt."""
    if getattr(sys, "frozen", False):
        command = [sys.executable]
    else:
        command = [sys.executable, str(Path(__file__).resolve())]
    if parent_handle is not None:
        command.append(f"{RELAUNCH_HANDLE_OPTION}{parent_handle}")
    return command


def launcher_working_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


def _windows_process_api() -> object:
    import ctypes
    from ctypes import wintypes

    api = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    api.GetCurrentProcess.argtypes = ()
    api.GetCurrentProcess.restype = wintypes.HANDLE
    api.DuplicateHandle.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    api.DuplicateHandle.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    return api


def duplicate_current_process_handle(windows_api: object | None = None) -> int:
    """Create an inheritable real handle identifying this launcher process."""
    import ctypes
    from ctypes import wintypes

    api: Any = windows_api or _windows_process_api()
    current_process = api.GetCurrentProcess()
    duplicated = wintypes.HANDLE()
    succeeded = api.DuplicateHandle(
        current_process,
        current_process,
        current_process,
        ctypes.byref(duplicated),
        0x00100000,  # SYNCHRONIZE
        True,
        0,
    )
    if not succeeded or not duplicated.value:
        raise OSError("Unable to create launcher handoff handle")
    return int(duplicated.value)


def close_windows_handle(
    handle: int,
    windows_api: object | None = None,
) -> None:
    api: Any = windows_api or _windows_process_api()
    api.CloseHandle(handle)


def spawn_launcher_process(
    command: list[str] | None = None,
    process_factory: Callable[..., object] | None = None,
    *,
    platform: str | None = None,
    duplicate_handle: Callable[[], int] = duplicate_current_process_handle,
    close_handle: Callable[[int], object] = close_windows_handle,
    startupinfo_factory: Callable[[], object] | None = None,
) -> object:
    """Spawn a fresh launcher process without waiting for it."""
    launcher = process_factory or subprocess.Popen
    if command is not None or (platform or sys.platform) != "win32":
        return launcher(
            command or launcher_command(),
            cwd=str(launcher_working_directory()),
            close_fds=True,
        )

    parent_handle = duplicate_handle()
    try:
        startupinfo = (
            startupinfo_factory()
            if startupinfo_factory is not None
            else subprocess.STARTUPINFO()
        )
        startupinfo.lpAttributeList = {"handle_list": [parent_handle]}
        return launcher(
            launcher_command(parent_handle=parent_handle),
            cwd=str(launcher_working_directory()),
            close_fds=True,
            startupinfo=startupinfo,
        )
    finally:
        close_handle(parent_handle)


def terminate_current_launcher(exit_function: Callable[[int], object] | None = None) -> None:
    """Terminate this process so its daemon application thread cannot survive."""
    terminator = exit_function or os._exit
    terminator(0)


def relaunch_launcher(
    *,
    spawn: Callable[[], object] = spawn_launcher_process,
    cleanup: Callable[[], object] | None = None,
    terminate: Callable[[], object] = terminate_current_launcher,
) -> None:
    """Start a normal fresh launcher attempt, then terminate this launcher."""
    spawn()
    cleanup_error: BaseException | None = None
    if cleanup is not None:
        try:
            cleanup()
        except BaseException as exc:
            cleanup_error = exc
            LOG.error(
                "Runtime cleanup failed during relaunch (failure type: %s)",
                _safe_exception_type(exc),
            )
    terminate()
    if cleanup_error is not None:
        raise cleanup_error


def _relaunch_parent_handle(argv: list[str] | None = None) -> int | None:
    """Read the inherited parent identity handle emitted by the retry helper."""
    for argument in argv if argv is not None else sys.argv[1:]:
        if not argument.startswith(RELAUNCH_HANDLE_OPTION):
            continue
        raw_handle = argument.removeprefix(RELAUNCH_HANDLE_OPTION)
        if raw_handle.isdecimal() and int(raw_handle) > 0:
            return int(raw_handle)
    return None


def wait_for_previous_launcher(
    parent_handle: int,
    *,
    timeout_milliseconds: int = 10_000,
    windows_api: object | None = None,
) -> HandoffOutcome:
    """Wait on the inherited parent identity handle and always close it."""
    if sys.platform != "win32" and windows_api is None:
        return HandoffOutcome.COMPLETE

    api: Any = windows_api or _windows_process_api()
    try:
        result = int(api.WaitForSingleObject(parent_handle, timeout_milliseconds))
        if result == 0:
            return HandoffOutcome.COMPLETE
        if result == 0x102:
            return HandoffOutcome.TIMEOUT
        return HandoffOutcome.FAILED
    finally:
        api.CloseHandle(parent_handle)


def _phase_event(attempt: int, phase: StartupPhase, url: str) -> LauncherEvent:
    return LauncherEvent(attempt=attempt, kind=EventKind.PHASE, phase=phase, url=url)


class StartupRunner:
    """Perform slow startup work and communicate only through queued events."""

    def __init__(
        self,
        controller: LauncherController,
        paths: DesktopPaths,
        env: MutableMapping[str, str] | None = None,
        *,
        desktop_instance: DesktopInstance,
        is_relaunch: bool = False,
        handoff_outcome: HandoffOutcome = HandoffOutcome.COMPLETE,
    ) -> None:
        self.controller = controller
        self.paths = paths
        self.desktop_instance = desktop_instance
        self.env = env if env is not None else os.environ
        self.is_relaunch = is_relaunch
        self.handoff_outcome = handoff_outcome

    def _emit_error(
        self,
        attempt: int,
        recovery: RecoveryCode,
        url: str,
        failure_type: str,
    ) -> None:
        LOG.error(
            "Recovery available: %s (failure type: %s)",
            recovery.value,
            failure_type,
        )
        self.controller.emit(
            LauncherEvent(
                attempt=attempt,
                kind=EventKind.ERROR,
                url=url,
                recovery=recovery,
                safe_exception_type=failure_type,
            )
        )

    def run(self, attempt: int) -> None:
        url = self.controller.state.url
        try:
            LOG.info("Phase: %s", StartupPhase.PREPARE.value)

            if self.handoff_outcome is not HandoffOutcome.COMPLETE:
                self._emit_error(
                    attempt,
                    RecoveryCode.HANDOFF_FAILED,
                    url,
                    (
                        "PreviousLauncherExitTimeout"
                        if self.handoff_outcome is HandoffOutcome.TIMEOUT
                        else "PreviousLauncherHandleWaitFailed"
                    ),
                )
                return

            try:
                instance_decision = self.desktop_instance.coordinate()
            except InstanceUnavailableError as exc:
                self._emit_error(
                    attempt,
                    RecoveryCode.TIMEOUT,
                    "",
                    _safe_exception_type(exc),
                )
                return
            except DesktopInstanceError as exc:
                self._emit_error(
                    attempt,
                    RecoveryCode.STARTUP_FAILED,
                    "",
                    _safe_exception_type(exc),
                )
                return

            smoke_enabled = (
                self.env.get("DOCSIGHT_SKIP_BROWSER") == "1"
                and not self.is_relaunch
            )
            if (
                smoke_enabled
                and self.env.get("DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE") == "1"
            ):
                self._emit_error(
                    attempt,
                    RecoveryCode.NO_PORT,
                    "",
                    "InjectedNoFreePort",
                )
                return

            if instance_decision.role is InstanceRole.FOLLOWER:
                assert instance_decision.port is not None
                selection = PortSelection(instance_decision.port)
                owns_server = False
            else:
                owns_server = True
                try:
                    selection = select_port(self.env)
                except RuntimeError as exc:
                    self._emit_error(
                        attempt,
                        RecoveryCode.NO_PORT,
                        "",
                        _safe_exception_type(exc),
                    )
                    return
                try:
                    _ensure_repo_on_path()
                    from app.version import get_app_version

                    self.desktop_instance.publish(
                        port=selection.port,
                        application_version=get_app_version(),
                    )
                except BaseException as exc:
                    self._emit_error(
                        attempt,
                        RecoveryCode.STARTUP_FAILED,
                        url,
                        _safe_exception_type(exc),
                    )
                    return

            url = local_url(selection.port)
            self.controller.emit(_phase_event(attempt, StartupPhase.START, url))
            LOG.info("Phase: %s", StartupPhase.START.value)

            app_handle: AppThreadHandle | None = None
            if not owns_server:
                LOG.info("Validated existing DOCSight desktop instance on %s", url)
            else:
                LOG.info("Starting DOCSight on %s", url)
                inject_smoke_failure = (
                    smoke_enabled
                    and self.env.get("DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE") == "1"
                )
                app_handle = (
                    _start_app_thread(inject_smoke_failure=True)
                    if inject_smoke_failure
                    else _start_app_thread()
                )

            self.controller.emit(_phase_event(attempt, StartupPhase.WAIT, url))
            LOG.info("Phase: %s", StartupPhase.WAIT.value)
            outcome = (
                WaitOutcome.READY
                if not owns_server
                else _wait_for_ready(
                    selection.port,
                    app_handle,
                    readiness_probe=self.desktop_instance.validate_published_runtime,
                )
            )
            if outcome is WaitOutcome.APP_FAILED:
                if (
                    owns_server
                    and app_handle is not None
                    and app_handle.failure_type is None
                    and self.env.get(BIND_RETRY_ENV) != "1"
                    and not _can_bind_local_port(selection.port)
                ):
                    LOG.warning(
                        "Selected loopback port was lost before readiness; "
                        "starting one fresh launcher attempt"
                    )
                    self.env[BIND_RETRY_ENV] = "1"
                    try:
                        relaunch_launcher(cleanup=self.desktop_instance.cleanup)
                    except BaseException as exc:
                        self.env.pop(BIND_RETRY_ENV, None)
                        self._emit_error(
                            attempt,
                            RecoveryCode.RELAUNCH_FAILED,
                            url,
                            _safe_exception_type(exc),
                        )
                    return
                failure_type = (
                    app_handle.failure_type
                    if app_handle is not None and app_handle.failure_type
                    else "ApplicationThreadStopped"
                )
                self._emit_error(
                    attempt,
                    RecoveryCode.APP_FAILED,
                    url,
                    failure_type,
                )
                return
            if outcome is WaitOutcome.TIMEOUT:
                self._emit_error(
                    attempt,
                    RecoveryCode.TIMEOUT,
                    url,
                    "ReadinessTimeout",
                )
                return

            self.controller.emit(_phase_event(attempt, StartupPhase.OPEN, url))
            LOG.info("Phase: %s", StartupPhase.OPEN.value)
            LOG.info("DOCSight is ready on %s", url)
            self.env.pop(BIND_RETRY_ENV, None)
            if (
                smoke_enabled
                and self.env.get("DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE") == "1"
            ):
                self._emit_error(
                    attempt,
                    RecoveryCode.BROWSER_FAILED,
                    url,
                    "InjectedBrowserOpenFailure",
                )
                return
            try:
                browser_opened = open_browser(selection.port, self.env)
            except BaseException as exc:
                self._emit_error(
                    attempt,
                    RecoveryCode.BROWSER_FAILED,
                    url,
                    _safe_exception_type(exc),
                )
                return
            if not browser_opened:
                self._emit_error(
                    attempt,
                    RecoveryCode.BROWSER_FAILED,
                    url,
                    "BrowserOpenReturnedFalse",
                )
                return

            self.controller.emit(
                LauncherEvent(
                    attempt=attempt,
                    kind=EventKind.READY,
                    url=url,
                    owns_server=owns_server,
                )
            )

            if app_handle is None:
                self.controller.emit(LauncherEvent(attempt, EventKind.EXIT))
                return

            assert app_handle.thread is not None
            app_handle.thread.join()
            if app_handle.failure_type:
                self._emit_error(
                    attempt,
                    RecoveryCode.APP_FAILED,
                    url,
                    app_handle.failure_type,
                )
            else:
                self.controller.emit(LauncherEvent(attempt, EventKind.EXIT))
        except BaseException as exc:
            failure_type = _safe_exception_type(exc)
            if LOG.handlers:
                self._emit_error(
                    attempt,
                    RecoveryCode.STARTUP_FAILED,
                    url,
                    failure_type,
                )
            else:
                self.controller.emit(
                    LauncherEvent(
                        attempt=attempt,
                        kind=EventKind.ERROR,
                        url=url,
                        recovery=RecoveryCode.STARTUP_FAILED,
                        safe_exception_type=failure_type,
                    )
                )


class TkLauncher:
    """Compact native view. All methods are called from the Tk main thread."""

    def __init__(
        self,
        root: Any,
        tk_module: Any,
        ttk_module: Any,
        controller: LauncherController,
        runner: StartupRunner,
        paths: DesktopPaths,
        desktop_instance: DesktopInstance,
    ) -> None:
        self.root = root
        self.tk = tk_module
        self.ttk = ttk_module
        self.controller = controller
        self.runner = runner
        self.paths = paths
        self.desktop_instance = desktop_instance
        self._worker: threading.Thread | None = None
        self.root.report_callback_exception = self._report_callback_exception
        self._build()

    def _build(self) -> None:
        self.root.title("DOCSight")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        outer = self.ttk.Frame(self.root, padding=(24, 20, 24, 18))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)

        heading = self.ttk.Label(
            outer,
            text="DOCSight",
            foreground="#1769AA",
            font=("Segoe UI", 17, "bold"),
        )
        heading.grid(row=0, column=0, sticky="w")

        self.status_var = self.tk.StringVar()
        self.status_label = self.ttk.Label(
            outer,
            textvariable=self.status_var,
            wraplength=420,
            justify="left",
        )
        self.status_label.grid(row=1, column=0, sticky="ew", pady=(7, 14))

        self.phase_labels: list[Any] = []
        phase_frame = self.ttk.Frame(outer)
        phase_frame.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        for row, phase in enumerate(PHASES):
            label = self.ttk.Label(phase_frame, text=phase.value)
            label.grid(row=row, column=0, sticky="w", pady=1)
            self.phase_labels.append(label)

        url_caption = self.ttk.Label(outer, text="Local address")
        url_caption.grid(row=3, column=0, sticky="w")
        url_row = self.ttk.Frame(outer)
        url_row.grid(row=4, column=0, sticky="ew", pady=(4, 12))
        url_row.columnconfigure(0, weight=1)
        self.url_var = self.tk.StringVar()
        self.url_entry = self.ttk.Entry(
            url_row,
            textvariable=self.url_var,
            state="readonly",
            width=47,
        )
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.copy_button = self.ttk.Button(
            url_row,
            text="Copy",
            width=8,
            command=self._copy_url,
        )
        self.copy_button.grid(row=0, column=1, padx=(8, 0))

        self.actions = self.ttk.Frame(outer)
        self.retry_button = self.ttk.Button(
            self.actions,
            text="Retry",
            command=self._retry,
        )
        self.retry_button.grid(row=0, column=0)
        self.log_button = self.ttk.Button(
            self.actions,
            text="Open log folder",
            command=self._open_logs,
        )
        self.log_button.grid(row=0, column=1, padx=8)
        self.close_button = self.ttk.Button(
            self.actions,
            text="Close",
            command=self._close,
        )
        self.close_button.grid(row=0, column=2)

        self.render()
        self.root.update_idletasks()
        self.root.geometry(
            centered_window_geometry(
                self.root.winfo_reqwidth(),
                self.root.winfo_reqheight(),
                self.root.winfo_screenwidth(),
                self.root.winfo_screenheight(),
            )
        )

    def start(self) -> None:
        attempt = self.controller.begin_attempt()
        self.render()
        self._worker = threading.Thread(
            target=self.runner.run,
            args=(attempt,),
            name="docsight-startup",
            daemon=True,
        )
        self._worker.start()

    def poll(self) -> None:
        try:
            if self.controller.drain_events():
                self.render()
            state = self.controller.state
            if state.closed:
                self.root.destroy()
                return
        except BaseException as exc:
            self._recover_ui_exception(exc)
        try:
            self.root.after(EVENT_POLL_MILLISECONDS, self.poll)
        except BaseException as exc:
            self._recover_ui_exception(exc)

    def render(self) -> None:
        """Render state, retaining a minimal recovery surface on widget failure."""
        try:
            self._render_full()
        except BaseException as exc:
            self._recover_ui_exception(exc)

    def _render_full(self) -> None:
        state = self.controller.state
        self.status_var.set(state.status)
        self.url_var.set(state.url or "Not available")
        self.copy_button.configure(state="normal" if state.url else "disabled")
        current_index = PHASES.index(state.phase)
        for index, label in enumerate(self.phase_labels):
            if state.ready or index < current_index:
                marker = "✓"
            elif index == current_index:
                marker = "!" if state.recovery is not None else "→"
            else:
                marker = "·"
            label.configure(text=f"{marker}  {PHASES[index].value}")
        if state.recovery is not None:
            self.actions.grid(row=5, column=0, sticky="w")
            self.root.deiconify()
            self.root.update_idletasks()
            self.root.geometry(
                centered_window_geometry(
                    self.root.winfo_reqwidth(),
                    self.root.winfo_reqheight(),
                    self.root.winfo_screenwidth(),
                    self.root.winfo_screenheight(),
                    minimum_height=330,
                )
            )
        else:
            self.actions.grid_remove()
        if state.ready and state.recovery is None and state.owns_server:
            self.root.withdraw()

    def _report_callback_exception(
        self,
        exception_type: type[BaseException],
        _exception: BaseException,
        _traceback: object,
    ) -> None:
        """Sanitize exceptions escaping Tk callbacks."""
        name = re.sub(r"[^A-Za-z0-9_]", "_", exception_type.__name__)[:80]
        self._recover_ui_failure_type(name or "Exception")

    def _recover_ui_exception(self, exc: BaseException) -> None:
        self._recover_ui_failure_type(_safe_exception_type(exc))

    def _recover_ui_failure_type(self, failure_type: str) -> None:
        LOG.error(
            "Recovery available: %s (failure type: %s)",
            RecoveryCode.STARTUP_FAILED.value,
            failure_type,
        )
        self.controller.exit_code = 1
        self.controller.state = replace(
            self.controller.state,
            status=RECOVERY_MESSAGES[RecoveryCode.STARTUP_FAILED],
            ready=False,
            recovery=RecoveryCode.STARTUP_FAILED,
        )
        self._render_minimal_recovery()

    def _render_minimal_recovery(self) -> None:
        """Best-effort fallback that does not recurse through full rendering."""
        operations = (
            lambda: self.status_var.set(
                RECOVERY_MESSAGES[RecoveryCode.STARTUP_FAILED]
            ),
            lambda: self.url_var.set(self.controller.state.url or "Not available"),
            lambda: self.copy_button.configure(
                state="normal" if self.controller.state.url else "disabled"
            ),
            lambda: self.actions.grid(row=5, column=0, sticky="w"),
            self.root.deiconify,
        )
        for operation in operations:
            try:
                operation()
            except BaseException:
                continue

    def _copy_url(self) -> None:
        copy_local_url(self.root, self.controller.state.url)
        self.copy_button.configure(text="Copied")
        self.root.after(1200, lambda: self.copy_button.configure(text="Copy"))

    def _open_logs(self) -> None:
        try:
            open_log_folder(self.paths.logs_dir)
        except BaseException as exc:
            LOG.error(
                "Unable to open launcher log folder (failure type: %s)",
                _safe_exception_type(exc),
            )
            self.status_var.set(
                "The log folder could not be opened. "
                "You can find it under your local DOCSight data folder."
            )

    def _retry(self) -> None:
        attempt = self.controller.begin_attempt()
        self.controller.state = replace(
            self.controller.state,
            status="Restarting DOCSight…",
        )
        self.render()
        LOG.info("Retry requested; starting a fresh launcher process")
        self.runner.env.pop(BIND_RETRY_ENV, None)
        try:
            relaunch_launcher(cleanup=self.desktop_instance.cleanup)
        except BaseException as exc:
            LOG.error(
                "Recovery available: %s (failure type: %s)",
                RecoveryCode.RELAUNCH_FAILED.value,
                _safe_exception_type(exc),
            )
            self.controller.emit(
                LauncherEvent(
                    attempt=attempt,
                    kind=EventKind.ERROR,
                    recovery=RecoveryCode.RELAUNCH_FAILED,
                    url=self.controller.state.url,
                    safe_exception_type=_safe_exception_type(exc),
                )
            )

    def _close(self) -> None:
        self.root.destroy()
        try:
            self.desktop_instance.cleanup()
        except BaseException:
            pass
        os._exit(self.controller.exit_code)


def show_fatal_startup_message(
    logs_dir: Path | None,
    *,
    message_box: Callable[[object, str, str, int], object] | None = None,
    env: MutableMapping[str, str] | None = None,
) -> None:
    """Show a last-resort Windows message when Tk cannot create the launcher."""
    runtime_env = env if env is not None else os.environ
    if runtime_env.get("DOCSIGHT_SKIP_BROWSER") == "1":
        return
    location = str(logs_dir) if logs_dir is not None else "the local DOCSight data folder"
    text = (
        "DOCSight could not open its startup window. Close DOCSight and try again.\n\n"
        f"Launcher logs: {location}"
    )
    try:
        if message_box is None:
            if sys.platform != "win32":
                return
            import ctypes

            message_box = getattr(ctypes, "windll").user32.MessageBoxW
        message_box(None, text, "DOCSight", 0x10)
    except BaseException:
        return


def run_desktop() -> int:
    """Paint the launcher, then run startup work through its event queue."""
    runtime_env = os.environ
    paths: DesktopPaths | None = None
    desktop_instance: DesktopInstance | None = None
    try:
        paths = configure_desktop_environment(runtime_env)
        parent_handle = _relaunch_parent_handle()
        handoff_outcome = (
            wait_for_previous_launcher(parent_handle)
            if parent_handle is not None
            else HandoffOutcome.COMPLETE
        )
        configure_logging(paths.log_file, paths.runtime_log_file)
        desktop_instance = create_desktop_instance(paths.runtime_file, runtime_env)

        import tkinter as tk
        from tkinter import ttk

        controller = LauncherController("")
        root = tk.Tk()
        runner = StartupRunner(
            controller,
            paths,
            runtime_env,
            desktop_instance=desktop_instance,
            is_relaunch=parent_handle is not None,
            handoff_outcome=handoff_outcome,
        )
        view = TkLauncher(
            root,
            tk,
            ttk,
            controller,
            runner,
            paths,
            desktop_instance,
        )

        root.update()
        root.after(50, view.start)
        root.after(EVENT_POLL_MILLISECONDS, view.poll)
        root.mainloop()
        try:
            desktop_instance.cleanup()
        except BaseException as exc:
            LOG.error(
                "Runtime cleanup failed after launcher mainloop exit "
                "(failure type: %s)",
                _safe_exception_type(exc),
            )
            return 1
        return controller.exit_code
    except BaseException as exc:
        if desktop_instance is not None:
            try:
                desktop_instance.cleanup()
            except BaseException:
                pass
        try:
            LOG.error(
                "Recovery unavailable: startup_surface_failure (failure type: %s)",
                _safe_exception_type(exc),
            )
        except BaseException:
            pass
        show_fatal_startup_message(paths.logs_dir if paths is not None else None)
        return 1


def main() -> int:
    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
