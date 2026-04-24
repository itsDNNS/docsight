"""Backup and restore routes."""

import logging
import os
import time
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, request, jsonify, redirect, send_file

from app.web import (
    require_auth, _auth_required,
    get_config_manager, get_on_config_changed,
    _get_client_ip,
)

from werkzeug.utils import secure_filename

from .backup import (
    browse_directory, cleanup_old_backups, create_backup, create_backup_to_file,
    list_backups, restore_backup, validate_backup,
)

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web")

bp = Blueprint("backup_bp", __name__)

# Rate-limit unauthenticated restore attempts (setup-race mitigation)
_restore_attempts: dict[str, list[float]] = defaultdict(list)
_RESTORE_MAX_ATTEMPTS = 5
_RESTORE_WINDOW = 3600  # 1 hour


def _check_restore_rate_limit() -> bool:
    """Return True if the client has exceeded the restore rate limit."""
    ip = _get_client_ip()
    now = time.time()
    attempts = _restore_attempts[ip]
    _restore_attempts[ip] = [t for t in attempts if now - t < _RESTORE_WINDOW]
    return len(_restore_attempts[ip]) >= _RESTORE_MAX_ATTEMPTS


def _record_restore_attempt():
    """Record a restore attempt for the current client IP."""
    _restore_attempts[_get_client_ip()].append(time.time())


def _int_config(config_mgr, key, default):
    """Read an integer-like config value safely."""
    try:
        value = int(config_mgr.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@bp.route("/api/backup", methods=["POST"])
@require_auth
def api_backup_download():
    """Create a backup and stream it as download."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify({"error": "Not initialized"}), 500
    try:
        buf = create_backup(_config_manager.data_dir)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"docsight_backup_{ts}.tar.gz"
        audit_log.info("Backup downloaded: ip=%s", _get_client_ip())
        return send_file(buf, mimetype="application/gzip", as_attachment=True, download_name=filename)
    except Exception as e:
        log.error("Backup creation failed: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/backup/scheduled", methods=["POST"])
@require_auth
def api_backup_scheduled():
    """Create a backup in the configured backup path."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify({"error": "Not initialized"}), 500
    backup_path = _config_manager.get("backup_path", "/backup")
    retention = _int_config(_config_manager, "backup_retention", 5)
    try:
        filename = create_backup_to_file(_config_manager.data_dir, backup_path)
        cleanup_old_backups(backup_path, keep=retention)
        audit_log.info("Scheduled backup created: ip=%s file=%s", _get_client_ip(), filename)
        return jsonify({"success": True, "filename": filename})
    except Exception as e:
        log.error("Scheduled backup failed: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/backup/list")
@require_auth
def api_backup_list():
    """List backups in the configured backup path."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify([])
    backup_path = _config_manager.get("backup_path", "/backup")
    return jsonify(list_backups(backup_path))


@bp.route("/api/backup/<filename>", methods=["DELETE"])
@require_auth
def api_backup_delete(filename):
    """Delete a backup file."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify({"error": "Not initialized"}), 500
    backup_path = _config_manager.get("backup_path", "/backup")
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return jsonify({"error": "Invalid filename"}), 400
    fpath = os.path.join(backup_path, safe_name)
    real_fpath = os.path.realpath(fpath)
    real_backup = os.path.realpath(backup_path)
    if not real_fpath.startswith(real_backup + os.sep):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(real_fpath):
        return jsonify({"error": "Not found"}), 404
    os.remove(real_fpath)
    audit_log.info("Backup deleted: ip=%s file=%s", _get_client_ip(), safe_name)
    return jsonify({"success": True})


@bp.route("/api/restore/validate", methods=["POST"])
def api_restore_validate():
    """Validate a backup archive and return metadata.

    No auth required during initial setup (not configured yet).
    Auth required if already configured.
    """
    _config_manager = get_config_manager()
    if _config_manager and _config_manager.is_configured() and _auth_required():
        return redirect("/login")
    if not (_config_manager and _config_manager.is_configured()):
        if _check_restore_rate_limit():
            audit_log.warning("Restore rate limit exceeded: ip=%s", _get_client_ip())
            return jsonify({"error": "Too many attempts"}), 429
        _record_restore_attempt()
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    data = f.read()
    if len(data) > 500 * 1024 * 1024:  # 500 MB limit
        return jsonify({"error": "File too large"}), 400
    try:
        meta = validate_backup(data)
        return jsonify({"valid": True, "meta": meta})
    except ValueError as e:
        return jsonify({"valid": False, "error": str(e)}), 400


@bp.route("/api/restore", methods=["POST"])
def api_restore():
    """Restore a backup archive.

    No auth required during initial setup (not configured yet).
    Auth required if already configured.
    """
    _config_manager = get_config_manager()
    if _config_manager is None:
        return jsonify({"error": "Not initialized"}), 500
    if _config_manager.is_configured() and _auth_required():
        return redirect("/login")
    if not _config_manager.is_configured():
        if _check_restore_rate_limit():
            audit_log.warning("Restore rate limit exceeded: ip=%s", _get_client_ip())
            return jsonify({"error": "Too many attempts"}), 429
        _record_restore_attempt()
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    data = f.read()
    if len(data) > 500 * 1024 * 1024:
        return jsonify({"error": "File too large"}), 400
    try:
        result = restore_backup(data, _config_manager.data_dir)
        audit_log.info(
            "Backup restored: ip=%s files=%s",
            _get_client_ip(), result["restored_files"],
        )
        # Reload config so the app recognizes the restored state
        _config_manager._load()
        _on_config_changed = get_on_config_changed()
        if _on_config_changed:
            _on_config_changed()
        return jsonify({
            "success": True,
            "restored_files": result["restored_files"],
            "configured": _config_manager.is_configured(),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        log.error("Restore failed: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/browse")
@require_auth
def api_browse():
    """Browse server-side directories for backup path selection."""
    path = request.args.get("path", "/backup")
    try:
        result = browse_directory(path)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
