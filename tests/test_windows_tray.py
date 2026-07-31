"""Linux-friendly tests for the Windows tray adapter contract."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TRAY_PATH = ROOT / "packaging" / "windows" / "tray.py"

spec = importlib.util.spec_from_file_location("docsight_windows_tray", TRAY_PATH)
assert spec is not None
assert spec.loader is not None
tray = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tray
spec.loader.exec_module(tray)


def test_tray_labels_use_german_and_english_fallback():
    german = tray.labels_for_language("de-DE")
    fallback = tray.labels_for_language("fr-FR")

    assert (german.open_app, german.open_logs, german.quit) == (
        "DOCSight öffnen",
        "Log-Ordner öffnen",
        "Beenden",
    )
    assert (fallback.open_app, fallback.open_logs, fallback.quit) == (
        "Open DOCSight",
        "Open log folder",
        "Quit",
    )


def test_language_detection_is_injectable_and_failure_falls_back():
    assert tray.detect_windows_ui_language(lambda: "de-DE") == "de-DE"
    assert tray.detect_windows_ui_language(
        lambda: (_ for _ in ()).throw(OSError("private detail"))
    ) == "en"


def test_tray_callbacks_only_enqueue_commands():
    dispatcher = tray.TrayCommandDispatcher()
    adapter = tray.WindowsTray(
        dispatcher,
        Path("marker"),
        language_detector=lambda: "en-US",
        icon_factory=lambda **_kwargs: SimpleNamespace(),
    )

    adapter.request_open()
    adapter.request_open_logs()
    adapter.request_quit()

    commands = []
    dispatcher.drain(commands.append)
    assert commands == [
        tray.TrayCommand.OPEN_APP,
        tray.TrayCommand.OPEN_LOGS,
        tray.TrayCommand.QUIT,
    ]


def test_default_menu_action_dispatches_open_command(tmp_path):
    captured = {}

    class MenuItem:
        def __init__(self, label, action, **kwargs):
            self.label = label
            self.action = action
            self.default = kwargs.get("default", False)

    class Menu(tuple):
        def __new__(cls, *items):
            return tuple.__new__(cls, items)

    class Icon:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_detached(self, setup=None):
            captured["setup"] = setup

    dispatcher = tray.TrayCommandDispatcher()
    adapter = tray.WindowsTray(
        dispatcher,
        tmp_path / "notice.marker",
        language_detector=lambda: "en",
        icon_factory=Icon,
        menu_factory=Menu,
        menu_item_factory=MenuItem,
        image_factory=lambda: object(),
    )

    adapter.start()
    default_item = next(item for item in captured["menu"] if item.default)
    default_item.action(None, default_item)

    commands = []
    dispatcher.drain(commands.append)
    assert default_item.label == "Open DOCSight"
    assert commands == [tray.TrayCommand.OPEN_APP]


def test_async_native_tray_setup_failure_is_dispatched(tmp_path):
    captured = {}

    class Icon:
        def __init__(self, **_kwargs):
            pass

        def run_detached(self, setup=None):
            captured["setup"] = setup

    class FailingReadyIcon:
        @property
        def visible(self):
            return False

        @visible.setter
        def visible(self, _value):
            raise OSError("private native detail")

    dispatcher = tray.TrayCommandDispatcher()
    adapter = tray.WindowsTray(
        dispatcher,
        tmp_path / "notice.marker",
        icon_factory=Icon,
        menu_factory=lambda *items: items,
        menu_item_factory=lambda *args, **kwargs: (args, kwargs),
        image_factory=lambda: object(),
    )

    adapter.start()
    captured["setup"](FailingReadyIcon())

    commands = []
    dispatcher.drain(commands.append)
    assert commands == [tray.TrayCommand.STARTUP_FAILED]


def test_first_run_notification_marks_only_after_success(tmp_path):
    marker = tmp_path / "tray-notice-v1"
    calls = []

    assert tray.notify_first_run_once(
        marker,
        lambda: calls.append("notify"),
    )
    assert marker.is_file()
    assert not tray.notify_first_run_once(
        marker,
        lambda: calls.append("repeat"),
    )
    assert calls == ["notify"]


def test_failed_first_run_notification_remains_retryable(tmp_path):
    marker = tmp_path / "tray-notice-v1"

    assert not tray.notify_first_run_once(
        marker,
        lambda: (_ for _ in ()).throw(RuntimeError("private detail")),
    )
    assert not marker.exists()


def test_smoke_quit_trigger_requires_skip_browser_and_local_marker(tmp_path):
    dispatcher = tray.TrayCommandDispatcher()
    base_dir = tmp_path / "DOCSight"
    base_dir.mkdir()
    sentinel = base_dir / "quit.signal"
    sentinel.write_text("quit", encoding="utf-8")

    disabled = tray.create_smoke_quit_trigger(
        {"DOCSIGHT_SMOKE_QUIT_SENTINEL": str(sentinel)},
        base_dir,
        dispatcher,
    )
    assert disabled is None

    enabled = tray.create_smoke_quit_trigger(
        {
            "DOCSIGHT_SKIP_BROWSER": "1",
            "DOCSIGHT_SMOKE_QUIT_SENTINEL": str(sentinel),
        },
        base_dir,
        dispatcher,
    )
    assert enabled is not None
    assert enabled.poll()
    commands = []
    dispatcher.drain(commands.append)
    assert commands == [tray.TrayCommand.QUIT]
    assert not sentinel.exists()


def test_smoke_quit_trigger_rejects_path_outside_runtime_dir(tmp_path):
    dispatcher = tray.TrayCommandDispatcher()
    base_dir = tmp_path / "DOCSight"
    base_dir.mkdir()

    trigger = tray.create_smoke_quit_trigger(
        {
            "DOCSIGHT_SKIP_BROWSER": "1",
            "DOCSIGHT_SMOKE_QUIT_SENTINEL": str(tmp_path / "outside.signal"),
        },
        base_dir,
        dispatcher,
    )

    assert trigger is None
