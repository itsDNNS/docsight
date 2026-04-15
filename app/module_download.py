"""Generic module downloader for fetching community modules from GitHub."""

import json
import logging
import os
import shutil
import urllib.request
from urllib.parse import urlparse

log = logging.getLogger("docsis.module_download")

REQUIRED_ENTRY_FIELDS = {"id", "name", "version", "download_url", "min_app_version"}

TRUSTED_HOSTS = {
    "raw.githubusercontent.com",
    "api.github.com",
    "github.com",
}


def is_trusted_url(url: str) -> bool:
    """Check that a URL uses HTTPS and points to a trusted GitHub host."""
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in TRUSTED_HOSTS
    except Exception:
        return False


def validate_registry_entry(entry: dict[str, str]) -> bool:
    """Check if a registry entry has all required fields."""
    return REQUIRED_ENTRY_FIELDS.issubset(entry.keys())


def fetch_registry(registry_url: str, key: str = "modules", timeout: int = 10) -> list[dict[str, str]]:
    """Fetch a registry index and return list of valid entries.

    Args:
        registry_url: URL to the registry JSON file
        key: top-level key in the JSON (e.g., "modules" or "themes")
        timeout: request timeout in seconds
    """
    if not is_trusted_url(registry_url):
        log.error("Refusing registry fetch: untrusted URL %s", registry_url)
        return []
    try:
        with urllib.request.urlopen(registry_url, timeout=timeout) as resp:
            data = json.loads(resp.read())
        entries = data.get(key, [])
        return [e for e in entries if validate_registry_entry(e)]
    except Exception as e:
        log.warning("Failed to fetch registry from %s: %s", registry_url, e)
        return []


def download_github_directory(download_url: str, target_dir: str, timeout: int = 30) -> bool:
    """Download a directory recursively from the GitHub Contents API.

    Fully recursive traversal of any directory structure. All URLs are
    validated against TRUSTED_HOSTS to prevent SSRF.

    Args:
        download_url: GitHub Contents API URL for the directory
        target_dir: local directory to download into
        timeout: request timeout in seconds

    Returns:
        True on success, False on failure (target_dir is cleaned up on failure)
    """
    if not is_trusted_url(download_url):
        log.error("Refusing download: untrusted URL %s", download_url)
        return False

    try:
        os.makedirs(target_dir, exist_ok=True)

        with urllib.request.urlopen(download_url, timeout=timeout) as resp:
            entries = json.loads(resp.read())

        for entry in entries:
            name = os.path.basename(entry.get("name", ""))
            entry_type = entry.get("type", "")

            if not name or name in (".", ".."):
                log.warning("Skipping suspicious entry name: %r", entry.get("name"))
                continue

            candidate = os.path.realpath(os.path.join(target_dir, name))
            if not candidate.startswith(os.path.realpath(target_dir) + os.sep):
                log.warning("Path traversal blocked: %r", entry.get("name"))
                continue

            if entry_type == "file":
                file_url = entry.get("download_url")
                if not file_url or not is_trusted_url(file_url):
                    log.warning("Skipping untrusted file URL: %s", file_url)
                    continue
                with urllib.request.urlopen(file_url, timeout=timeout) as resp:
                    with open(candidate, "wb") as f:
                        f.write(resp.read())

            elif entry_type == "dir":
                subdir_url = entry.get("url", "")
                if not is_trusted_url(subdir_url):
                    log.warning("Skipping untrusted dir URL: %s", subdir_url)
                    continue
                if not download_github_directory(subdir_url, candidate, timeout):
                    shutil.rmtree(target_dir, ignore_errors=True)
                    return False

        return True
    except Exception as e:
        log.error("Failed to download from %s: %s", download_url, e)
        shutil.rmtree(target_dir, ignore_errors=True)
        return False
