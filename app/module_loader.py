"""Module loader: discovers, validates, and loads DOCSight modules."""

import importlib.util
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from flask import send_from_directory

log = logging.getLogger("docsis.modules")

VALID_TYPES = {"driver", "integration", "analysis", "theme"}
VALID_CONTRIBUTES = {"collector", "routes", "settings", "tab", "card", "i18n", "static", "publisher", "thresholds"}
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
    template_paths: dict[str, str] = field(default_factory=dict)
    collector_class: type | None = None
    publisher_class: type | None = None
    thresholds_data: dict | None = None
    has_css: bool = False
    has_js: bool = False


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


def register_module_config(config_defaults: dict) -> None:
    """Register a module's config defaults into the global config system.

    - Adds defaults to config.DEFAULTS (without overwriting existing keys)
    - Auto-detects bool/int keys and adds them to BOOL_KEYS/INT_KEYS
    """
    from app import config as cfg

    for key, value in config_defaults.items():
        if key in cfg.DEFAULTS:
            log.debug("Config key '%s' already exists in core, skipping", key)
            continue
        cfg.DEFAULTS[key] = value
        if isinstance(value, bool):
            cfg.BOOL_KEYS.add(key)
        elif isinstance(value, int):
            cfg.INT_KEYS.add(key)


def merge_module_i18n(module_id: str, i18n_dir: str) -> None:
    """Merge a module's i18n JSON files into the global translation system.

    Keys are namespaced under the module ID:
        module i18n key "greeting" -> global key "module_id.greeting"
    """
    if not os.path.isdir(i18n_dir):
        log.debug("No i18n directory for module '%s': %s", module_id, i18n_dir)
        return

    from app.i18n import _TRANSLATIONS

    for fname in sorted(os.listdir(i18n_dir)):
        if not fname.endswith(".json"):
            continue
        lang = fname[:-5]  # "en.json" -> "en"
        fpath = os.path.join(i18n_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load i18n file %s: %s", fpath, e)
            continue

        if lang not in _TRANSLATIONS:
            _TRANSLATIONS[lang] = {}

        for key, value in data.items():
            if key.startswith("_"):
                continue  # skip metadata keys like _meta
            _TRANSLATIONS[lang][f"{module_id}.{key}"] = value
            # Also add un-namespaced key for backward compat with JS code
            if key not in _TRANSLATIONS[lang]:
                _TRANSLATIONS[lang][key] = value

        log.debug("Merged %d i18n keys for module '%s' lang '%s'", len(data), module_id, lang)


def load_module_routes(app, module_id: str, module_path: str, routes_file: str) -> None:
    """Dynamically load a Flask Blueprint from a module's routes file.

    The routes file must export a variable named 'bp' or 'blueprint'
    that is a Flask Blueprint instance.
    """
    routes_path = os.path.join(module_path, routes_file)
    if not os.path.isfile(routes_path):
        log.warning("Module '%s': routes file not found: %s", module_id, routes_path)
        return

    # Dynamic import using importlib
    dir_name = os.path.basename(module_path)
    mod_name = f"app.modules.{dir_name}.routes"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, routes_path)
        if spec is None or spec.loader is None:
            log.warning("Module '%s': could not create import spec for %s", module_id, routes_path)
            return
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        log.error("Module '%s': failed to import routes: %s", module_id, e)
        return

    # Find Blueprint
    blueprint = getattr(mod, "bp", None) or getattr(mod, "blueprint", None)
    if blueprint is None:
        log.warning("Module '%s': routes.py does not export 'bp' or 'blueprint'", module_id)
        return

    try:
        app.register_blueprint(blueprint)
        log.info("Module '%s': registered routes blueprint", module_id)
    except Exception as e:
        log.error("Module '%s': failed to register blueprint: %s", module_id, e)


def load_module_collector(module_id: str, module_path: str, spec: str):
    """Load a Collector class from a module file.

    Args:
        module_id: The module's unique identifier.
        module_path: Filesystem path to the module directory.
        spec: "filename.py:ClassName" format (e.g. "collector.py:WeatherCollector")

    Returns:
        The Collector subclass, or None if loading failed.
    """
    if ":" not in spec:
        log.warning("Module '%s': collector spec must be 'file.py:ClassName', got '%s'", module_id, spec)
        return None

    filename, class_name = spec.rsplit(":", 1)
    file_path = os.path.join(module_path, filename)

    if not os.path.isfile(file_path):
        log.warning("Module '%s': collector file not found: %s", module_id, file_path)
        return None

    dir_name = os.path.basename(module_path)
    mod_name = f"app.modules.{dir_name}.collector"
    try:
        im_spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if im_spec is None or im_spec.loader is None:
            log.warning("Module '%s': could not create import spec for %s", module_id, file_path)
            return None
        mod = importlib.util.module_from_spec(im_spec)
        sys.modules[mod_name] = mod
        im_spec.loader.exec_module(mod)
    except Exception as e:
        log.error("Module '%s': failed to import collector: %s", module_id, e)
        return None

    cls = getattr(mod, class_name, None)
    if cls is None:
        log.warning("Module '%s': class '%s' not found in %s", module_id, class_name, file_path)
        return None

    log.info("Module '%s': loaded collector class '%s'", module_id, class_name)
    return cls


def load_module_publisher(module_id: str, module_path: str, spec: str):
    """Load a Publisher class from a module file.

    Args:
        module_id: The module's unique identifier.
        module_path: Filesystem path to the module directory.
        spec: "filename.py:ClassName" format (e.g. "publisher.py:MQTTPublisher")

    Returns:
        The Publisher class, or None if loading failed.
    """
    if ":" not in spec:
        log.warning("Module '%s': publisher spec must be 'file.py:ClassName', got '%s'", module_id, spec)
        return None

    filename, class_name = spec.rsplit(":", 1)
    file_path = os.path.join(module_path, filename)

    if not os.path.isfile(file_path):
        log.warning("Module '%s': publisher file not found: %s", module_id, file_path)
        return None

    dir_name = os.path.basename(module_path)
    mod_name = f"app.modules.{dir_name}.publisher"
    try:
        im_spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if im_spec is None or im_spec.loader is None:
            log.warning("Module '%s': could not create import spec for %s", module_id, file_path)
            return None
        mod = importlib.util.module_from_spec(im_spec)
        sys.modules[mod_name] = mod
        im_spec.loader.exec_module(mod)
    except Exception as e:
        log.error("Module '%s': failed to import publisher: %s", module_id, e)
        return None

    cls = getattr(mod, class_name, None)
    if cls is None:
        log.warning("Module '%s': class '%s' not found in %s", module_id, class_name, file_path)
        return None

    log.info("Module '%s': loaded publisher class '%s'", module_id, class_name)
    return cls


def setup_module_static(app, module_id: str, module_path: str, static_subdir: str) -> None:
    """Mount a module's static directory at /modules/<id>/static/."""
    static_dir = os.path.join(module_path, static_subdir.rstrip("/"))
    if not os.path.isdir(static_dir):
        log.debug("Module '%s': no static directory at %s", module_id, static_dir)
        return

    route = f"/modules/{module_id}/static/<path:filename>"

    def serve_static(filename, _dir=static_dir):
        return send_from_directory(_dir, filename)

    # Use a unique endpoint name per module
    endpoint = f"module_static_{module_id.replace('.', '_')}"
    app.add_url_rule(route, endpoint=endpoint, view_func=serve_static)
    log.info("Module '%s': serving static files at /modules/%s/static/", module_id, module_id)


def setup_module_templates(
    module_id: str, module_path: str, contributes: dict
) -> dict[str, str]:
    """Resolve module template paths to absolute file paths.

    Args:
        contributes: Dict with keys like 'tab', 'card', 'settings' mapping to
            relative template paths within the module directory.

    Returns:
        Dict of template type -> absolute file path (only for files that exist).
    """
    template_keys = {"tab", "card", "settings"}
    resolved = {}

    for key in template_keys:
        rel_path = contributes.get(key)
        if not rel_path:
            continue
        abs_path = os.path.join(module_path, rel_path)
        if os.path.isfile(abs_path):
            # Store just the filename for Jinja2 include (ChoiceLoader resolves it)
            resolved[key] = os.path.basename(abs_path)
            log.debug("Module '%s': template '%s' -> %s", module_id, key, abs_path)
        else:
            log.warning("Module '%s': template '%s' not found: %s", module_id, key, abs_path)

    return resolved


REQUIRED_THRESHOLD_SECTIONS = {"downstream_power", "upstream_power", "snr"}


def validate_thresholds(data: dict) -> None:
    """Validate a threshold JSON structure.

    Raises ManifestError if required sections or keys are missing.
    """
    missing = REQUIRED_THRESHOLD_SECTIONS - set(data.keys())
    if missing:
        raise ManifestError(f"Missing required threshold sections: {', '.join(sorted(missing))}")

    for section in REQUIRED_THRESHOLD_SECTIONS:
        block = data[section]
        if not isinstance(block, dict):
            raise ManifestError(f"Threshold section '{section}' must be a dict")
        if "_default" not in block:
            raise ManifestError(f"Threshold section '{section}' missing '_default' key")


class ModuleLoader:
    """Orchestrates module discovery, validation, and loading.

    Usage:
        loader = ModuleLoader(app, search_paths=[...])
        modules = loader.load_all()
    """

    def __init__(
        self,
        app,
        search_paths: list[str] | None = None,
        disabled_ids: set[str] | None = None,
    ):
        self._app = app
        self._search_paths = search_paths or []
        self._disabled_ids = disabled_ids or set()
        self._modules: list[ModuleInfo] = []

    def load_all(self) -> list[ModuleInfo]:
        """Discover and load all modules.

        Returns list of all discovered ModuleInfo (including disabled).
        """
        self._modules = discover_modules(
            search_paths=self._search_paths,
            disabled_ids=self._disabled_ids,
        )

        for mod in self._modules:
            if not mod.enabled:
                log.info("Module '%s' is disabled, skipping load", mod.id)
                continue

            try:
                self._load_module(mod)
            except Exception as e:
                mod.error = str(e)
                log.error("Module '%s' failed to load: %s", mod.id, e)

        enabled = [m for m in self._modules if m.enabled and not m.error]
        log.info(
            "Module loading complete: %d discovered, %d enabled, %d failed",
            len(self._modules),
            len(enabled),
            len([m for m in self._modules if m.error]),
        )

        return self._modules

    def _load_module(self, mod: ModuleInfo) -> None:
        """Load a single module's contributions."""
        c = mod.contributes

        # Config defaults
        if mod.config:
            register_module_config(mod.config)

        # i18n
        if "i18n" in c:
            i18n_dir = os.path.join(mod.path, c["i18n"].rstrip("/"))
            merge_module_i18n(mod.id, i18n_dir)

        # Routes (Blueprint)
        if "routes" in c:
            load_module_routes(self._app, mod.id, mod.path, c["routes"])

        # Static files
        if "static" in c:
            setup_module_static(self._app, mod.id, mod.path, c["static"])

        # Template paths
        mod.template_paths = setup_module_templates(mod.id, mod.path, c)

        # Collector (class loaded but not instantiated -- collector discovery handles that)
        if "collector" in c:
            mod.collector_class = load_module_collector(mod.id, mod.path, c["collector"])

        # Publisher (class loaded but not instantiated -- main.py handles that)
        if "publisher" in c:
            mod.publisher_class = load_module_publisher(mod.id, mod.path, c["publisher"])

        # Thresholds
        if "thresholds" in c:
            thresholds_path = os.path.join(mod.path, c["thresholds"])
            if not os.path.isfile(thresholds_path):
                raise ManifestError(f"Thresholds file not found: {c['thresholds']}")
            with open(thresholds_path, "r", encoding="utf-8") as f:
                tdata = json.load(f)
            validate_thresholds(tdata)
            mod.thresholds_data = tdata
            from app import analyzer
            analyzer.set_thresholds(tdata)
            log.info("Module '%s': loaded threshold profile", mod.id)

        # Convention-based asset detection
        static_subdir = c.get("static", "static/").rstrip("/")
        static_dir = os.path.join(mod.path, static_subdir)
        if os.path.isdir(static_dir):
            mod.has_css = os.path.isfile(os.path.join(static_dir, "style.css"))
            mod.has_js = os.path.isfile(os.path.join(static_dir, "main.js"))

    def get_modules(self) -> list[ModuleInfo]:
        """Return all discovered modules (enabled and disabled)."""
        return list(self._modules)

    def get_enabled_modules(self) -> list[ModuleInfo]:
        """Return only enabled modules without errors."""
        return [m for m in self._modules if m.enabled and not m.error]

    def get_threshold_modules(self) -> list[ModuleInfo]:
        """Return all modules that contribute thresholds."""
        return [m for m in self._modules if "thresholds" in m.contributes]
