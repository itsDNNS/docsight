"""Module manifest models and deterministic source discovery."""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, cast

from .builtin_modules import BUILTIN_MODULE_DIRS
from .manifest_contract import validate_manifest_contract
from .theme_registry import BUILTIN_THEMES
from .threshold_profiles import BUILTIN_THRESHOLD_PROFILES


log = logging.getLogger("docsis.modules")


class ManifestError(Exception):
    """Raised when a module manifest is invalid."""


class ModuleRegistryError(RuntimeError):
    """Raised when the application-owned module registry is inconsistent."""


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
    config_secrets: list[str] = field(default_factory=list)
    config_private: list[str] = field(default_factory=list)
    menu: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    error: str | None = None
    template_paths: dict[str, str] = field(default_factory=dict)
    collector_class: type | None = None
    publisher_class: type | None = None
    hints: dict[str, object] = field(default_factory=dict)
    thresholds_data: dict[str, object] | None = None
    theme_data: dict[str, object] | None = None
    has_css: bool = False
    has_js: bool = False


def validate_manifest(
    raw: dict[str, Any], module_path: str, *, builtin: bool | None = None
) -> ModuleInfo:
    """Validate a raw manifest dict and return stable module metadata."""
    if builtin is None:
        norm = os.path.normpath(module_path).replace("\\", "/")
        builtin = "/app/modules/" in norm
    errors = validate_manifest_contract(raw, builtin=builtin)
    if errors:
        raise ManifestError(errors[0])
    return ModuleInfo(
        id=raw["id"],
        name=raw["name"],
        description=raw["description"],
        version=raw["version"],
        author=raw["author"],
        min_app_version=raw["minAppVersion"],
        type=raw["type"],
        contributes=raw["contributes"],
        path=module_path,
        builtin=builtin,
        homepage=raw.get("homepage", ""),
        license=raw.get("license", ""),
        config=raw.get("config", {}),
        config_secrets=raw.get("config_secrets", []),
        config_private=raw.get("configPrivate", []),
        menu={**{"order": 999}, **raw.get("menu", {})},
        hints=raw.get("hints", {}),
    )


def _manifest(path: str, *, builtin: bool) -> ModuleInfo:
    try:
        with open(os.path.join(path, "manifest.json"), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        if builtin:
            raise ModuleRegistryError("Built-in module manifest could not be read") from exc
        raise ManifestError("Module manifest could not be read") from exc
    return validate_manifest(raw, path, builtin=builtin)


def discover_modules(
    search_paths: list[str] | None = None,
    disabled_ids: set[str] | None = None,
    known_ids: set[str] | None = None,
) -> list[ModuleInfo]:
    """Discover community modules in stable path and directory order."""
    modules: list[ModuleInfo] = []
    disabled = disabled_ids or set()
    seen = set(known_ids or set())
    for search_dir in search_paths or []:
        if not os.path.isdir(search_dir):
            continue
        for entry in sorted(os.listdir(search_dir)):
            mod_dir = os.path.join(search_dir, entry)
            if not os.path.isfile(os.path.join(mod_dir, "manifest.json")):
                continue
            try:
                info = _manifest(mod_dir, builtin=False)
            except ManifestError:
                log.warning("Skipping invalid community module manifest")
                continue
            if info.id in seen:
                log.warning("Skipping duplicate module '%s'; first source wins", info.id)
                continue
            info.enabled = info.id not in disabled
            seen.add(info.id)
            modules.append(info)
    return modules


def discover_builtin_modules(
    builtin_base_path: str,
    disabled_ids: set[str] | None = None,
    module_dirs: tuple[str, ...] | None = None,
) -> list[ModuleInfo]:
    """Resolve the statically ordered built-in manifest registry."""
    modules: list[ModuleInfo] = []
    for entry in module_dirs or BUILTIN_MODULE_DIRS:
        try:
            modules.append(_manifest(os.path.join(builtin_base_path, entry), builtin=True))
        except ManifestError as exc:
            raise ModuleRegistryError(f"Built-in module {entry} manifest is invalid") from exc
    return _finalize_builtins(modules, disabled_ids, "module")


def _finalize_builtins(
    modules: list[ModuleInfo], disabled_ids: set[str] | None, kind: str
) -> list[ModuleInfo]:
    seen, disabled = set(), disabled_ids or set()
    for info in modules:
        if info.id in seen:
            raise ModuleRegistryError(f"Duplicate built-in {kind} id {info.id}")
        info.enabled = info.id not in disabled
        seen.add(info.id)
    return modules


def discover_builtin_theme_modules(
    disabled_ids: set[str] | None = None,
    themes=None,
) -> list[ModuleInfo]:
    """Resolve application-owned themes from their static registry."""
    modules: list[ModuleInfo] = []
    for theme in BUILTIN_THEMES if themes is None else themes:
        modules.append(ModuleInfo(
            id=theme["id"], name=theme["name"], description=theme["description"],
            version=theme["version"], author=theme["author"],
            min_app_version=theme["minAppVersion"], type="theme",
            contributes={"theme": "builtin"}, path="", builtin=True,
            homepage=theme.get("homepage", ""), license=theme.get("license", ""),
            menu={"order": 999}, theme_data=theme["theme_data"],
        ))
    return _finalize_builtins(modules, disabled_ids, "theme")


def discover_builtin_threshold_modules(
    disabled_ids: set[str] | None = None,
    profiles=None,
) -> list[ModuleInfo]:
    """Resolve application-owned threshold profiles from their static registry."""
    modules: list[ModuleInfo] = []
    for profile in BUILTIN_THRESHOLD_PROFILES if profiles is None else profiles:
        modules.append(ModuleInfo(
            id=cast(str, profile["id"]), name=cast(str, profile["name"]),
            description=cast(str, profile["description"]),
            version=cast(str, profile["version"]), author=cast(str, profile["author"]),
            min_app_version=cast(str, profile["minAppVersion"]), type="analysis",
            contributes={"thresholds": "builtin"}, path="", builtin=True,
            menu={"order": 999},
            thresholds_data=deepcopy(cast(dict[str, object], profile["thresholds"])),
        ))
    return _finalize_builtins(modules, disabled_ids, "threshold profile")
