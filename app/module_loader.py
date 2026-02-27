"""Module loader: discovers, validates, and loads DOCSight modules."""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("docsis.modules")

VALID_TYPES = {"driver", "integration", "analysis", "theme"}
VALID_CONTRIBUTES = {"collector", "routes", "settings", "tab", "card", "i18n", "static"}
REQUIRED_FIELDS = {"id", "name", "description", "version", "author", "minAppVersion", "type", "contributes"}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.]+$")


class ManifestError(Exception):
    """Raised when a manifest.json is invalid."""


@dataclass
class ModuleInfo:
    """Validated module metadata from manifest.json."""
    id: str
    name: str
    description: str
    version: str
    author: str
    min_app_version: str
    type: str
    contributes: dict[str, str]
    path: str
    builtin: bool = False
    homepage: str = ""
    license: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    menu: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    error: str | None = None


def validate_manifest(raw: dict, module_path: str) -> ModuleInfo:
    """Validate a raw manifest dict and return a ModuleInfo.

    Raises ManifestError if the manifest is invalid.
    """
    # Required fields
    missing = REQUIRED_FIELDS - set(raw.keys())
    if missing:
        raise ManifestError(f"Missing required fields: {', '.join(sorted(missing))}")

    # ID format
    mod_id = raw["id"]
    if not isinstance(mod_id, str) or not ID_PATTERN.match(mod_id):
        raise ManifestError(
            f"Invalid id '{mod_id}': must be lowercase alphanumeric with dots/underscores, "
            f"starting with a letter (e.g. 'docsight.weather')"
        )

    # Type
    mod_type = raw["type"]
    if mod_type not in VALID_TYPES:
        raise ManifestError(f"Invalid type '{mod_type}': must be one of {sorted(VALID_TYPES)}")

    # Contributes keys
    contributes = raw.get("contributes", {})
    if not isinstance(contributes, dict):
        raise ManifestError("'contributes' must be a dict")
    unknown = set(contributes.keys()) - VALID_CONTRIBUTES
    if unknown:
        raise ManifestError(f"Unknown contributes keys: {', '.join(sorted(unknown))}")

    # Detect builtin
    norm = os.path.normpath(module_path).replace("\\", "/")
    builtin = "/app/modules/" in norm or "\\app\\modules\\" in os.path.normpath(module_path)

    return ModuleInfo(
        id=mod_id,
        name=raw["name"],
        description=raw["description"],
        version=raw["version"],
        author=raw["author"],
        min_app_version=raw["minAppVersion"],
        type=mod_type,
        contributes=contributes,
        path=module_path,
        builtin=builtin,
        homepage=raw.get("homepage", ""),
        license=raw.get("license", ""),
        config=raw.get("config", {}),
        menu=raw.get("menu", {}),
    )


def discover_modules(
    search_paths: list[str] | None = None,
    disabled_ids: set[str] | None = None,
) -> list[ModuleInfo]:
    """Scan directories for module manifest.json files.

    Args:
        search_paths: List of directories to scan. Each directory is expected
            to contain subdirectories, each with a manifest.json.
        disabled_ids: Set of module IDs that should be marked as disabled.

    Returns:
        List of validated ModuleInfo objects. Invalid manifests are logged
        and skipped -- they never raise exceptions.
    """
    if search_paths is None:
        search_paths = []
    if disabled_ids is None:
        disabled_ids = set()

    modules: list[ModuleInfo] = []
    seen_ids: set[str] = set()

    for search_dir in search_paths:
        if not os.path.isdir(search_dir):
            log.debug("Module search path does not exist: %s", search_dir)
            continue

        for entry in sorted(os.listdir(search_dir)):
            mod_dir = os.path.join(search_dir, entry)
            manifest_path = os.path.join(mod_dir, "manifest.json")

            if not os.path.isfile(manifest_path):
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Skipping %s: failed to read manifest: %s", mod_dir, e)
                continue

            try:
                info = validate_manifest(raw, mod_dir)
            except ManifestError as e:
                log.warning("Skipping %s: invalid manifest: %s", mod_dir, e)
                continue

            if info.id in seen_ids:
                log.warning(
                    "Skipping duplicate module '%s' at %s (already loaded from another path)",
                    info.id, mod_dir,
                )
                continue

            info.enabled = info.id not in disabled_ids
            seen_ids.add(info.id)
            modules.append(info)
            log.info(
                "Discovered module: %s v%s (%s)%s",
                info.id, info.version, "built-in" if info.builtin else "community",
                "" if info.enabled else " [disabled]",
            )

    return modules
