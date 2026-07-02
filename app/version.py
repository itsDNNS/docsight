"""Application version helpers."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache


def _read_version_file() -> str | None:
    """Return a packaged VERSION value when present."""
    for vpath in ("/app/VERSION", os.path.join(os.path.dirname(__file__), "..", "VERSION")):
        try:
            with open(vpath, encoding="utf-8") as f:
                version = f.read().strip()
                if version:
                    return version
        except FileNotFoundError:
            pass
    return None


def _git_tag(*args: str) -> str | None:
    try:
        version = subprocess.check_output(
            ["git", "describe", "--tags", *args],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None
    return version or None


@lru_cache(maxsize=1)
def get_available_app_version() -> str | None:
    """Return the exact running DOCSight version when available."""
    return _read_version_file() or _git_tag("--exact-match")


def get_app_version() -> str:
    """Return the running DOCSight version, or ``dev`` for display fallback."""
    return get_available_app_version() or _git_tag("--abbrev=0") or "dev"
