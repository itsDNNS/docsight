"""Desktop launcher for local Windows DOCSight preview runs.

This entrypoint is intentionally kept under ``packaging/windows`` so the core
application remains platform-neutral. It prepares per-user runtime paths,
forces loopback-only binding, handles simple single-instance behavior, and
opens the user's default browser once the local server is ready.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import MutableMapping

SOURCE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_PORT = 8775
HEALTH_TIMEOUT_SECONDS = 30

LOG = logging.getLogger("docsight.desktop")


@dataclass(frozen=True)
class DesktopPaths:
    """Per-user paths used by the desktop preview launcher."""

    base_dir: Path
    data_dir: Path
    modules_dir: Path
    logs_dir: Path
    log_file: Path


@dataclass(frozen=True)
class PortSelection:
    """Selected local web port and whether an existing instance owns it."""

    port: int
    existing_instance: bool = False


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
        log_file=logs_dir / "docsight.log",
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
    runtime_env["DOCSIGHT_DESKTOP_MODE"] = "1"
    return paths


def configure_logging(log_file: Path) -> None:
    """Route launcher/app logs to a small rotating per-user log file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[handler],
        force=True,
    )


def _health_url(port: int) -> str:
    return f"http://{DEFAULT_HOST}:{port}/health"


def _fetch_health_json(port: int, timeout: float = 0.5) -> dict | None:
    """Fetch and parse a local DOCSight health response, returning None on miss."""
    request = urllib.request.Request(_health_url(port), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(4096).decode("utf-8")
    except (OSError, urllib.error.URLError, TimeoutError):
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def is_docsight_health_payload(payload: object) -> bool:
    """Return True when a health payload looks like a DOCSight instance."""
    return isinstance(payload, dict) and payload.get("status") == "ok" and "version" in payload


def _can_bind_local_port(port: int) -> bool:
    """Return whether loopback port can be bound by a new DOCSight instance."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((DEFAULT_HOST, port))
        except OSError:
            return False
    return True


def _preferred_port(env: MutableMapping[str, str]) -> int:
    raw = env.get("WEB_PORT", str(DEFAULT_PORT))
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
    """Select a loopback port or detect an already-running DOCSight instance."""
    runtime_env = env if env is not None else os.environ
    preferred = _preferred_port(runtime_env)

    existing_payload = _fetch_health_json(preferred)
    if is_docsight_health_payload(existing_payload):
        return PortSelection(port=preferred, existing_instance=True)

    candidates = [preferred]
    if preferred <= max_port:
        candidates.extend(port for port in range(max(DEFAULT_PORT, preferred + 1), max_port + 1))
    else:
        candidates.extend(range(DEFAULT_PORT, max_port + 1))

    seen: set[int] = set()
    for port in candidates:
        if port in seen:
            continue
        seen.add(port)
        if _can_bind_local_port(port):
            runtime_env["WEB_PORT"] = str(port)
            return PortSelection(port=port, existing_instance=False)

    raise RuntimeError(f"No free loopback port found in {preferred}-{max_port}")


def get_runtime_root() -> Path:
    """Return the root that contains bundled app data or the source checkout."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return SOURCE_ROOT


def _ensure_repo_on_path() -> None:
    runtime_root = str(get_runtime_root())
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)


def _wait_for_ready(port: int, timeout_seconds: float = HEALTH_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_docsight_health_payload(_fetch_health_json(port, timeout=1.0)):
            return True
        time.sleep(0.5)
    return False


def open_browser(port: int) -> None:
    """Open the desktop preview URL in the default browser."""
    if os.environ.get("DOCSIGHT_SKIP_BROWSER") == "1":
        LOG.info("Skipping browser launch because DOCSIGHT_SKIP_BROWSER=1")
        return
    webbrowser.open(f"http://{DEFAULT_HOST}:{port}/")


def _start_app_thread() -> threading.Thread:
    _ensure_repo_on_path()
    from app.main import main as app_main

    thread = threading.Thread(target=app_main, name="docsight-app", daemon=True)
    thread.start()
    return thread


def run_desktop() -> int:
    """Run the DOCSight desktop preview launcher."""
    paths = configure_desktop_environment()
    configure_logging(paths.log_file)

    try:
        selection = select_port()
    except RuntimeError as exc:
        LOG.error("%s", exc)
        print(f"DOCSight Desktop could not find a free local port. See log: {paths.log_file}", file=sys.stderr)
        return 1

    if selection.existing_instance:
        LOG.info("Existing DOCSight instance detected on %s:%d", DEFAULT_HOST, selection.port)
        open_browser(selection.port)
        return 0

    LOG.info("Starting DOCSight Desktop Preview on %s:%d", DEFAULT_HOST, selection.port)
    app_thread = _start_app_thread()

    if _wait_for_ready(selection.port):
        LOG.info("DOCSight Desktop Preview is ready on %s:%d", DEFAULT_HOST, selection.port)
        open_browser(selection.port)
        try:
            while app_thread.is_alive():
                app_thread.join(timeout=60)
        except KeyboardInterrupt:
            LOG.info("DOCSight Desktop Preview interrupted by user")
        return 0

    LOG.error("DOCSight did not become ready within %d seconds", HEALTH_TIMEOUT_SECONDS)
    print(f"DOCSight Desktop did not become ready. See log: {paths.log_file}", file=sys.stderr)
    return 1


def main() -> int:
    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
