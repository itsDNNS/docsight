"""Shared test fixtures and setup for DOCSight tests."""

import importlib
import json
import os

from app.builtin_modules import BUILTIN_MODULE_DIRS
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


_register_module_blueprints()
