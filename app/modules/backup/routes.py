"""Backup and restore routes."""

import logging
import os
from datetime import datetime

from flask import Blueprint, request, jsonify, redirect, send_file

from app.web import (
    require_auth, _auth_required,
    get_config_manager, get_on_config_changed,
    _get_client_ip,
)

from werkzeug.utils import secure_filename

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web")

bp = Blueprint("backup_bp", __name__)


@bp.route("/api/backup", methods=["POST"])
@require_auth
def api_backup_download():
    """Create a backup and stream it as download."""
    _config_manager = get_config_manager()
    if not _config_manager:
        return jsonify({"error": "Not initialized"}), 500
    try:
        from .backup import create_backup
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
    retention = _config_manager.get("backup_retention", 5)
    try:
        from .backup import create_backup_to_file, cleanup_old_backups
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
    from .backup import list_backups
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
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    data = f.read()
    if len(data) > 500 * 1024 * 1024:  # 500 MB limit
        return jsonify({"error": "File too large"}), 400
    try:
        from .backup import validate_backup
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
    if _config_manager and _config_manager.is_configured() and _auth_required():
        return redirect("/login")
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    data = f.read()
    if len(data) > 500 * 1024 * 1024:
        return jsonify({"error": "File too large"}), 400
    try:
        from .backup import restore_backup
        data_dir = _config_manager.data_dir if _config_manager else "/data"
        result = restore_backup(data, data_dir)
        audit_log.info(
            "Backup restored: ip=%s files=%s",
            _get_client_ip(), result["restored_files"],
        )
        # Reload config so the app recognizes the restored state
        if _config_manager:
            _config_manager._load()
        _on_config_changed = get_on_config_changed()
        if _on_config_changed:
            _on_config_changed()
        configured = bool(_config_manager and _config_manager.is_configured())
        return jsonify({
            "success": True,
            "restored_files": result["restored_files"],
            "configured": configured,
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
        from .backup import browse_directory
        result = browse_directory(path)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
