"""Theme registry helpers and the built-in DOCSight themes."""

from __future__ import annotations

import logging
import os
from typing import Any

from .module_download import (
    fetch_registry as _fetch_registry,
    download_github_directory,
    is_trusted_url,
)
from .path_safety import safe_child_file
from .theme_catalog import load_builtin_themes

log = logging.getLogger("docsis.themes")

# Re-export for backward compatibility (used by tests)
_is_trusted_url = is_trusted_url

# Built-in themes are application-owned data, kept in a validated JSON catalog
# so startup does not need wrapper module directories or per-theme manifests.
BUILTIN_THEMES: tuple[dict[str, Any], ...] = load_builtin_themes()


def fetch_registry(registry_url: str, timeout: int = 10) -> list[dict]:
    """Fetch the theme registry index and return list of valid theme entries."""
    return _fetch_registry(registry_url, key="themes", timeout=timeout)


def download_theme(download_url: str, target_dir: str, timeout: int = 30) -> bool:
    """Download a theme module from the registry into target_dir.

    Uses the generic directory downloader, then validates that both
    manifest.json and theme.json exist. The caller must provide a fresh,
    validated target and owns cleanup of an invalid theme using its trusted
    module root. Generic downloader cleanup on transport failure is unchanged.
    """
    if not download_github_directory(download_url, target_dir, timeout):
        return False

    manifest_path = safe_child_file(target_dir, "manifest.json")
    theme_path = safe_child_file(target_dir, "theme.json")
    if not os.path.isfile(manifest_path) or not os.path.isfile(theme_path):
        log.error("Downloaded theme missing manifest.json or theme.json")
        return False

    return True


DEFAULT_THEME_ID = "docsight.theme_graphite"


def resolve_active_theme(active_id, theme_modules):
    """Return active theme data and ID, falling back to Graphite then first usable."""
    fallback = None
    for mod in theme_modules:
        if not mod.error and mod.theme_data:
            # Theme data is loaded even for disabled modules; enabled reflects
            # startup state, while the configured selection can change live.
            if mod.id == active_id:
                return mod.theme_data, mod.id
            if mod.enabled and (fallback is None or mod.id == DEFAULT_THEME_ID):
                fallback = mod
    return (fallback.theme_data, fallback.id) if fallback else (None, "")
