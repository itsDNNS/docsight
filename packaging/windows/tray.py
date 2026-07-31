"""Windows notification-area adapter and its thread-safe command boundary."""

from __future__ import annotations

import ctypes
import os
import queue
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, MutableMapping


class TrayCommand(str, Enum):
    OPEN_APP = "open_app"
    OPEN_LOGS = "open_logs"
    QUIT = "quit"
    STARTUP_FAILED = "startup_failed"


class TrayCommandDispatcher:
    """Move native tray callbacks onto the launcher UI thread."""

    def __init__(self) -> None:
        self._commands: queue.Queue[TrayCommand] = queue.Queue()

    def request(self, command: TrayCommand) -> None:
        self._commands.put(command)

    def drain(self, handler: Callable[[TrayCommand], object]) -> int:
        handled = 0
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return handled
            handler(command)
            handled += 1


@dataclass(frozen=True)
class TrayLabels:
    open_app: str
    open_logs: str
    quit: str
    notification_title: str
    notification_text: str


_ENGLISH_LABELS = TrayLabels(
    open_app="Open DOCSight",
    open_logs="Open log folder",
    quit="Quit",
    notification_title="DOCSight is still running",
    notification_text=(
        "Closing the browser does not exit DOCSight. "
        "Use the tray icon to reopen it or quit."
    ),
)
_GERMAN_LABELS = TrayLabels(
    open_app="DOCSight öffnen",
    open_logs="Log-Ordner öffnen",
    quit="Beenden",
    notification_title="DOCSight läuft weiter",
    notification_text=(
        "Das Schließen des Browsers beendet DOCSight nicht. "
        "Über das Symbol im Infobereich können Sie DOCSight öffnen oder beenden."
    ),
)


def labels_for_language(language: str | None) -> TrayLabels:
    """Return German labels for German Windows UI, English otherwise."""
    normalized = (language or "").replace("_", "-").casefold()
    return _GERMAN_LABELS if normalized == "de" or normalized.startswith("de-") else _ENGLISH_LABELS


def _windows_ui_language() -> str:
    if os.name != "nt":
        return "en"
    language_id = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    if language_id == 0:
        raise OSError("Windows UI locale unavailable")
    return "de" if language_id & 0x03FF == 0x0007 else "en"


def detect_windows_ui_language(
    locale_name_getter: Callable[[], str] | None = None,
) -> str:
    """Detect the Windows UI language through an injectable native boundary."""
    try:
        return (locale_name_getter or _windows_ui_language)()
    except BaseException:
        return "en"


def create_tray_image() -> object:
    """Generate a simple preview tray image without final icon assets."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (23, 105, 170, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((7, 7, 57, 57), fill=(255, 255, 255, 255))
    draw.arc((16, 16, 48, 48), 35, 325, fill=(23, 105, 170, 255), width=7)
    draw.ellipse((27, 27, 37, 37), fill=(23, 105, 170, 255))
    return image


def notify_first_run_once(
    marker_path: Path,
    notify: Callable[[], object],
) -> bool:
    """Notify once, persisting the marker only after notification succeeds."""
    if marker_path.is_file():
        return False
    try:
        notify()
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.touch(exist_ok=True)
    except BaseException:
        return False
    return True


class WindowsTray:
    """Thin pystray adapter; callbacks only enqueue launcher commands."""

    def __init__(
        self,
        dispatcher: TrayCommandDispatcher,
        notification_marker: Path,
        *,
        language_detector: Callable[[], str] = detect_windows_ui_language,
        icon_factory: Callable[..., object] | None = None,
        menu_factory: Callable[..., object] | None = None,
        menu_item_factory: Callable[..., object] | None = None,
        image_factory: Callable[[], object] = create_tray_image,
    ) -> None:
        self.dispatcher = dispatcher
        self.notification_marker = notification_marker
        self.language_detector = language_detector
        self._icon_factory = icon_factory
        self._menu_factory = menu_factory
        self._menu_item_factory = menu_item_factory
        self._image_factory = image_factory
        self._icon: object | None = None

    def request_open(self, *_args: object) -> None:
        self.dispatcher.request(TrayCommand.OPEN_APP)

    def request_open_logs(self, *_args: object) -> None:
        self.dispatcher.request(TrayCommand.OPEN_LOGS)

    def request_quit(self, *_args: object) -> None:
        self.dispatcher.request(TrayCommand.QUIT)

    def start(self) -> None:
        if self._icon is not None:
            return
        if (
            self._icon_factory is None
            or self._menu_factory is None
            or self._menu_item_factory is None
        ):
            import pystray

            icon_factory = self._icon_factory or pystray.Icon
            menu_factory = self._menu_factory or pystray.Menu
            menu_item_factory = self._menu_item_factory or pystray.MenuItem
        else:
            icon_factory = self._icon_factory
            menu_factory = self._menu_factory
            menu_item_factory = self._menu_item_factory

        labels = labels_for_language(self.language_detector())
        menu = menu_factory(
            menu_item_factory(
                labels.open_app,
                self.request_open,
                default=True,
            ),
            menu_item_factory(labels.open_logs, self.request_open_logs),
            menu_item_factory(labels.quit, self.request_quit),
        )
        icon = icon_factory(
            name="DOCSight",
            icon=self._image_factory(),
            title="DOCSight",
            menu=menu,
        )
        self._icon = icon

        def setup(ready_icon: object) -> None:
            try:
                setattr(ready_icon, "visible", True)
                notify_first_run_once(
                    self.notification_marker,
                    lambda: ready_icon.notify(
                        labels.notification_text,
                        labels.notification_title,
                    ),
                )
            except BaseException:
                self.dispatcher.request(TrayCommand.STARTUP_FAILED)

        icon.run_detached(setup=setup)

    def stop(self) -> None:
        icon = self._icon
        self._icon = None
        if icon is not None:
            icon.stop()


@dataclass(frozen=True)
class SmokeQuitTrigger:
    """File-based packaged-smoke trigger feeding the tray command queue."""

    path: Path
    dispatcher: TrayCommandDispatcher

    def poll(self) -> bool:
        if not self.path.is_file():
            return False
        try:
            self.path.unlink()
        except OSError:
            return False
        self.dispatcher.request(TrayCommand.QUIT)
        return True


def create_smoke_quit_trigger(
    env: MutableMapping[str, str],
    base_dir: Path,
    dispatcher: TrayCommandDispatcher,
) -> SmokeQuitTrigger | None:
    """Enable the local sentinel only inside the skip-browser smoke boundary."""
    if env.get("DOCSIGHT_SKIP_BROWSER") != "1":
        return None
    configured = env.get("DOCSIGHT_SMOKE_QUIT_SENTINEL")
    if not configured:
        return None
    candidate = Path(configured)
    try:
        resolved_base = base_dir.resolve()
        resolved_candidate = candidate.resolve()
    except OSError:
        return None
    if not candidate.is_absolute() or resolved_candidate.parent != resolved_base:
        return None
    return SmokeQuitTrigger(resolved_candidate, dispatcher)
