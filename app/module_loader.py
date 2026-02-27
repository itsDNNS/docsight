"""Module loader: discovers, validates, and loads DOCSight modules."""

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
