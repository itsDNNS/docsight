"""Resolve and preflight complete module contribution sets."""

import importlib
import importlib.util
import json
import logging
import os
import sys
from typing import Any

from flask import abort, send_file, url_for

from .builtin_modules import BUILTIN_PYTHON_CONTRIBUTIONS
from .module_registry import ManifestError, ModuleInfo
from .path_safety import safe_manifest_ref, safe_manifest_subpath
from .registration import (
    ModuleContribution,
    PlannedRule,
    RegistrationError,
    RegistrationPlan,
    apply_module_i18n,
    apply_plan,
    probe_blueprint,
)


log = logging.getLogger("docsis.modules")

_PROTECTED_ROUTES = {
    "/", "/login", "/logout", "/setup", "/settings", "/health", "/sw.js",
}
_PROTECTED_API_PREFIXES = (
    "/api/config", "/api/data", "/api/tokens", "/api/demo",
    "/api/poll", "/api/status", "/api/history", "/api/events", "/api/trends",
    "/api/export", "/api/correlation", "/api/modules/", "/api/themes/",
)
REQUIRED_THRESHOLD_SECTIONS = {"downstream_power", "upstream_power", "snr"}
REQUIRED_THEME_SECTIONS = {"dark", "light"}


def resolve_module_i18n(i18n_dir: str) -> dict[str, dict[str, Any]]:
    """Read module translations without mutating the process catalog."""
    if not os.path.isdir(i18n_dir):
        return {}
    catalogs: dict[str, dict[str, Any]] = {}
    for fname in sorted(os.listdir(i18n_dir)):
        if not fname.endswith(".json") or fname == "template.json":
            continue
        fpath = os.path.join(i18n_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            raise ManifestError("Invalid module translation catalog") from exc
        if not isinstance(data, dict):
            raise ManifestError("Module translation catalog must be an object")
        catalogs[fname[:-5]] = data
    return catalogs


def merge_module_i18n(module_id: str, i18n_dir: str) -> None:
    """Compatibility adapter that resolves then applies one i18n contribution."""
    apply_module_i18n(module_id, resolve_module_i18n(i18n_dir))


def _load_symbol(spec: str, module_id: str):
    """Import a trusted built-in Python contribution by module path."""
    if ":" not in spec:
        log.warning("Built-in module '%s': invalid Python contribution spec", module_id)
        return None
    module_name, attr_name = spec.rsplit(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception:
        log.error("Built-in module '%s': Python contribution import failed", module_id)
        return None
    value = getattr(module, attr_name, None)
    if value is None:
        log.warning("Built-in module '%s': Python contribution symbol not found", module_id)
    return value


def attach_builtin_python_contributions(mod: ModuleInfo) -> None:
    """Attach statically registered Python entry points for a built-in module."""
    specs = BUILTIN_PYTHON_CONTRIBUTIONS.get(mod.id)
    for key, attr_name in (
        ("collector", "collector_class"),
        ("publisher", "publisher_class"),
    ):
        if key not in mod.contributes or getattr(mod, attr_name) is not None:
            continue
        spec = getattr(specs, key, None) if specs else None
        if not spec:
            raise ManifestError(f"Built-in module '{mod.id}' missing static {key} registration")
        symbol = _load_symbol(spec, mod.id)
        if not isinstance(symbol, type):
            raise ManifestError(
                f"Built-in module '{mod.id}' failed to import static {key} registration"
            )
        setattr(mod, attr_name, symbol)


def resolve_module_routes(
    module_id: str,
    module_path: str,
    routes_file: str,
    *,
    builtin: bool = False,
) -> RegistrationPlan:
    """Import and preflight a module Blueprint without target mutation."""
    routes_path = safe_manifest_ref(module_path, routes_file)
    if not os.path.isfile(routes_path):
        raise ManifestError("Routes contribution file not found")
    dir_name = os.path.basename(module_path)
    if builtin:
        mod_name = f"app.modules.{dir_name}.{os.path.splitext(os.path.basename(routes_file))[0]}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:
            raise ManifestError("Routes contribution import failed") from exc
    else:
        mod_name = f"community_modules.{dir_name}.routes"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, routes_path)
            if spec is None or spec.loader is None:
                raise ManifestError("Routes contribution import failed")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise ManifestError("Routes contribution import failed") from exc
    blueprint = getattr(mod, "bp", None) or getattr(mod, "blueprint", None)
    if blueprint is None:
        raise ManifestError("Routes contribution does not export a Blueprint")
    planned = probe_blueprint(blueprint, source=f"module:{module_id}")
    if not builtin:
        blocked = []
        for rule in planned.rules:
            path = rule.rule
            if path in _PROTECTED_ROUTES:
                blocked.append(path)
                continue
            for prefix in _PROTECTED_API_PREFIXES:
                if path.startswith(prefix):
                    if prefix == "/api/modules/" and path.startswith(
                        f"/api/modules/{module_id}/"
                    ):
                        own_action = path.rstrip("/")
                        if own_action not in {
                            f"/api/modules/{module_id}/enable",
                            f"/api/modules/{module_id}/disable",
                        }:
                            continue
                    blocked.append(path)
                    break
        if blocked:
            raise RegistrationError(
                f"Module {module_id} has protected route conflicts: "
                + ", ".join(sorted(blocked))
            )
    return RegistrationPlan(blueprints=(planned,))


def load_module_routes(
    app,
    module_id: str,
    module_path: str,
    routes_file: str,
    *,
    builtin: bool = False,
) -> None:
    """Compatibility adapter for registering one independently tested module."""
    try:
        plan = resolve_module_routes(module_id, module_path, routes_file, builtin=builtin)
        apply_plan(app, plan)
    except RegistrationError:
        raise
    except (ManifestError, OSError):
        log.warning("Module '%s': routes contribution skipped", module_id)


def _load_module_class(module_id: str, module_path: str, spec: str, kind: str):
    """Load a contributed class from a module-owned Python file."""
    if ":" not in spec:
        log.warning("Module '%s': invalid %s contribution spec", module_id, kind)
        return None
    filename, class_name = spec.rsplit(":", 1)
    file_path = safe_manifest_ref(module_path, filename)
    if not os.path.isfile(file_path):
        log.warning("Module '%s': %s contribution file not found", module_id, kind)
        return None
    dir_name = os.path.basename(module_path)
    mod_name = f"app.modules.{dir_name}.{kind}"
    try:
        im_spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if im_spec is None or im_spec.loader is None:
            log.warning("Module '%s': %s contribution import unavailable", module_id, kind)
            return None
        mod = importlib.util.module_from_spec(im_spec)
        sys.modules[mod_name] = mod
        im_spec.loader.exec_module(mod)
    except Exception:
        log.error("Module '%s': %s contribution import failed", module_id, kind)
        return None
    cls = getattr(mod, class_name, None)
    if cls is None:
        log.warning("Module '%s': %s contribution class not found", module_id, kind)
        return None
    log.info("Module '%s': loaded %s contribution", module_id, kind)
    return cls


def load_module_collector(module_id: str, module_path: str, spec: str):
    """Load a Collector class, returning None on resolution failure."""
    return _load_module_class(module_id, module_path, spec, "collector")


def load_module_publisher(module_id: str, module_path: str, spec: str):
    """Load a Publisher class, returning None on resolution failure."""
    return _load_module_class(module_id, module_path, spec, "publisher")


def module_static_endpoint(module_id: str) -> str:
    """Return the stable Flask endpoint name for a module's static files."""
    return f"module_static_{module_id}"


def module_static_url(module_id: str, filename: str, **values: Any) -> str:
    """Build a module-static URL using the registered endpoint contract."""
    return url_for(module_static_endpoint(module_id), filename=filename, **values)


def plan_module_static(
    module_id: str, module_path: str, static_subdir: str
) -> RegistrationPlan:
    """Resolve a safe module-static mount without target mutation."""
    static_dir = safe_manifest_subpath(module_path, static_subdir.rstrip("/"))
    if not os.path.isdir(static_dir):
        return RegistrationPlan()
    static_root = os.path.realpath(static_dir)
    static_prefix = static_root + os.sep
    route = f"/modules/{module_id}/static/<path:filename>"

    def serve_static(filename, _root=static_root, _prefix=static_prefix):
        try:
            candidate = os.path.realpath(os.path.join(_root, filename))
        except (OSError, TypeError, ValueError):
            return abort(404)
        if candidate.startswith(_prefix):
            if not os.path.isfile(candidate):
                return abort(404)
            return send_file(candidate)
        return abort(404)

    endpoint = module_static_endpoint(module_id)
    return RegistrationPlan(rules=(PlannedRule(
        route, endpoint, ("GET",), f"module-static:{module_id}", serve_static,
    ),))


def setup_module_static(app, module_id: str, module_path: str, static_subdir: str) -> None:
    """Compatibility adapter for mounting one independently tested module."""
    apply_plan(app, plan_module_static(module_id, module_path, static_subdir))


def setup_module_templates(
    module_id: str, module_path: str, contributes: dict[str, str]
) -> dict[str, str]:
    """Resolve declared template files for Jinja includes."""
    resolved = {}
    for key in {"tab", "card", "settings"}:
        rel_path = contributes.get(key)
        if not rel_path:
            continue
        abs_path = safe_manifest_subpath(module_path, rel_path)
        if os.path.isfile(abs_path):
            resolved[key] = os.path.basename(abs_path)
            log.debug("Module '%s': resolved %s template contribution", module_id, key)
        else:
            log.warning("Module '%s': %s template contribution not found", module_id, key)
    return resolved


def validate_thresholds(data: dict[str, object]) -> None:
    """Validate a threshold contribution."""
    missing = REQUIRED_THRESHOLD_SECTIONS - set(data.keys())
    if missing:
        raise ManifestError(f"Missing required threshold sections: {', '.join(sorted(missing))}")
    for section in REQUIRED_THRESHOLD_SECTIONS:
        block = data[section]
        if not isinstance(block, dict):
            raise ManifestError(f"Threshold section '{section}' must be a dict")
        if "_default" not in block:
            raise ManifestError(f"Threshold section '{section}' missing '_default' key")


def validate_theme(data: dict[str, object]) -> None:
    """Validate a theme contribution."""
    if not isinstance(data, dict):
        raise ManifestError("Theme contribution must be an object")
    missing = REQUIRED_THEME_SECTIONS - set(data.keys())
    if missing:
        raise ManifestError(f"Missing required theme sections: {', '.join(sorted(missing))}")
    for section in REQUIRED_THEME_SECTIONS:
        block = data[section]
        if not isinstance(block, dict):
            raise ManifestError(f"Theme section '{section}' must be a dict")
        if not block:
            raise ManifestError(f"Theme section '{section}' is empty")
        for key, value in block.items():
            if not isinstance(value, str):
                raise ManifestError(
                    f"Theme property '{key}' in '{section}' must be a string, "
                    f"got {type(value).__name__}"
                )


def _read_json_contribution(
    module_path: str, reference: str, kind: str, validator
) -> dict[str, object]:
    try:
        path = safe_manifest_ref(module_path, reference)
    except ValueError as exc:
        raise ManifestError(f"{kind} contribution reference is unsafe") from exc
    if not os.path.isfile(path):
        raise ManifestError(f"{kind} contribution file not found")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        validator(data)
        return data
    except (json.JSONDecodeError, OSError, ManifestError) as exc:
        raise ManifestError(f"{kind} contribution is invalid") from exc


def _redacted_resolution(kind: str, resolver):
    try:
        return resolver()
    except ValueError as exc:
        raise ManifestError(f"{kind} contribution reference is unsafe") from exc


def resolve_module_contribution(
    mod: ModuleInfo,
) -> tuple[ModuleContribution, RegistrationPlan]:
    """Resolve and validate one complete contribution set without target mutation."""
    contributes = mod.contributes
    http = RegistrationPlan()
    collector_class = publisher_class = None
    if mod.builtin:
        attach_builtin_python_contributions(mod)
        collector_class, publisher_class = mod.collector_class, mod.publisher_class
    static_subdir = contributes.get("static", "static/").rstrip("/")
    static_dir = _redacted_resolution(
        "static", lambda: safe_manifest_subpath(mod.path, static_subdir)
    )
    if "i18n" in contributes:
        i18n_dir = _redacted_resolution(
            "i18n",
            lambda: safe_manifest_subpath(mod.path, contributes["i18n"].rstrip("/")),
        )
        if not os.path.isdir(i18n_dir):
            raise ManifestError("i18n contribution directory not found")
        i18n_catalogs = resolve_module_i18n(i18n_dir)
    else:
        i18n_catalogs = {}
    if "routes" in contributes:
        http = _redacted_resolution(
            "routes",
            lambda: resolve_module_routes(
                mod.id, mod.path, contributes["routes"], builtin=mod.builtin
            ),
        )
    if "static" in contributes and not os.path.isdir(static_dir):
        raise ManifestError("static contribution directory not found")
    if os.path.isdir(static_dir):
        http = http.combined(plan_module_static(mod.id, mod.path, static_subdir))
        has_css = os.path.isfile(os.path.join(static_dir, "style.css"))
        has_js = os.path.isfile(os.path.join(static_dir, "main.js"))
    else:
        has_css = has_js = False
    template_paths = _redacted_resolution(
        "template", lambda: setup_module_templates(mod.id, mod.path, contributes)
    )
    declared_templates = {
        key for key in ("tab", "card", "settings") if key in contributes
    }
    if declared_templates != set(template_paths):
        missing_kind = sorted(declared_templates - set(template_paths))[0]
        raise ManifestError(f"{missing_kind} template contribution file not found")
    if "collector" in contributes and not mod.builtin:
        collector_class = _redacted_resolution(
            "collector",
            lambda: load_module_collector(
                mod.id, mod.path, contributes["collector"]
            ),
        )
        if not isinstance(collector_class, type):
            raise ManifestError("collector contribution could not be resolved")
    if "publisher" in contributes and not mod.builtin:
        publisher_class = _redacted_resolution(
            "publisher",
            lambda: load_module_publisher(
                mod.id, mod.path, contributes["publisher"]
            ),
        )
        if not isinstance(publisher_class, type):
            raise ManifestError("publisher contribution could not be resolved")
    if "thresholds" in contributes:
        thresholds_data = mod.thresholds_data
        if thresholds_data is None:
            thresholds_data = _read_json_contribution(
                mod.path, contributes["thresholds"], "thresholds", validate_thresholds
            )
        else:
            validate_thresholds(thresholds_data)
    else:
        thresholds_data = None
    if "theme" in contributes:
        theme_data = mod.theme_data
        if theme_data is None:
            theme_data = _read_json_contribution(
                mod.path, contributes["theme"], "theme", validate_theme
            )
        else:
            validate_theme(theme_data)
    else:
        theme_data = None
    template_dir = os.path.join(mod.path, "templates")
    contribution = ModuleContribution(
        module_id=mod.id,
        source=("builtin:" if mod.builtin else "community:") + mod.id,
        version=mod.version,
        builtin=mod.builtin,
        info=mod,
        config=tuple(sorted(mod.config.items())),
        secret_keys=tuple(sorted(mod.config_secrets)),
        private_keys=tuple(sorted(mod.config_private if mod.builtin else ())),
        i18n_catalogs=tuple(
            (lang, tuple(sorted(strings.items())))
            for lang, strings in sorted(i18n_catalogs.items())
        ),
        template_paths=tuple(sorted(template_paths.items())),
        template_dir=template_dir if os.path.isdir(template_dir) else None,
        collector_class=collector_class,
        publisher_class=publisher_class,
        thresholds_data=thresholds_data,
        theme_data=theme_data,
        has_css=has_css,
        has_js=has_js,
    )
    return contribution, http
