"""Module management API endpoints."""

import json
import logging
import os
import shutil

from flask import Blueprint, jsonify, request

from app.module_download import download_github_directory, fetch_registry as fetch_module_registry
from app.module_loader import ID_PATTERN, validate_manifest
from app.theme_registry import download_theme, fetch_registry as fetch_theme_registry
from app.web import get_config_manager, get_module_loader, require_auth

log = logging.getLogger("docsis.modules")

modules_bp = Blueprint("modules_bp", __name__)


def _safe_child_path(base_dir: str, child_name: str) -> str:
    """Resolve *child_name* inside *base_dir* safely.

    Validates *child_name* against ``ID_PATTERN`` (lowercase alphanum,
    dots, underscores) and ensures the resolved path is actually inside
    *base_dir* via ``os.path.commonpath``.

    Returns the resolved absolute path on success.
    Raises ``ValueError`` for any invalid or escaping name.
    """
    if not isinstance(child_name, str) or not ID_PATTERN.match(child_name):
        raise ValueError(f"Invalid ID: {child_name!r}")

    candidate = os.path.join(base_dir, child_name)
    real_base = os.path.realpath(base_dir)
    real_candidate = os.path.realpath(candidate)

    if os.path.commonpath([real_base, real_candidate]) != real_base:
        raise ValueError(f"Path escapes base directory: {child_name!r}")

    return real_candidate


_ALLOWED_CHILD_FILES = frozenset({"manifest.json"})


def _safe_child_file(validated_dir: str, filename: str) -> str:
    """Return the path to a known child file inside a validated directory.

    *validated_dir* must already be the output of :func:`_safe_child_path`.
    *filename* must be in the ``_ALLOWED_CHILD_FILES`` allowlist.

    Raises ``ValueError`` if *filename* is not allowed or the resolved
    path escapes *validated_dir*.
    """
    if filename not in _ALLOWED_CHILD_FILES:
        raise ValueError(f"Filename not in allowlist: {filename!r}")

    candidate = os.path.join(validated_dir, filename)
    real_dir = os.path.realpath(validated_dir)
    real_candidate = os.path.realpath(candidate)

    if os.path.commonpath([real_dir, real_candidate]) != real_dir:
        raise ValueError(f"Child file escapes directory: {filename!r}")

    return real_candidate


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

    themes = fetch_theme_registry(registry_url)

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

    theme_id = data["id"]
    if not isinstance(theme_id, str) or not ID_PATTERN.match(theme_id):
        return jsonify({"success": False, "error": "Invalid theme ID"}), 400

    modules_dir = os.environ.get("MODULES_DIR", "/modules")

    try:
        theme_dir = _safe_child_path(modules_dir, theme_id.replace(".", "_"))
    except ValueError:
        return jsonify({"success": False, "error": "Invalid theme ID"}), 400

    if download_theme(data["download_url"], theme_dir):
        return jsonify({"success": True, "restart_required": True})
    else:
        return jsonify({"success": False, "error": "Download failed"}), 500


def _get_modules_dir():
    return os.environ.get("MODULES_DIR", "/modules")


def _scan_installed_community_ids():
    """Scan MODULES_DIR for installed community modules by reading manifest IDs."""
    modules_dir = _get_modules_dir()
    installed = {}
    if not os.path.isdir(modules_dir):
        return installed
    for entry in os.listdir(modules_dir):
        manifest_path = os.path.join(modules_dir, entry, "manifest.json")
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path) as f:
                    data = json.load(f)
                mod_id = data.get("id", "")
                if mod_id:
                    installed[mod_id] = entry
            except Exception as e:
                log.warning("Failed to read manifest in %s: %s", entry, e)
    return installed


@modules_bp.route("/api/modules/registry")
@require_auth
def api_modules_registry():
    """Fetch available community modules from the registry."""
    config_mgr = get_config_manager()
    if not config_mgr:
        return jsonify([])

    registry_url = config_mgr.get(
        "module_registry_url",
        "https://raw.githubusercontent.com/itsDNNS/docsight-modules/main/registry.json",
    )

    modules = fetch_module_registry(registry_url, key="modules")

    # Determine install status via disk detection
    installed_ids = _scan_installed_community_ids()
    disabled_raw = config_mgr.get("disabled_modules", "")
    disabled_set = {s.strip() for s in disabled_raw.split(",") if s.strip()}

    for mod in modules:
        mod_id = mod.get("id", "")
        if mod_id in installed_ids:
            mod["status"] = "installed_disabled" if mod_id in disabled_set else "installed_enabled"
        else:
            mod["status"] = "not_installed"

    return jsonify(modules)


@modules_bp.route("/api/modules/install", methods=["POST"])
@require_auth
def api_modules_install():
    """Download and install a community module."""
    data = request.get_json()
    if not data or "download_url" not in data or "id" not in data:
        return jsonify({"success": False, "error": "Missing download_url or id"}), 400

    mod_id = data["id"]
    modules_dir = _get_modules_dir()

    try:
        target_dir = _safe_child_path(modules_dir, mod_id)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid module ID"}), 400

    # Reject if directory already exists
    if os.path.exists(target_dir):
        return jsonify({"success": False, "error": "Module already installed"}), 409

    # Reject if ID conflicts with existing modules
    loader = get_module_loader()
    if loader:
        existing_ids = {m.id for m in loader.get_modules()}
        if mod_id in existing_ids:
            return jsonify({"success": False, "error": "Module ID conflicts with existing module"}), 409

    # Also check disk for already-installed community modules
    installed_ids = _scan_installed_community_ids()
    if mod_id in installed_ids:
        return jsonify({"success": False, "error": "Module already installed"}), 409

    # Download
    if not download_github_directory(data["download_url"], target_dir):
        return jsonify({"success": False, "error": "Download failed"}), 500

    # Post-download validation
    manifest_path = _safe_child_file(target_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        shutil.rmtree(target_dir, ignore_errors=True)
        return jsonify({"success": False, "error": "Downloaded module missing manifest.json"}), 500

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
        validate_manifest(manifest, target_dir)
        if manifest.get("id") != mod_id:
            raise ValueError(f"Manifest ID '{manifest.get('id')}' does not match requested ID '{mod_id}'")
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        return jsonify({"success": False, "error": f"Invalid module: {e}"}), 500

    # Persist as disabled-by-default
    config_mgr = get_config_manager()
    if config_mgr:
        disabled_raw = config_mgr.get("disabled_modules", "")
        disabled_set = {s.strip() for s in disabled_raw.split(",") if s.strip()}
        disabled_set.add(mod_id)
        config_mgr.save({"disabled_modules": ",".join(sorted(disabled_set))})

    log.info("Module '%s' installed to %s (disabled, restart required)", mod_id, target_dir)
    return jsonify({"success": True, "restart_required": True})


@modules_bp.route("/api/modules/uninstall", methods=["POST"])
@require_auth
def api_modules_uninstall():
    """Uninstall a community module."""
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"success": False, "error": "Missing id"}), 400

    mod_id = data["id"]
    modules_dir = _get_modules_dir()

    installed = _scan_installed_community_ids()
    if mod_id not in installed:
        return jsonify({"success": False, "error": "Module not installed"}), 404

    target_dir = os.path.join(modules_dir, installed[mod_id])

    # Path traversal protection
    real_modules = os.path.realpath(modules_dir)
    real_target = os.path.realpath(target_dir)
    if not real_target.startswith(real_modules + os.sep):
        return jsonify({"success": False, "error": "Invalid module path"}), 400

    # Only allow uninstalling non-builtin modules
    loader = get_module_loader()
    if loader:
        mod = next((m for m in loader.get_modules() if m.id == mod_id), None)
        if mod and mod.builtin:
            return jsonify({"success": False, "error": "Cannot uninstall built-in module"}), 403

    shutil.rmtree(target_dir, ignore_errors=True)

    # Remove from disabled_modules if present
    config_mgr = get_config_manager()
    if config_mgr:
        disabled_raw = config_mgr.get("disabled_modules", "")
        disabled_set = {s.strip() for s in disabled_raw.split(",") if s.strip()}
        disabled_set.discard(mod_id)
        config_mgr.save({"disabled_modules": ",".join(sorted(disabled_set))})

    log.info("Module '%s' uninstalled (restart required)", mod_id)
    return jsonify({"success": True, "restart_required": True})
