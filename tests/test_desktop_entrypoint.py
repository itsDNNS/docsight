"""Linux-friendly tests for the Windows launcher controller and OS boundaries."""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT / "packaging" / "windows" / "docsight_desktop.py"

spec = importlib.util.spec_from_file_location("docsight_desktop_launcher", LAUNCHER_PATH)
assert spec is not None
assert spec.loader is not None
desktop = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = desktop
spec.loader.exec_module(desktop)


@pytest.fixture(autouse=True)
def close_desktop_logging_handlers():
    """Release module-owned files so Windows temporary directories are removable."""
    root_logger = logging.getLogger()
    root_level = root_logger.level
    launcher_level = desktop.LOG.level
    launcher_propagate = desktop.LOG.propagate
    yield
    desktop._remove_owned_handlers(desktop.LOG)
    desktop._remove_owned_handlers(root_logger)
    desktop._LOGGING_SIGNATURE = None
    root_logger.setLevel(root_level)
    desktop.LOG.setLevel(launcher_level)
    desktop.LOG.propagate = launcher_propagate


def make_paths(tmp_path: Path) -> object:
    return desktop.resolve_desktop_paths({"LOCALAPPDATA": str(tmp_path)})


def make_controller(port: int = 8765) -> object:
    controller = desktop.LauncherController(desktop.local_url(port))
    controller.begin_attempt()
    return controller


def run_runner(monkeypatch, tmp_path, *, selection=None, wait=None, browser=True):
    controller = make_controller()
    paths = make_paths(tmp_path)
    handle = desktop.AppThreadHandle(
        thread=SimpleNamespace(join=lambda: None),
        stopped=threading.Event(),
    )
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(
        desktop,
        "configure_logging",
        lambda *_args: pytest.fail("StartupRunner must not reconfigure logging"),
    )
    monkeypatch.setattr(
        desktop,
        "select_port",
        lambda env: selection or desktop.PortSelection(8765),
    )
    monkeypatch.setattr(desktop, "_start_app_thread", lambda: handle)
    monkeypatch.setattr(
        desktop,
        "_wait_for_ready",
        lambda port, app_handle: wait or desktop.WaitOutcome.READY,
    )
    if isinstance(browser, BaseException):
        def raise_browser(port, env):
            raise browser

        monkeypatch.setattr(desktop, "open_browser", raise_browser)
    else:
        monkeypatch.setattr(desktop, "open_browser", lambda port, env: browser)

    runner = desktop.StartupRunner(controller, paths, {})
    runner.run(controller.state.attempt)
    controller.drain_events()
    return controller, handle


def test_resolve_desktop_paths_uses_localappdata(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "LocalAppData")}

    paths = desktop.resolve_desktop_paths(env)

    assert paths.base_dir == tmp_path / "LocalAppData" / "DOCSight"
    assert paths.data_dir == paths.base_dir / "data"
    assert paths.modules_dir == paths.base_dir / "modules"
    assert paths.logs_dir == paths.base_dir / "logs"
    assert paths.log_file == paths.logs_dir / "launcher.log"
    assert paths.runtime_log_file == paths.logs_dir / "runtime.log"


def test_resolve_desktop_paths_falls_back_to_home_localappdata(tmp_path):
    paths = desktop.resolve_desktop_paths({}, home=tmp_path / "User")

    assert paths.base_dir == tmp_path / "User" / "AppData" / "Local" / "DOCSight"


def test_configure_desktop_environment_creates_paths_and_exports_contract(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path)}

    paths = desktop.configure_desktop_environment(env)

    assert paths.data_dir.is_dir()
    assert paths.modules_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert env["DATA_DIR"] == str(paths.data_dir)
    assert env["MODULES_DIR"] == str(paths.modules_dir)
    assert env["WEB_HOST"] == "127.0.0.1"
    assert env["DOCSIGHT_DESKTOP_MODE"] == "1"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "ok", "version": "v2026-07-05.1", "docsis_health": "waiting"}, True),
        ({"status": "ok", "docsis_health": "waiting"}, False),
        ({"status": "error", "version": "v2026-07-05.1"}, False),
        (None, False),
        (["not", "a", "dict"], False),
    ],
)
def test_detects_docsight_health_payload(payload, expected):
    assert desktop.is_docsight_health_payload(payload) is expected


def test_select_port_opens_existing_docsight_instance(monkeypatch):
    env = {"WEB_PORT": "8765"}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: {"status": "ok", "version": "dev"})
    monkeypatch.setattr(
        desktop,
        "_can_bind_local_port",
        lambda port: pytest.fail("existing instance should skip bind probe"),
    )

    selection = desktop.select_port(env)

    assert selection == desktop.PortSelection(port=8765, existing_instance=True)
    assert "WEB_PORT" in env


def test_select_port_walks_when_preferred_port_has_non_docsight_service(monkeypatch):
    env = {"WEB_PORT": "8765"}
    bind_results = {8765: False, 8766: True}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: {"status": "ok", "service": "other"})
    monkeypatch.setattr(desktop, "_can_bind_local_port", lambda port: bind_results[port])

    selection = desktop.select_port(env, max_port=8766)

    assert selection == desktop.PortSelection(port=8766, existing_instance=False)
    assert env["WEB_PORT"] == "8766"


def test_select_port_uses_default_when_web_port_is_invalid(monkeypatch):
    env = {"WEB_PORT": "not-a-port"}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: None)
    monkeypatch.setattr(desktop, "_can_bind_local_port", lambda port: port == 8765)

    selection = desktop.select_port(env, max_port=8765)

    assert selection == desktop.PortSelection(port=8765, existing_instance=False)
    assert env["WEB_PORT"] == "8765"


def test_select_port_raises_when_range_is_unavailable(monkeypatch):
    env = {"WEB_PORT": "8765"}

    monkeypatch.setattr(desktop, "_fetch_health_json", lambda port: None)
    monkeypatch.setattr(desktop, "_can_bind_local_port", lambda port: False)

    with pytest.raises(RuntimeError, match="No free loopback port"):
        desktop.select_port(env, max_port=8766)


@pytest.mark.parametrize(
    ("platform", "expected_option"),
    [
        ("win32", getattr(desktop.socket, "SO_EXCLUSIVEADDRUSE", -5)),
        ("linux", desktop.socket.SO_REUSEADDR),
    ],
)
def test_bind_probe_uses_platform_specific_socket_option(platform, expected_option):
    calls = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def setsockopt(self, level, option, value):
            calls.append(("setsockopt", level, option, value))

        def bind(self, address):
            calls.append(("bind", address))

    assert desktop._can_bind_local_port(
        8765,
        platform=platform,
        socket_factory=lambda *_args: FakeSocket(),
    )
    assert calls == [
        ("setsockopt", desktop.socket.SOL_SOCKET, expected_option, 1),
        ("bind", ("127.0.0.1", 8765)),
    ]


def test_bind_probe_returns_false_on_bind_failure():
    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def setsockopt(self, *_args):
            return None

        def bind(self, _address):
            raise OSError("occupied")

    assert desktop._can_bind_local_port(
        8765,
        platform="win32",
        socket_factory=lambda *_args: FakeSocket(),
    ) is False


def test_controller_applies_phase_transitions_and_ready():
    controller = make_controller()
    attempt = controller.state.attempt

    for phase in (
        desktop.StartupPhase.START,
        desktop.StartupPhase.WAIT,
        desktop.StartupPhase.OPEN,
    ):
        controller.emit(
            desktop.LauncherEvent(
                attempt,
                desktop.EventKind.PHASE,
                phase=phase,
                url=desktop.local_url(8766),
            )
        )
        assert controller.drain_events() is True
        assert controller.state.phase is phase

    controller.emit(
        desktop.LauncherEvent(
            attempt,
            desktop.EventKind.READY,
            url=desktop.local_url(8766),
            owns_server=True,
        )
    )
    controller.drain_events()

    assert controller.state.ready is True
    assert controller.state.owns_server is True
    assert controller.state.url == "http://127.0.0.1:8766/"


def test_controller_ignores_events_from_stale_attempt():
    controller = make_controller()
    stale_attempt = controller.state.attempt
    active_attempt = controller.begin_attempt()

    controller.emit(
        desktop.LauncherEvent(
            stale_attempt,
            desktop.EventKind.ERROR,
            recovery=desktop.RecoveryCode.TIMEOUT,
            url=desktop.local_url(8765),
        )
    )
    controller.emit(
        desktop.LauncherEvent(
            active_attempt,
            desktop.EventKind.PHASE,
            phase=desktop.StartupPhase.START,
            url=desktop.local_url(8766),
        )
    )
    controller.drain_events()

    assert controller.state.attempt == active_attempt
    assert controller.state.phase is desktop.StartupPhase.START
    assert controller.state.recovery is None
    assert controller.state.url == "http://127.0.0.1:8766/"


def test_startup_runner_reaches_ready_and_emits_all_phases(monkeypatch, tmp_path):
    controller = make_controller()
    paths = make_paths(tmp_path)
    emitted = []
    original_emit = controller.emit

    def capture(event):
        emitted.append(event)
        original_emit(event)

    controller.emit = capture
    handle = desktop.AppThreadHandle(
        thread=SimpleNamespace(join=lambda: None),
        stopped=threading.Event(),
    )
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(desktop, "select_port", lambda env: desktop.PortSelection(8766))
    monkeypatch.setattr(desktop, "_start_app_thread", lambda: handle)
    monkeypatch.setattr(desktop, "_wait_for_ready", lambda port, app_handle: desktop.WaitOutcome.READY)
    monkeypatch.setattr(desktop, "open_browser", lambda port, env: True)

    desktop.StartupRunner(controller, paths, {}).run(controller.state.attempt)
    controller.drain_events()

    assert [event.phase for event in emitted if event.kind is desktop.EventKind.PHASE] == [
        desktop.StartupPhase.START,
        desktop.StartupPhase.WAIT,
        desktop.StartupPhase.OPEN,
    ]
    assert any(event.kind is desktop.EventKind.READY for event in emitted)
    assert controller.state.ready is True
    assert controller.state.closed is True


def test_startup_runner_reports_no_free_port(monkeypatch, tmp_path):
    controller = make_controller()
    paths = make_paths(tmp_path)
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(
        desktop,
        "select_port",
        lambda env: (_ for _ in ()).throw(RuntimeError("occupied by secret service")),
    )

    desktop.StartupRunner(controller, paths, {}).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is desktop.RecoveryCode.NO_PORT
    assert controller.state.url == ""
    assert "secret" not in controller.state.status


def test_startup_runner_reports_readiness_timeout(monkeypatch, tmp_path):
    controller, _ = run_runner(
        monkeypatch,
        tmp_path,
        wait=desktop.WaitOutcome.TIMEOUT,
    )

    assert controller.state.recovery is desktop.RecoveryCode.TIMEOUT
    assert controller.state.url == "http://127.0.0.1:8765/"


def test_startup_runner_reports_app_thread_system_exit(monkeypatch, tmp_path):
    controller = make_controller()
    paths = make_paths(tmp_path)
    handle = desktop.AppThreadHandle(
        thread=SimpleNamespace(join=lambda: None),
        stopped=threading.Event(),
    )
    handle.failure_type = "SystemExit"
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(desktop, "select_port", lambda env: desktop.PortSelection(8765))
    monkeypatch.setattr(desktop, "_start_app_thread", lambda: handle)
    monkeypatch.setattr(desktop, "_wait_for_ready", lambda port, app_handle: desktop.WaitOutcome.APP_FAILED)
    desktop.StartupRunner(controller, paths, {}).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is desktop.RecoveryCode.APP_FAILED
    assert controller.state.status == "DOCSight stopped unexpectedly during startup."


@pytest.mark.parametrize(
    ("browser_result", "failure_type"),
    [
        (False, "BrowserOpenReturnedFalse"),
        (RuntimeError("credential=do-not-show"), "RuntimeError"),
    ],
)
def test_browser_open_failures_keep_ready_recovery_surface(
    monkeypatch,
    tmp_path,
    browser_result,
    failure_type,
):
    controller, _ = run_runner(
        monkeypatch,
        tmp_path,
        browser=browser_result,
    )

    assert controller.state.recovery is desktop.RecoveryCode.BROWSER_FAILED
    assert controller.state.ready is True
    assert controller.state.url == "http://127.0.0.1:8765/"
    assert failure_type not in controller.state.status
    assert "credential" not in controller.state.status


def test_existing_instance_runs_wait_and_browser_phases_without_app_thread(
    monkeypatch,
    tmp_path,
):
    controller = make_controller()
    paths = make_paths(tmp_path)
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(
        desktop,
        "select_port",
        lambda env: desktop.PortSelection(8765, existing_instance=True),
    )
    monkeypatch.setattr(
        desktop,
        "_start_app_thread",
        lambda: pytest.fail("existing instance must not start an app thread"),
    )
    monkeypatch.setattr(desktop, "open_browser", lambda port, env: True)

    desktop.StartupRunner(controller, paths, {}).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.ready is True
    assert controller.state.owns_server is False
    assert controller.state.closed is True


def test_app_thread_wrapper_captures_baseexception_type_without_message(monkeypatch):
    from app import main as app_main_module

    monkeypatch.setattr(desktop, "_ensure_repo_on_path", lambda: None)
    monkeypatch.setattr(
        app_main_module,
        "main",
        lambda: (_ for _ in ()).throw(SystemExit("credential=do-not-retain")),
    )

    handle = desktop._start_app_thread()
    assert handle.thread is not None
    handle.thread.join(timeout=2)

    assert handle.stopped.is_set()
    assert handle.failure_type == "SystemExit"
    assert "credential" not in handle.failure_type


def test_open_browser_can_be_skipped_for_ci_smoke(monkeypatch):
    calls = []

    result = desktop.open_browser(
        8765,
        {"DOCSIGHT_SKIP_BROWSER": "1"},
        lambda url: calls.append(url),
    )

    assert result is True
    assert calls == []


def test_open_browser_returns_false_and_uses_loopback_url():
    calls = []

    result = desktop.open_browser(8766, {}, lambda url: calls.append(url) or False)

    assert result is False
    assert calls == ["http://127.0.0.1:8766/"]


@pytest.mark.parametrize("initialize_result", [0, 1])
def test_default_windows_browser_balances_successful_com_initialization(
    monkeypatch,
    initialize_result,
):
    calls = []
    com_api = SimpleNamespace(
        CoInitializeEx=lambda reserved, mode: (
            calls.append(("initialize", reserved, mode)) or initialize_result
        ),
        CoUninitialize=lambda: calls.append("uninitialize"),
    )
    monkeypatch.setattr(
        desktop.webbrowser,
        "open",
        lambda url: calls.append(("open", url)) or True,
    )

    assert desktop.open_browser(
        8765,
        {},
        platform="win32",
        com_api=com_api,
    ) is True
    assert calls == [
        ("initialize", None, 0x2),
        ("open", "http://127.0.0.1:8765/"),
        "uninitialize",
    ]


def test_default_windows_browser_handles_changed_com_mode_without_uninitialize(
    monkeypatch,
):
    calls = []
    com_api = SimpleNamespace(
        CoInitializeEx=lambda *_args: -2147417850,
        CoUninitialize=lambda: calls.append("uninitialize"),
    )
    monkeypatch.setattr(
        desktop.webbrowser,
        "open",
        lambda url: calls.append(("open", url)) or True,
    )

    assert desktop.open_browser(
        8765,
        {},
        platform="win32",
        com_api=com_api,
    ) is True
    assert calls == [("open", "http://127.0.0.1:8765/")]


def test_custom_windows_browser_callback_does_not_require_com():
    calls = []
    com_api = SimpleNamespace(
        CoInitializeEx=lambda *_args: pytest.fail("custom callback must skip COM"),
        CoUninitialize=lambda: pytest.fail("custom callback must skip COM"),
    )

    assert desktop.open_browser(
        8765,
        {},
        lambda url: calls.append(url) or True,
        platform="win32",
        com_api=com_api,
    ) is True
    assert calls == ["http://127.0.0.1:8765/"]


def test_copy_local_url_uses_clipboard_contract():
    calls = []
    clipboard = SimpleNamespace(
        clipboard_clear=lambda: calls.append("clear"),
        clipboard_append=lambda value: calls.append(("append", value)),
    )

    desktop.copy_local_url(clipboard, "http://127.0.0.1:8765/")

    assert calls == ["clear", ("append", "http://127.0.0.1:8765/")]


@pytest.mark.parametrize(
    ("requested_width", "requested_height", "expected"),
    [
        (420, 260, "480x300+720+200"),
        (760, 520, "760x520+580+126"),
    ],
)
def test_centered_window_geometry_preserves_scaled_widget_request(
    requested_width,
    requested_height,
    expected,
):
    assert desktop.centered_window_geometry(
        requested_width,
        requested_height,
        1920,
        900,
    ) == expected


def test_open_log_folder_uses_windows_shell_action(tmp_path):
    calls = []

    result = desktop.open_log_folder(
        tmp_path,
        platform="win32",
        windows_open=lambda path: calls.append(path),
    )

    assert result is True
    assert calls == [str(tmp_path)]


def test_open_log_folder_is_testable_outside_windows(tmp_path):
    calls = []

    desktop.open_log_folder(
        tmp_path,
        platform="linux",
        process_open=lambda command: calls.append(command),
    )

    assert calls == [["xdg-open", str(tmp_path)]]


def test_relaunch_spawns_before_terminating_current_process():
    calls = []

    desktop.relaunch_launcher(
        spawn=lambda: calls.append("spawn"),
        terminate=lambda: calls.append("terminate"),
    )

    assert calls == ["spawn", "terminate"]


def test_spawn_launcher_process_is_isolated_for_unit_tests(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "launcher_working_directory", lambda: ROOT)

    result = desktop.spawn_launcher_process(
        ["python", "launcher.py"],
        process_factory=lambda *args, **kwargs: calls.append((args, kwargs)) or "child",
    )

    assert result == "child"
    assert calls == [
        (
            (["python", "launcher.py"],),
            {"cwd": str(ROOT), "close_fds": True},
        )
    ]


def test_windows_spawn_inherits_real_parent_handle_and_closes_local_copy(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "launcher_working_directory", lambda: ROOT)
    startupinfo = SimpleNamespace(lpAttributeList=None)

    desktop.spawn_launcher_process(
        process_factory=lambda *args, **kwargs: calls.append(("spawn", args, kwargs)),
        platform="win32",
        duplicate_handle=lambda: calls.append("duplicate") or 4321,
        close_handle=lambda handle: calls.append(("close", handle)),
        startupinfo_factory=lambda: startupinfo,
    )

    assert calls[0] == "duplicate"
    _, args, kwargs = calls[1]
    command = args[0]
    assert command[-1] == "--docsight-relaunch-handle=4321"
    assert desktop._relaunch_parent_handle(command) == 4321
    assert kwargs == {
        "cwd": str(ROOT),
        "close_fds": True,
        "startupinfo": startupinfo,
    }
    assert startupinfo.lpAttributeList == {"handle_list": [4321]}
    assert calls[2] == ("close", 4321)


def test_windows_parent_handoff_waits_on_inherited_handle_and_closes_it():
    calls = []

    class FakeWindowsApi:
        def WaitForSingleObject(self, handle, timeout):
            calls.append(("wait", handle, timeout))
            return 0

        def CloseHandle(self, handle):
            calls.append(("close", handle))

    assert desktop.wait_for_previous_launcher(
        99,
        timeout_milliseconds=2500,
        windows_api=FakeWindowsApi(),
    ) is desktop.HandoffOutcome.COMPLETE
    assert calls == [
        ("wait", 99, 2500),
        ("close", 99),
    ]


@pytest.mark.parametrize(
    ("wait_result", "expected"),
    [
        (0x102, desktop.HandoffOutcome.TIMEOUT),
        (0xFFFFFFFF, desktop.HandoffOutcome.FAILED),
        (17, desktop.HandoffOutcome.FAILED),
    ],
)
def test_windows_parent_handoff_distinguishes_timeout_and_invalid_wait_results(
    wait_result,
    expected,
):
    closed = []
    api = SimpleNamespace(
        WaitForSingleObject=lambda *_args: wait_result,
        CloseHandle=lambda handle: closed.append(handle),
    )

    assert desktop.wait_for_previous_launcher(
        99,
        windows_api=api,
    ) is expected
    assert closed == [99]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process handle contract")
def test_windows_parent_handoff_uses_real_process_handle_api():
    handle = desktop.duplicate_current_process_handle()

    assert desktop.wait_for_previous_launcher(
        handle,
        timeout_milliseconds=1,
    ) is desktop.HandoffOutcome.TIMEOUT


def test_parent_handoff_timeout_stays_on_recovery_before_port_selection(
    monkeypatch,
    tmp_path,
):
    controller = make_controller()
    paths = make_paths(tmp_path)
    monkeypatch.setattr(
        desktop,
        "select_port",
        lambda env: pytest.fail("port selection must wait for the old launcher"),
    )

    desktop.StartupRunner(
        controller,
        paths,
        {},
        is_relaunch=True,
        handoff_outcome=desktop.HandoffOutcome.TIMEOUT,
    ).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is desktop.RecoveryCode.HANDOFF_FAILED
    assert controller.state.status == (
        "DOCSight could not safely finish restarting. "
        "Close it and start DOCSight again."
    )


@pytest.mark.parametrize(
    ("parent_handle", "expected_prefix"),
    [
        (None, ["environment", "logging", "tk"]),
        (99, ["environment", ("wait", 99), "logging", "tk"]),
    ],
)
def test_run_desktop_waits_before_single_logging_configuration(
    monkeypatch,
    tmp_path,
    parent_handle,
    expected_prefix,
):
    calls = []
    paths = make_paths(tmp_path)
    fake_tk = SimpleNamespace(
        ttk=SimpleNamespace(),
        Tk=lambda: (
            calls.append("tk")
            or (_ for _ in ()).throw(RuntimeError("stop after ordering check"))
        ),
    )
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setattr(
        desktop,
        "configure_desktop_environment",
        lambda env: calls.append("environment") or paths,
    )
    monkeypatch.setattr(
        desktop,
        "_relaunch_parent_handle",
        lambda: parent_handle,
    )
    monkeypatch.setattr(
        desktop,
        "wait_for_previous_launcher",
        lambda handle: calls.append(("wait", handle))
        or desktop.HandoffOutcome.COMPLETE,
    )
    monkeypatch.setattr(
        desktop,
        "configure_logging",
        lambda launcher, runtime: calls.append("logging"),
    )
    monkeypatch.setattr(
        desktop,
        "show_fatal_startup_message",
        lambda logs_dir: calls.append("fatal"),
    )

    assert desktop.run_desktop() == 1
    assert calls[:-1] == expected_prefix
    assert calls[-1] == "fatal"
    assert calls.count("logging") == 1


def test_runtime_root_uses_source_checkout_by_default():
    assert desktop.get_runtime_root() == ROOT


def test_runtime_root_uses_pyinstaller_meipass(monkeypatch, tmp_path):
    bundle_root = tmp_path / "_internal"

    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop.sys, "_MEIPASS", str(bundle_root), raising=False)

    assert desktop.get_runtime_root() == bundle_root


def test_configure_logging_installs_private_launcher_and_root_runtime_handlers(
    tmp_path,
):
    log_file = tmp_path / "logs" / "launcher.log"
    runtime_log_file = tmp_path / "logs" / "runtime.log"
    foreign_handler = logging.NullHandler()
    root_logger = logging.getLogger()
    root_logger.addHandler(foreign_handler)

    try:
        desktop.configure_logging(log_file, runtime_log_file)

        assert log_file.parent.is_dir()
        launcher_handlers = [
            handler
            for handler in desktop.LOG.handlers
            if getattr(handler, desktop._OWNED_HANDLER_ATTRIBUTE, False)
        ]
        runtime_handlers = [
            handler
            for handler in root_logger.handlers
            if getattr(handler, desktop._OWNED_HANDLER_ATTRIBUTE, False)
        ]
        assert len(launcher_handlers) == 1
        assert len(runtime_handlers) == 1
        assert isinstance(launcher_handlers[0], desktop.RotatingFileHandler)
        assert isinstance(runtime_handlers[0], desktop.RotatingFileHandler)
        assert launcher_handlers[0].maxBytes == 1_000_000
        assert runtime_handlers[0].maxBytes == 5_000_000
        assert foreign_handler in root_logger.handlers
        assert desktop.LOG.propagate is False
    finally:
        root_logger.removeHandler(foreign_handler)


def test_configure_logging_is_idempotent_for_same_process_paths(tmp_path):
    paths = make_paths(tmp_path)

    desktop.configure_logging(paths.log_file, paths.runtime_log_file)
    launcher_handler = next(
        handler
        for handler in desktop.LOG.handlers
        if getattr(handler, desktop._OWNED_HANDLER_ATTRIBUTE, False)
    )
    runtime_handler = next(
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, desktop._OWNED_HANDLER_ATTRIBUTE, False)
    )

    desktop.configure_logging(paths.log_file, paths.runtime_log_file)

    assert launcher_handler in desktop.LOG.handlers
    assert runtime_handler in logging.getLogger().handlers


def test_launcher_log_excludes_runtime_records_and_tracebacks(tmp_path):
    log_file = tmp_path / "logs" / "launcher.log"
    runtime_log_file = tmp_path / "logs" / "runtime.log"
    desktop.configure_logging(log_file, runtime_log_file)

    desktop.LOG.info("Phase: safe launcher record")
    logging.getLogger("app.main").error("password=runtime-secret")
    try:
        raise RuntimeError("password=launcher-secret")
    except RuntimeError:
        desktop.LOG.error("failure type: RuntimeError", exc_info=True)
    for handler in desktop.LOG.handlers:
        handler.flush()
    for handler in logging.getLogger().handlers:
        if getattr(handler, desktop._OWNED_HANDLER_ATTRIBUTE, False):
            handler.flush()

    log_text = log_file.read_text(encoding="utf-8")
    runtime_text = runtime_log_file.read_text(encoding="utf-8")
    assert "safe launcher record" in log_text
    assert "failure type: RuntimeError" in log_text
    assert "runtime-secret" not in log_text
    assert "launcher-secret" not in log_text
    assert "Traceback" not in log_text
    assert "runtime-secret" in runtime_text
    assert "safe launcher record" not in runtime_text


def test_startup_failure_logging_omits_raw_exception_and_traceback(
    monkeypatch,
    tmp_path,
):
    controller = make_controller()
    paths = make_paths(tmp_path)
    desktop.configure_logging(paths.log_file, paths.runtime_log_file)
    monkeypatch.setattr(
        desktop,
        "select_port",
        lambda env: (_ for _ in ()).throw(
            RuntimeError("password=secret request_body=private")
        ),
    )

    desktop.StartupRunner(
        controller,
        paths,
        {"LOCALAPPDATA": str(tmp_path)},
    ).run(controller.state.attempt)
    for handler in desktop.LOG.handlers:
        handler.flush()
    log_text = paths.log_file.read_text(encoding="utf-8")

    assert "Recovery available: no_free_port" in log_text
    assert "failure type: RuntimeError" in log_text
    assert "password=secret" not in log_text
    assert "request_body" not in log_text
    assert "Traceback" not in log_text


def test_generic_startup_failure_is_recorded_by_private_launcher_log(
    monkeypatch,
    tmp_path,
):
    controller = make_controller()
    paths = make_paths(tmp_path)
    desktop.configure_logging(paths.log_file, paths.runtime_log_file)
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(desktop, "select_port", lambda env: desktop.PortSelection(8765))
    monkeypatch.setattr(
        desktop,
        "_start_app_thread",
        lambda: (_ for _ in ()).throw(RuntimeError("password=secret")),
    )

    desktop.StartupRunner(
        controller,
        paths,
        {"LOCALAPPDATA": str(tmp_path)},
    ).run(controller.state.attempt)
    controller.drain_events()
    for handler in desktop.LOG.handlers:
        handler.flush()
    log_text = paths.log_file.read_text(encoding="utf-8")

    assert controller.state.recovery is desktop.RecoveryCode.STARTUP_FAILED
    assert "Recovery available: startup_failure" in log_text
    assert "failure type: RuntimeError" in log_text
    assert "password=secret" not in log_text
    assert "Traceback" not in log_text


def test_smoke_failure_injection_requires_browser_skip_boundary(monkeypatch, tmp_path):
    controller = make_controller()
    paths = make_paths(tmp_path)
    handle = desktop.AppThreadHandle(
        thread=SimpleNamespace(join=lambda: None),
        stopped=threading.Event(),
    )
    injected = []
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(desktop, "select_port", lambda env: desktop.PortSelection(8765))

    def start_app_thread(*, inject_smoke_failure=False):
        injected.append(inject_smoke_failure)
        if not inject_smoke_failure:
            return handle
        stopped = threading.Event()
        stopped.set()
        return desktop.AppThreadHandle(
            thread=SimpleNamespace(join=lambda: None),
            stopped=stopped,
            failure_type="RuntimeError",
        )

    monkeypatch.setattr(desktop, "_start_app_thread", start_app_thread)
    monkeypatch.setattr(
        desktop,
        "_wait_for_ready",
        lambda port, app_handle: (
            desktop.WaitOutcome.APP_FAILED
            if app_handle.stopped.is_set()
            else desktop.WaitOutcome.READY
        ),
    )
    monkeypatch.setattr(desktop, "open_browser", lambda port, env: True)
    desktop.StartupRunner(
        controller,
        paths,
        {"DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE": "1"},
    ).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is None
    assert injected == [False]

    controller = make_controller()
    env = {
        "DOCSIGHT_SKIP_BROWSER": "1",
        "DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE": "1",
    }

    desktop.StartupRunner(controller, paths, env).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is desktop.RecoveryCode.APP_FAILED
    assert injected == [False, True]


def test_relaunch_handle_makes_smoke_failure_injection_one_shot(monkeypatch, tmp_path):
    controller = make_controller()
    paths = make_paths(tmp_path)
    handle = desktop.AppThreadHandle(
        thread=SimpleNamespace(join=lambda: None),
        stopped=threading.Event(),
    )
    injected = []
    monkeypatch.setattr(desktop, "configure_desktop_environment", lambda env: paths)
    monkeypatch.setattr(desktop, "select_port", lambda env: desktop.PortSelection(8765))

    def start_app_thread(*, inject_smoke_failure=False):
        injected.append(inject_smoke_failure)
        return handle

    monkeypatch.setattr(desktop, "_start_app_thread", start_app_thread)
    monkeypatch.setattr(
        desktop,
        "_wait_for_ready",
        lambda port, app_handle: desktop.WaitOutcome.READY,
    )
    monkeypatch.setattr(desktop, "open_browser", lambda port, env: True)

    desktop.StartupRunner(
        controller,
        paths,
        {
            "DOCSIGHT_SKIP_BROWSER": "1",
            "DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE": "1",
        },
        is_relaunch=True,
    ).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is None
    assert injected == [False]


def test_browser_smoke_injection_reaches_recovery_without_browser(
    monkeypatch,
    tmp_path,
):
    controller = make_controller()
    paths = make_paths(tmp_path)
    handle = desktop.AppThreadHandle(
        thread=SimpleNamespace(join=lambda: None),
        stopped=threading.Event(),
    )
    monkeypatch.setattr(desktop, "select_port", lambda env: desktop.PortSelection(8765))
    monkeypatch.setattr(desktop, "_start_app_thread", lambda: handle)
    monkeypatch.setattr(
        desktop,
        "_wait_for_ready",
        lambda port, app_handle: desktop.WaitOutcome.READY,
    )
    monkeypatch.setattr(
        desktop,
        "open_browser",
        lambda *_args: pytest.fail("browser injection must not invoke a browser"),
    )

    desktop.StartupRunner(
        controller,
        paths,
        {
            "DOCSIGHT_SKIP_BROWSER": "1",
            "DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE": "1",
        },
    ).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is desktop.RecoveryCode.BROWSER_FAILED
    assert controller.state.ready is True
    assert controller.state.url == "http://127.0.0.1:8765/"


def test_no_port_smoke_injection_clears_url_before_port_selection(
    monkeypatch,
    tmp_path,
):
    controller = make_controller()
    paths = make_paths(tmp_path)
    monkeypatch.setattr(
        desktop,
        "select_port",
        lambda env: pytest.fail("no-port injection must skip selection"),
    )

    desktop.StartupRunner(
        controller,
        paths,
        {
            "DOCSIGHT_SKIP_BROWSER": "1",
            "DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE": "1",
        },
    ).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is desktop.RecoveryCode.NO_PORT
    assert controller.state.url == ""


@pytest.mark.parametrize(
    "injection_name",
    [
        "DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE",
        "DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE",
    ],
)
def test_relaunch_does_not_repeat_new_smoke_injections(
    monkeypatch,
    tmp_path,
    injection_name,
):
    controller = make_controller()
    paths = make_paths(tmp_path)
    handle = desktop.AppThreadHandle(
        thread=SimpleNamespace(join=lambda: None),
        stopped=threading.Event(),
    )
    browser_calls = []
    monkeypatch.setattr(desktop, "select_port", lambda env: desktop.PortSelection(8765))
    monkeypatch.setattr(desktop, "_start_app_thread", lambda: handle)
    monkeypatch.setattr(
        desktop,
        "_wait_for_ready",
        lambda port, app_handle: desktop.WaitOutcome.READY,
    )
    monkeypatch.setattr(
        desktop,
        "open_browser",
        lambda port, env: browser_calls.append(port) or True,
    )

    desktop.StartupRunner(
        controller,
        paths,
        {
            "DOCSIGHT_SKIP_BROWSER": "1",
            injection_name: "1",
        },
        is_relaunch=True,
    ).run(controller.state.attempt)
    controller.drain_events()

    assert controller.state.recovery is None
    assert controller.state.ready is True
    assert browser_calls == [8765]


def make_minimal_view_for_recovery():
    values = {"status": [], "url": [], "copy": [], "actions": [], "after": []}
    view = desktop.TkLauncher.__new__(desktop.TkLauncher)
    view.controller = make_controller()
    view.status_var = SimpleNamespace(
        set=lambda value: values["status"].append(value)
    )
    view.url_var = SimpleNamespace(set=lambda value: values["url"].append(value))
    view.copy_button = SimpleNamespace(
        configure=lambda **kwargs: values["copy"].append(kwargs)
    )
    view.actions = SimpleNamespace(
        grid=lambda **kwargs: values["actions"].append(kwargs)
    )
    view.root = SimpleNamespace(
        deiconify=lambda: None,
        after=lambda *args: values["after"].append(args),
        destroy=lambda: None,
    )
    return view, values


def test_tk_callback_exception_is_sanitized_and_shows_recovery(tmp_path):
    view, values = make_minimal_view_for_recovery()
    paths = make_paths(tmp_path)
    desktop.configure_logging(paths.log_file, paths.runtime_log_file)

    view._report_callback_exception(
        RuntimeError,
        RuntimeError("password=secret"),
        object(),
    )
    for handler in desktop.LOG.handlers:
        handler.flush()
    log_text = paths.log_file.read_text(encoding="utf-8")

    assert view.controller.state.recovery is desktop.RecoveryCode.STARTUP_FAILED
    assert view.controller.exit_code == 1
    assert view.controller.state.status == "DOCSight could not finish starting."
    assert all("secret" not in value for value in values["status"])
    assert values["actions"] == [{"row": 5, "column": 0, "sticky": "w"}]
    assert "failure type: RuntimeError" in log_text
    assert "password=secret" not in log_text
    assert "Traceback" not in log_text


def test_render_failure_retains_minimal_recovery_surface():
    view, values = make_minimal_view_for_recovery()
    view._render_full = lambda: (_ for _ in ()).throw(
        RuntimeError("private callback detail")
    )

    view.render()

    assert view.controller.state.recovery is desktop.RecoveryCode.STARTUP_FAILED
    assert values["status"][-1] == "DOCSight could not finish starting."
    assert values["copy"][-1] == {"state": "normal"}
    assert values["actions"][-1] == {"row": 5, "column": 0, "sticky": "w"}


def test_poll_failure_recovers_and_schedules_next_poll():
    view, values = make_minimal_view_for_recovery()
    view.controller.drain_events = lambda: (_ for _ in ()).throw(
        RuntimeError("private poll detail")
    )

    view.poll()

    assert view.controller.state.recovery is desktop.RecoveryCode.STARTUP_FAILED
    assert values["after"] == [(desktop.EVENT_POLL_MILLISECONDS, view.poll)]


def test_tk_launcher_installs_callback_exception_boundary(monkeypatch, tmp_path):
    root = SimpleNamespace()
    monkeypatch.setattr(desktop.TkLauncher, "_build", lambda self: None)

    view = desktop.TkLauncher(
        root,
        SimpleNamespace(),
        SimpleNamespace(),
        make_controller(),
        SimpleNamespace(),
        make_paths(tmp_path),
    )

    assert root.report_callback_exception == view._report_callback_exception


def test_fatal_startup_message_is_sanitized_and_points_to_logs(tmp_path):
    calls = []

    desktop.show_fatal_startup_message(
        tmp_path / "logs",
        message_box=lambda *args: calls.append(args),
    )

    assert len(calls) == 1
    assert calls[0][2] == "DOCSight"
    assert str(tmp_path / "logs") in calls[0][1]
    assert "Traceback" not in calls[0][1]


def test_fatal_startup_message_is_suppressed_in_smoke_mode(tmp_path):
    calls = []

    desktop.show_fatal_startup_message(
        tmp_path / "logs",
        message_box=lambda *args: calls.append(args),
        env={"DOCSIGHT_SKIP_BROWSER": "1"},
    )

    assert calls == []


def test_pre_ui_failure_returns_error_and_uses_fallback(monkeypatch):
    calls = []

    def fail_environment(_env):
        raise RuntimeError("password=secret")

    monkeypatch.setattr(desktop, "configure_desktop_environment", fail_environment)
    monkeypatch.setattr(
        desktop,
        "show_fatal_startup_message",
        lambda logs_dir: calls.append(logs_dir),
    )

    assert desktop.run_desktop() == 1
    assert calls == [None]


def test_close_destroys_window_and_terminates_process(monkeypatch):
    calls = []
    view = desktop.TkLauncher.__new__(desktop.TkLauncher)
    view.root = SimpleNamespace(destroy=lambda: calls.append("destroy"))
    view.controller = SimpleNamespace(exit_code=1)
    monkeypatch.setattr(desktop.os, "_exit", lambda code: calls.append(("exit", code)))

    view._close()

    assert calls == ["destroy", ("exit", 1)]
