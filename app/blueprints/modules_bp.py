"""Module management API endpoints."""

import logging

from flask import Blueprint, jsonify

from app.web import get_module_loader, require_auth

log = logging.getLogger("docsis.modules")

modules_bp = Blueprint("modules_bp", __name__)


def _serialize_module(mod):
    """Convert ModuleInfo to JSON-safe dict."""
    return {
        "id": mod.id,
        "name": mod.name,
        "description": mod.description,
        "version": mod.version,
        "author": mod.author,
        "type": mod.type,
        "enabled": mod.enabled,
        "builtin": mod.builtin,
        "error": mod.error,
        "homepage": mod.homepage,
    }


@modules_bp.route("/api/modules")
@require_auth
def api_modules_list():
    """List all discovered modules with metadata and status."""
    loader = get_module_loader()
    if not loader:
        return jsonify([])
    modules = loader.get_modules()
    return jsonify([_serialize_module(m) for m in modules])
