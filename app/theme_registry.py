"""Theme registry client -- thin wrapper around the generic module downloader."""

import logging
import os
import shutil

from .module_download import (
    fetch_registry as _fetch_registry,
    download_github_directory,
    is_trusted_url,
)

log = logging.getLogger("docsis.themes")

# Re-export for backward compatibility (used by tests)
_is_trusted_url = is_trusted_url


def fetch_registry(registry_url: str, timeout: int = 10) -> list[dict]:
    """Fetch the theme registry index and return list of valid theme entries."""
    return _fetch_registry(registry_url, key="themes", timeout=timeout)


def download_theme(download_url: str, target_dir: str, timeout: int = 30) -> bool:
    """Download a theme module from the registry into target_dir.

    Uses the generic directory downloader, then validates that both
    manifest.json and theme.json exist.
    """
    if not download_github_directory(download_url, target_dir, timeout):
        return False

    manifest_path = os.path.join(target_dir, "manifest.json")
    theme_path = os.path.join(target_dir, "theme.json")
    if not os.path.isfile(manifest_path) or not os.path.isfile(theme_path):
        log.error("Downloaded theme missing manifest.json or theme.json")
        shutil.rmtree(target_dir, ignore_errors=True)
        return False

    return True
