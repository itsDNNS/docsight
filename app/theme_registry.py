"""Theme registry client for fetching community themes from GitHub."""

import json
import logging
import os
import shutil
import urllib.request

log = logging.getLogger("docsis.themes")

REQUIRED_ENTRY_FIELDS = {"id", "name", "version", "download_url", "min_app_version"}


def validate_registry_entry(entry: dict) -> bool:
    """Check if a registry entry has all required fields."""
    return REQUIRED_ENTRY_FIELDS.issubset(entry.keys())


def fetch_registry(registry_url: str, timeout: int = 10) -> list[dict]:
    """Fetch the theme registry index and return list of valid theme entries."""
    try:
        with urllib.request.urlopen(registry_url, timeout=timeout) as resp:
            data = json.loads(resp.read())
        themes = data.get("themes", [])
        return [t for t in themes if validate_registry_entry(t)]
    except Exception as e:
        log.warning("Failed to fetch theme registry from %s: %s", registry_url, e)
        return []


def download_theme(download_url: str, target_dir: str, timeout: int = 30) -> bool:
    """Download a theme module from the registry into target_dir.

    Expects download_url to point to a GitHub Contents API directory listing.
    """
    try:
        os.makedirs(target_dir, exist_ok=True)

        with urllib.request.urlopen(download_url, timeout=timeout) as resp:
            files = json.loads(resp.read())

        for entry in files:
            if entry.get("type") != "file":
                continue
            name = entry["name"]
            file_url = entry.get("download_url")
            if not file_url:
                continue

            target_path = os.path.join(target_dir, name)
            with urllib.request.urlopen(file_url, timeout=timeout) as resp:
                with open(target_path, "wb") as f:
                    f.write(resp.read())
            log.info("Downloaded %s -> %s", name, target_path)

        # Handle static/ subdirectory
        for entry in files:
            if entry.get("type") == "dir" and entry["name"] == "static":
                static_dir = os.path.join(target_dir, "static")
                os.makedirs(static_dir, exist_ok=True)
                with urllib.request.urlopen(entry["url"], timeout=timeout) as resp:
                    static_files = json.loads(resp.read())
                for sf in static_files:
                    if sf.get("type") != "file" or not sf.get("download_url"):
                        continue
                    with urllib.request.urlopen(sf["download_url"], timeout=timeout) as resp:
                        with open(os.path.join(static_dir, sf["name"]), "wb") as f:
                            f.write(resp.read())

        manifest_path = os.path.join(target_dir, "manifest.json")
        theme_path = os.path.join(target_dir, "theme.json")
        if not os.path.isfile(manifest_path) or not os.path.isfile(theme_path):
            log.error("Downloaded theme missing manifest.json or theme.json")
            shutil.rmtree(target_dir, ignore_errors=True)
            return False

        return True
    except Exception as e:
        log.error("Failed to download theme from %s: %s", download_url, e)
        shutil.rmtree(target_dir, ignore_errors=True)
        return False
