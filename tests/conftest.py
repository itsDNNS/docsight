"""Shared test fixtures and setup for DOCSight tests."""

import importlib
import json
import os

from app.builtin_modules import BUILTIN_MODULE_DIRS
from app.module_loader import module_static_endpoint, setup_module_static
from app.web import app


def _register_module_blueprints():
    """Register built-in module blueprints with the Flask app for testing.

    Module blueprints are normally registered by the module loader at runtime.
    In tests, we register built-in routes early so they're available before the
    first request and route-level coverage sees the same shipped module surface.
    """

    module_base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "modules")
    existing = {b.name for b in app.blueprints.values()}

    for module_dir in BUILTIN_MODULE_DIRS:
        manifest_path = os.path.join(module_base, module_dir, "manifest.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except OSError:
            continue
        if "routes" not in manifest.get("contributes", {}):
            continue

        try:
            routes_module = importlib.import_module(f"app.modules.{module_dir}.routes")
        except ImportError:
            continue
        blueprint = getattr(routes_module, "bp", None) or getattr(routes_module, "blueprint", None)
        if blueprint is not None and blueprint.name not in existing:
            app.register_blueprint(blueprint)
            existing.add(blueprint.name)


def _register_module_static_routes():
    """Give the shared test app the built-in static routes used in production."""

    module_base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "modules")
    existing = {rule.endpoint for rule in app.url_map.iter_rules()}
    for module_dir in BUILTIN_MODULE_DIRS:
        manifest_path = os.path.join(module_base, module_dir, "manifest.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except OSError:
            continue
        static_subdir = manifest.get("contributes", {}).get("static")
        if not static_subdir:
            continue
        module_id = manifest["id"]
        endpoint = module_static_endpoint(module_id)
        if endpoint not in existing:
            setup_module_static(
                app,
                module_id,
                os.path.join(module_base, module_dir),
                static_subdir,
            )
            existing.add(endpoint)


_register_module_blueprints()
_register_module_static_routes()
