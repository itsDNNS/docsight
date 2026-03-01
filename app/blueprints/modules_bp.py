"""Module management API endpoints."""

import logging
import os

from flask import Blueprint, jsonify, request

from app.web import get_config_manager, get_module_loader, require_auth

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
        "is_threshold": "thresholds" in mod.contributes,
        "is_theme": mod.type == "theme",
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


@modules_bp.route("/api/modules/<module_id>/enable", methods=["POST"])
@require_auth
def api_module_enable(module_id):
    """Enable a disabled module (persisted, requires restart)."""
    loader = get_module_loader()
    if not loader:
        return jsonify({"success": False, "error": "Module system not initialized"}), 500

    module = next((m for m in loader.get_modules() if m.id == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Module '{module_id}' not found"}), 404

    config_mgr = get_config_manager()
    if not config_mgr:
        return jsonify({"success": False, "error": "Config not initialized"}), 500

    disabled_raw = config_mgr.get("disabled_modules", "")
    disabled_set = {s.strip() for s in disabled_raw.split(",") if s.strip()}

    # Mutual exclusion: if enabling a threshold module, disable the currently active one
    if "thresholds" in module.contributes:
        for m in loader.get_threshold_modules():
            if m.id != module_id and m.id not in disabled_set:
                disabled_set.add(m.id)
                log.info("Auto-disabled threshold module '%s' (mutual exclusion)", m.id)

    # Mutual exclusion: if enabling a theme, disable others and set active_theme
    if module.type == "theme":
        for m in loader.get_theme_modules():
            if m.id != module_id and m.id not in disabled_set:
                disabled_set.add(m.id)
                log.info("Auto-disabled theme module '%s' (mutual exclusion)", m.id)

    disabled_set.discard(module_id)
    updates = {"disabled_modules": ",".join(sorted(disabled_set))}
    if module.type == "theme":
        updates["active_theme"] = module_id
    config_mgr.save(updates)

    log.info("Module '%s' enabled (restart required)", module_id)
    return jsonify({"success": True, "restart_required": True})


@modules_bp.route("/api/modules/<module_id>/disable", methods=["POST"])
@require_auth
def api_module_disable(module_id):
    """Disable a module (persisted, requires restart)."""
    loader = get_module_loader()
    if not loader:
        return jsonify({"success": False, "error": "Module system not initialized"}), 500

    module = next((m for m in loader.get_modules() if m.id == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Module '{module_id}' not found"}), 404

    config_mgr = get_config_manager()
    if not config_mgr:
        return jsonify({"success": False, "error": "Config not initialized"}), 500

    # Block disabling the last active theme module
    if module.type == "theme":
        disabled_raw = config_mgr.get("disabled_modules", "")
        disabled_set_check = {s.strip() for s in disabled_raw.split(",") if s.strip()}
        active_themes = [
            m for m in loader.get_theme_modules()
            if m.id not in disabled_set_check and m.id != module_id
        ]
        if not active_themes:
            return jsonify({
                "success": False,
                "error": "Cannot disable the only active theme. Enable a different theme first.",
            }), 409

    # Block disabling the last active threshold module
    if "thresholds" in module.contributes:
        disabled_raw = config_mgr.get("disabled_modules", "")
        disabled_set = {s.strip() for s in disabled_raw.split(",") if s.strip()}
        active_thresholds = [
            m for m in loader.get_threshold_modules()
            if m.id not in disabled_set and m.id != module_id
        ]
        if not active_thresholds:
            return jsonify({
                "success": False,
                "error": "Cannot disable the only active threshold profile. Enable a different one first.",
            }), 409

    disabled_raw = config_mgr.get("disabled_modules", "")
    disabled_set = {s.strip() for s in disabled_raw.split(",") if s.strip()}
    disabled_set.add(module_id)
    config_mgr.save({"disabled_modules": ",".join(sorted(disabled_set))})

    log.info("Module '%s' disabled (restart required)", module_id)
    return jsonify({"success": True, "restart_required": True})


@modules_bp.route("/api/themes")
@require_auth
def api_themes_list():
    """List all theme modules with their CSS variable data."""
    loader = get_module_loader()
    if not loader:
        return jsonify([])
    themes = loader.get_theme_modules()
    result = []
    for m in themes:
        d = _serialize_module(m)
        d["theme_data"] = m.theme_data
        result.append(d)
    return jsonify(result)


@modules_bp.route("/api/themes/registry")
@require_auth
def api_themes_registry():
    """Fetch available themes from the remote registry."""
    config_mgr = get_config_manager()
    if not config_mgr:
        return jsonify([])

    registry_url = config_mgr.get(
        "theme_registry_url",
        "https://raw.githubusercontent.com/itsDNNS/docsight-themes/main/registry.json",
    )

    from app.theme_registry import fetch_registry
    themes = fetch_registry(registry_url)

    loader = get_module_loader()
    installed_ids = set()
    if loader:
        installed_ids = {m.id for m in loader.get_theme_modules()}
    available = [t for t in themes if t["id"] not in installed_ids]

    return jsonify(available)


@modules_bp.route("/api/themes/install", methods=["POST"])
@require_auth
def api_themes_install():
    """Install a theme from the registry."""
    data = request.get_json()
    if not data or "download_url" not in data or "id" not in data:
        return jsonify({"success": False, "error": "Missing download_url or id"}), 400

    theme_dir = os.path.join("/modules", data["id"].replace(".", "_"))

    from app.theme_registry import download_theme
    if download_theme(data["download_url"], theme_dir):
        return jsonify({"success": True, "restart_required": True})
    else:
        return jsonify({"success": False, "error": "Download failed"}), 500
