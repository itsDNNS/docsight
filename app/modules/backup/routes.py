"""Backup and restore routes."""

import logging
import os
import shutil
import tempfile
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file

from app.web_auth import require_auth, _get_client_ip
from app.runtime import current_runtime

from werkzeug.utils import secure_filename

from .backup import (
    _write_backup_archive, browse_directory, cleanup_old_backups, create_backup_to_file,
    list_backups, restore_backup, validate_backup,
)

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web")

bp = Blueprint("backup_bp", __name__)

def _int_config(config_mgr, key, default):
    """Read an integer-like config value safely."""
    try:
        value = int(config_mgr.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@bp.route("/api/backup", methods=["POST"])
@require_auth(session_only=True)
def api_backup_download():
    """Create a backup and stream it as download."""
    _config_manager = current_runtime().config_manager
    temp_dir = None
    response = None
    try:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"docsight_backup_{ts}.tar.gz"
        temp_dir = tempfile.mkdtemp(
            prefix=".docsight-backup-download-",
            dir=_config_manager.data_dir,
        )
        archive_path = os.path.join(temp_dir, filename)
        _write_backup_archive(
            _config_manager.data_dir,
            archive_path,
            work_dir=temp_dir,
        )
        response = send_file(
            archive_path,
            mimetype="application/gzip",
            as_attachment=True,
            download_name=filename,
        )
        cleanup_dir = temp_dir
        response.call_on_close(
            lambda: shutil.rmtree(cleanup_dir, ignore_errors=True)
        )
        # send_file uses direct passthrough by default, which returns its file
        # wrapper directly and bypasses Response.close(). Keep iteration lazy
        # while ensuring the WSGI closing iterator runs the registered cleanup.
        response.direct_passthrough = False
        temp_dir = None
        audit_log.info("Backup downloaded: ip=%s", _get_client_ip())
        return response
    except Exception:
        if response is not None:
            response.close()
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
        log.exception("Backup creation failed")
        return jsonify({"error": "Backup failed. See the DOCSight log for details."}), 500


@bp.route("/api/backup/scheduled", methods=["POST"])
@require_auth(session_only=True)
def api_backup_scheduled():
    """Create a backup in the configured backup path."""
    _config_manager = current_runtime().config_manager
    backup_path = _config_manager.get("backup_path", "/backup")
    retention = _int_config(_config_manager, "backup_retention", 5)
    try:
        filename = create_backup_to_file(_config_manager.data_dir, backup_path)
        cleanup_old_backups(backup_path, keep=retention)
        audit_log.info("Scheduled backup created: ip=%s file=%s", _get_client_ip(), filename)
        return jsonify({"success": True, "filename": filename})
    except Exception:
        log.exception("Scheduled backup failed")
        return jsonify({"error": "Backup failed. See the DOCSight log for details."}), 500


@bp.route("/api/backup/list")
@require_auth(session_only=True)
def api_backup_list():
    """List backups in the configured backup path."""
    return jsonify(list_backups(current_runtime().config_manager.get("backup_path", "/backup")))


@bp.route("/api/backup/<filename>", methods=["DELETE"])
@require_auth(session_only=True)
def api_backup_delete(filename):
    """Delete a backup file."""
    _config_manager = current_runtime().config_manager
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
@require_auth(session_only=True)
def api_restore_validate():
    """Validate a backup archive and return metadata."""
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
        log.warning("Backup validation failed: %s", e)
        return jsonify({"valid": False, "error": "Invalid backup file"}), 400


@bp.route("/api/restore", methods=["POST"])
@require_auth(session_only=True)
def api_restore():
    """Restore a backup archive."""
    _config_manager = current_runtime().config_manager
    if _config_manager is None:
        return jsonify({"error": "Not initialized"}), 500
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    data = f.read()
    if len(data) > 500 * 1024 * 1024:
        return jsonify({"error": "File too large"}), 400
    try:
        # No settings save may slip in between the restored config.json and the
        # reload of its encryption key.
        with _config_manager.locked():
            restored = []
            try:
                result = restore_backup(data, _config_manager.data_dir, restored)
                _config_manager.reload()
            finally:
                # Cached storages migrated the replaced databases (a running request may still use one).
                current_runtime().derived_storage.drop_storages({
                    os.path.join(_config_manager.data_dir, name) for name in restored
                })
        audit_log.info(
            "Backup restored: ip=%s files=%s",
            _get_client_ip(), result["restored_files"],
        )
        _on_config_changed = current_runtime().on_config_changed
        if _on_config_changed:
            _on_config_changed()
        return jsonify({
            "success": True,
            "restored_files": result["restored_files"],
            "configured": _config_manager.is_configured(),
        })
    except ValueError as e:
        log.warning("Restore rejected: %s", e)
        return jsonify({"error": "Invalid or damaged backup file"}), 400
    except Exception:
        log.exception("Restore failed")
        return jsonify({"error": "Restore failed. See the DOCSight log for details."}), 500


@bp.route("/api/browse")
@require_auth(session_only=True)
def api_browse():
    """Browse server-side directories for backup path selection."""
    path = request.args.get("path", "/backup")
    try:
        result = browse_directory(path)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
