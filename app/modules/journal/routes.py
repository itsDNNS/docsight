"""Journal and incident management routes."""

import csv
import json
import logging
import re
from datetime import datetime
from io import BytesIO

from flask import Blueprint, request, jsonify, send_file, make_response

from app.web import (
    require_auth,
    get_storage, get_config_manager, get_state,
    _valid_date, _localize_timestamps, _get_client_ip, _get_lang, _get_tz_name,
)
from app.storage import ALLOWED_MIME_TYPES, MAX_ATTACHMENT_SIZE, MAX_ATTACHMENTS_PER_ENTRY
from app.i18n import get_translations

from werkzeug.utils import secure_filename

audit_log = logging.getLogger("docsis.audit")
log = logging.getLogger("docsis.web")

bp = Blueprint("journal_bp", __name__)

_VALID_INCIDENT_STATUSES = {"open", "resolved", "escalated"}


def _get_journal_storage():
    """Get JournalStorage for journal-specific queries."""
    from app.web import get_storage
    core = get_storage()
    if not core:
        return None
    from .storage import JournalStorage
    return JournalStorage(core.db_path)


# ── Journal Entries API ──

@bp.route("/api/journal", methods=["GET"])
@require_auth
def api_journal_list():
    """Return list of journal entries with attachment counts."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify([])
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    search = request.args.get("search", "", type=str).strip() or None
    incident_id_param = request.args.get("incident_id", None, type=str)
    incident_id = None
    if incident_id_param is not None and incident_id_param != "":
        try:
            incident_id = int(incident_id_param)
        except (ValueError, TypeError):
            pass
    entries = _storage.get_entries(limit=limit, offset=offset, search=search, incident_id=incident_id)
    _localize_timestamps(entries)
    return jsonify(entries)


@bp.route("/api/journal/export")
@require_auth
def api_journal_export():
    """Export journal entries as CSV, JSON, or Markdown file download."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500

    fmt = request.args.get("format", "csv").lower()
    if fmt not in ("csv", "json", "md"):
        return jsonify({"error": "Unsupported format. Use csv, json, or md."}), 400

    date_from = request.args.get("from", None, type=str)
    date_to = request.args.get("to", None, type=str)
    incident_id_param = request.args.get("incident_id", None, type=str)
    incident_id = None
    if incident_id_param is not None and incident_id_param != "":
        try:
            incident_id = int(incident_id_param)
        except (ValueError, TypeError):
            pass

    entries = _storage.get_entries_for_export(date_from=date_from, date_to=date_to, incident_id=incident_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "csv":
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Date", "Title", "Description", "Icon", "Incident ID", "Attachments", "Created", "Updated"])
        for e in entries:
            writer.writerow([
                e["id"], e["date"], e["title"], e.get("description", ""),
                e.get("icon", ""), e.get("incident_id", ""),
                e.get("attachment_count", 0), e.get("created_at", ""), e.get("updated_at", ""),
            ])
        content = "\ufeff" + output.getvalue()
        return send_file(
            BytesIO(content.encode("utf-8")),
            mimetype="text/csv; charset=utf-8",
            as_attachment=True,
            download_name=f"journal_export_{timestamp}.csv",
        )

    if fmt == "json":
        content = json.dumps(entries, indent=2, ensure_ascii=False)
        return send_file(
            BytesIO(content.encode("utf-8")),
            mimetype="application/json; charset=utf-8",
            as_attachment=True,
            download_name=f"journal_export_{timestamp}.json",
        )

    # Markdown
    lines = ["# DOCSight Incident Journal Export", ""]
    if date_from or date_to:
        lines.append(f"**Filter:** {date_from or '...'} to {date_to or '...'}")
        lines.append("")
    lines.append(f"**Entries:** {len(entries)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    for e in entries:
        icon = f" {e['icon']}" if e.get("icon") else ""
        lines.append(f"## {e['date']} {icon} {e['title']}")
        lines.append("")
        if e.get("description"):
            lines.append(e["description"])
            lines.append("")
        meta = []
        if e.get("incident_id"):
            meta.append(f"Incident: #{e['incident_id']}")
        if e.get("attachment_count"):
            meta.append(f"Attachments: {e['attachment_count']}")
        if meta:
            lines.append(f"*{' | '.join(meta)}*")
            lines.append("")
        lines.append("---")
        lines.append("")
    content = "\n".join(lines)
    return send_file(
        BytesIO(content.encode("utf-8")),
        mimetype="text/markdown; charset=utf-8",
        as_attachment=True,
        download_name=f"journal_export_{timestamp}.md",
    )


@bp.route("/api/journal", methods=["POST"])
@require_auth
def api_journal_create():
    """Create a new journal entry."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not _valid_date(date):
        return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title too long (max 200 characters)"}), 400
    if len(description) > 10000:
        return jsonify({"error": "Description too long (max 10000 characters)"}), 400
    icon = (data.get("icon") or "").strip() or None
    inc_id = data.get("incident_id")
    if inc_id is not None:
        try:
            inc_id = int(inc_id) if inc_id else None
        except (ValueError, TypeError):
            inc_id = None
    entry_id = _storage.save_entry(date, title, description, icon=icon, incident_id=inc_id)
    audit_log.info("Journal entry created: ip=%s id=%d title=%s", _get_client_ip(), entry_id, title[:50])
    return jsonify({"id": entry_id}), 201


@bp.route("/api/journal/<int:entry_id>", methods=["GET"])
@require_auth
def api_journal_get(entry_id):
    """Return single journal entry with attachment metadata."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    entry = _storage.get_entry(entry_id)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    return jsonify(entry)


@bp.route("/api/journal/<int:entry_id>", methods=["PUT"])
@require_auth
def api_journal_update(entry_id):
    """Update an existing journal entry."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not _valid_date(date):
        return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title too long (max 200 characters)"}), 400
    if len(description) > 10000:
        return jsonify({"error": "Description too long (max 10000 characters)"}), 400
    icon = (data.get("icon") or "").strip() or None
    inc_id = data.get("incident_id")
    if inc_id is not None:
        try:
            inc_id = int(inc_id) if inc_id else None
        except (ValueError, TypeError):
            inc_id = None
    if not _storage.update_entry(entry_id, date, title, description, icon=icon, incident_id=inc_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Journal entry updated: ip=%s id=%d", _get_client_ip(), entry_id)
    return jsonify({"success": True})


@bp.route("/api/journal/<int:entry_id>", methods=["DELETE"])
@require_auth
def api_journal_delete(entry_id):
    """Delete a journal entry (CASCADE deletes attachments)."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_entry(entry_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Journal entry deleted: ip=%s id=%d", _get_client_ip(), entry_id)
    return jsonify({"success": True})


@bp.route("/api/journal/<int:entry_id>/attachments", methods=["POST"])
@require_auth
def api_journal_upload(entry_id):
    """Upload file attachment for a journal entry."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    entry = _storage.get_entry(entry_id)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    mime_type = f.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        return jsonify({"error": "File type not allowed"}), 400
    current_count = _storage.get_attachment_count(entry_id)
    if current_count >= MAX_ATTACHMENTS_PER_ENTRY:
        return jsonify({"error": "Too many attachments (max %d)" % MAX_ATTACHMENTS_PER_ENTRY}), 400
    file_data = f.read()
    if len(file_data) > MAX_ATTACHMENT_SIZE:
        return jsonify({"error": "File too large (max 10 MB)"}), 400
    filename = secure_filename(f.filename) or "attachment"
    attachment_id = _storage.save_attachment(entry_id, filename, mime_type, file_data)
    audit_log.info(
        "Attachment uploaded: ip=%s entry=%d file=%s size=%d",
        _get_client_ip(), entry_id, filename, len(file_data),
    )
    return jsonify({"id": attachment_id}), 201


@bp.route("/api/attachments/<int:attachment_id>", methods=["GET"])
@require_auth
def api_attachment_get(attachment_id):
    """Download an attachment file."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    att = _storage.get_attachment(attachment_id)
    if not att:
        return jsonify({"error": "Not found"}), 404
    return send_file(
        BytesIO(att["data"]),
        mimetype=att["mime_type"],
        as_attachment=True,
        download_name=att["filename"],
    )


@bp.route("/api/attachments/<int:attachment_id>", methods=["DELETE"])
@require_auth
def api_attachment_delete(attachment_id):
    """Delete a single attachment."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_attachment(attachment_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Attachment deleted: ip=%s id=%d", _get_client_ip(), attachment_id)
    return jsonify({"success": True})


# ── Journal Import API ──

@bp.route("/api/journal/import/preview", methods=["POST"])
@require_auth
def api_journal_import_preview():
    """Upload Excel/CSV file and return parsed preview with auto-detected mapping."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    lower = f.filename.lower()
    if not (lower.endswith(".xlsx") or lower.endswith(".csv")):
        return jsonify({"error": "Only .xlsx and .csv files are supported"}), 400

    file_bytes = f.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        return jsonify({"error": "File too large (max 5 MB)"}), 400

    from .import_parser import parse_file
    try:
        result = parse_file(file_bytes, f.filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        log.exception("Import parse error")
        return jsonify({"error": "Failed to parse file"}), 500

    # Mark duplicates
    for row in result["rows"]:
        row["duplicate"] = _storage.check_entry_exists(row["date"], row["title"])

    duplicates = sum(1 for r in result["rows"] if r["duplicate"])
    result["duplicates"] = duplicates

    audit_log.info(
        "Import preview: ip=%s file=%s total=%d skipped=%d duplicates=%d",
        _get_client_ip(), f.filename, result["total"], result["skipped"], duplicates,
    )
    return jsonify(result)


@bp.route("/api/journal/import/confirm", methods=["POST"])
@require_auth
def api_journal_import_confirm():
    """Bulk-import confirmed journal entry rows."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data or "rows" not in data:
        return jsonify({"error": "No rows provided"}), 400

    rows = data["rows"]
    if not isinstance(rows, list):
        return jsonify({"error": "rows must be a list"}), 400

    imported = 0
    duplicates = 0
    for row in rows:
        date = (row.get("date") or "").strip()
        title = (row.get("title") or "").strip()
        description = (row.get("description") or "").strip()

        if not _valid_date(date):
            continue
        if not title:
            continue
        if len(title) > 200:
            title = title[:200]
        if len(description) > 10000:
            description = description[:10000]

        if _storage.check_entry_exists(date, title):
            duplicates += 1
            continue

        _storage.save_entry(date, title, description)
        imported += 1

    audit_log.info(
        "Import confirm: ip=%s imported=%d duplicates=%d",
        _get_client_ip(), imported, duplicates,
    )
    return jsonify({"imported": imported, "duplicates": duplicates})


@bp.route("/api/journal/batch", methods=["DELETE"])
@require_auth
def api_journal_batch_delete():
    """Batch delete journal entries by IDs or delete all."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    if data.get("all"):
        if data.get("confirm") != "DELETE_ALL":
            return jsonify({"error": "Confirmation required: set confirm to 'DELETE_ALL'"}), 400
        deleted = _storage.delete_all_entries()
        audit_log.info("All journal entries deleted: ip=%s count=%d", _get_client_ip(), deleted)
        return jsonify({"deleted": deleted})

    ids = data.get("ids")
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "Provide 'ids' list or 'all: true'"}), 400
    ids = [int(i) for i in ids if isinstance(i, (int, float))]
    if not ids:
        return jsonify({"error": "No valid IDs"}), 400

    deleted = _storage.delete_entries_batch(ids)
    audit_log.info("Batch delete journal entries: ip=%s ids=%s deleted=%d", _get_client_ip(), ids, deleted)
    return jsonify({"deleted": deleted})


# ── Journal Entry Unassign ──

@bp.route("/api/journal/unassign", methods=["POST"])
@require_auth
def api_journal_unassign():
    """Remove incident assignment from journal entries."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    entry_ids = data.get("entry_ids", [])
    if not entry_ids or not isinstance(entry_ids, list):
        return jsonify({"error": "Provide entry_ids list"}), 400
    entry_ids = [int(i) for i in entry_ids if isinstance(i, (int, float))]
    count = _storage.unassign_entries(entry_ids)
    return jsonify({"updated": count})


# ── Incident Container API ──

@bp.route("/api/incidents", methods=["GET"])
@require_auth
def api_incidents_list():
    """Return list of incident containers with entry_count."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify([])
    status = request.args.get("status", None, type=str)
    if status and status not in _VALID_INCIDENT_STATUSES:
        status = None
    incidents = _storage.get_incidents(status=status)
    _localize_timestamps(incidents)
    return jsonify(incidents)


@bp.route("/api/incidents", methods=["POST"])
@require_auth
def api_incidents_create():
    """Create a new incident container."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if len(name) > 200:
        return jsonify({"error": "Name too long (max 200 characters)"}), 400
    description = (data.get("description") or "").strip()
    if len(description) > 5000:
        return jsonify({"error": "Description too long (max 5000 characters)"}), 400
    status = (data.get("status") or "open").strip()
    if status not in _VALID_INCIDENT_STATUSES:
        return jsonify({"error": "Invalid status (open, resolved, escalated)"}), 400
    start_date = (data.get("start_date") or "").strip() or None
    end_date = (data.get("end_date") or "").strip() or None
    if start_date and not _valid_date(start_date):
        return jsonify({"error": "Invalid start_date format (YYYY-MM-DD)"}), 400
    if end_date and not _valid_date(end_date):
        return jsonify({"error": "Invalid end_date format (YYYY-MM-DD)"}), 400
    icon = (data.get("icon") or "").strip() or None
    incident_id = _storage.save_incident(name, description, status, start_date, end_date, icon)
    audit_log.info("Incident created: ip=%s id=%d name=%s", _get_client_ip(), incident_id, name[:50])
    return jsonify({"id": incident_id}), 201


@bp.route("/api/incidents/<int:incident_id>", methods=["GET"])
@require_auth
def api_incident_get(incident_id):
    """Return single incident container with entry_count."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Not found"}), 404
    return jsonify(incident)


@bp.route("/api/incidents/<int:incident_id>", methods=["PUT"])
@require_auth
def api_incident_update(incident_id):
    """Update an existing incident container."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if len(name) > 200:
        return jsonify({"error": "Name too long (max 200 characters)"}), 400
    description = (data.get("description") or "").strip()
    if len(description) > 5000:
        return jsonify({"error": "Description too long (max 5000 characters)"}), 400
    status = (data.get("status") or "open").strip()
    if status not in _VALID_INCIDENT_STATUSES:
        return jsonify({"error": "Invalid status (open, resolved, escalated)"}), 400
    start_date = (data.get("start_date") or "").strip() or None
    end_date = (data.get("end_date") or "").strip() or None
    if start_date and not _valid_date(start_date):
        return jsonify({"error": "Invalid start_date format (YYYY-MM-DD)"}), 400
    if end_date and not _valid_date(end_date):
        return jsonify({"error": "Invalid end_date format (YYYY-MM-DD)"}), 400
    icon = (data.get("icon") or "").strip() or None
    if not _storage.update_incident(incident_id, name, description, status, start_date, end_date, icon):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Incident updated: ip=%s id=%d", _get_client_ip(), incident_id)
    return jsonify({"success": True})


@bp.route("/api/incidents/<int:incident_id>", methods=["DELETE"])
@require_auth
def api_incident_delete(incident_id):
    """Delete an incident container (entries become unassigned)."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    if not _storage.delete_incident(incident_id):
        return jsonify({"error": "Not found"}), 404
    audit_log.info("Incident deleted: ip=%s id=%d", _get_client_ip(), incident_id)
    return jsonify({"success": True})


@bp.route("/api/incidents/<int:incident_id>/timeline")
@require_auth
def api_incident_timeline(incident_id):
    """Return bundled timeline data for a single incident."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Not found"}), 404

    entries = _storage.get_entries(limit=9999, incident_id=incident_id)

    timeline = []
    bnetz = []
    if incident.get("start_date"):
        from app.tz import local_date_to_utc_range
        tz = _get_tz_name()
        start_ts, _ = local_date_to_utc_range(incident["start_date"], tz)
        end_date = incident.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        _, end_ts = local_date_to_utc_range(end_date, tz)
        from app.web import get_storage as _get_core_storage
        _core = _get_core_storage()
        if _core:
            timeline = _core.get_correlation_timeline(start_ts, end_ts)
        try:
            from app.modules.bnetz.storage import BnetzStorage
            _bs = BnetzStorage(_core.db_path)
            bnetz = _bs.get_bnetz_in_range(start_ts, end_ts)
        except (ImportError, Exception):
            bnetz = []

    _localize_timestamps(timeline)
    _localize_timestamps(entries)
    _localize_timestamps(incident)
    _localize_timestamps(bnetz)
    return jsonify({
        "incident": incident,
        "entries": entries,
        "timeline": timeline,
        "bnetz": bnetz,
    })


@bp.route("/api/incidents/<int:incident_id>/report")
@require_auth
def api_incident_report(incident_id):
    """Generate PDF complaint report for a specific incident."""
    from app.modules.reports.report import generate_incident_report

    _storage = _get_journal_storage()
    _config_manager = get_config_manager()

    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500

    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Not found"}), 404

    entries = _storage.get_entries(limit=9999, incident_id=incident_id)

    # For entries with attachments, load full attachment metadata
    for entry in entries:
        full = _storage.get_entry(entry["id"])
        if full:
            entry["attachments"] = full.get("attachments", [])

    snapshots = []
    speedtests = []
    bnetz = []
    if incident.get("start_date"):
        from app.tz import local_date_to_utc_range as _ldr
        _tz = _get_tz_name()
        start_ts, _ = _ldr(incident["start_date"], _tz)
        end_date = incident.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        _, end_ts = _ldr(end_date, _tz)
        from app.web import get_storage as _get_core_storage
        _core = _get_core_storage()
        snapshots = _core.get_range_data(start_ts, end_ts) if _core else []
        try:
            from app.modules.speedtest.storage import SpeedtestStorage
            _ss = SpeedtestStorage(_core.db_path)
            speedtests = _ss.get_speedtest_in_range(start_ts, end_ts)
        except (ImportError, Exception):
            speedtests = []
        try:
            from app.modules.bnetz.storage import BnetzStorage
            _bs = BnetzStorage(_core.db_path)
            bnetz = _bs.get_bnetz_in_range(start_ts, end_ts)
        except (ImportError, Exception):
            bnetz = []

    config = {}
    if _config_manager:
        config = {
            "isp_name": _config_manager.get("isp_name", ""),
            "modem_type": _config_manager.get("modem_type", ""),
        }

    conn_info = get_state().get("connection_info") or {}
    lang = _get_lang()

    pdf_bytes = generate_incident_report(
        incident, entries, snapshots, speedtests, bnetz,
        config, conn_info, lang,
        attachment_loader=_storage.get_attachment,
    )

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', incident.get("name", "incident"))
    ts = datetime.now().strftime("%Y-%m-%d")
    response.headers["Content-Disposition"] = f'attachment; filename="DOCSight_Beschwerde_{safe_name}_{ts}.pdf"'
    return response


@bp.route("/api/incidents/<int:incident_id>/assign", methods=["POST"])
@require_auth
def api_incident_assign(incident_id):
    """Assign journal entries to an incident."""
    _storage = _get_journal_storage()
    if not _storage:
        return jsonify({"error": "Storage not initialized"}), 500
    incident = _storage.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "Incident not found"}), 404
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    entry_ids = data.get("entry_ids", [])
    if not entry_ids or not isinstance(entry_ids, list):
        return jsonify({"error": "Provide entry_ids list"}), 400
    entry_ids = [int(i) for i in entry_ids if isinstance(i, (int, float))]
    count = _storage.assign_entries_to_incident(entry_ids, incident_id)
    audit_log.info("Entries assigned: ip=%s incident=%d count=%d", _get_client_ip(), incident_id, count)
    return jsonify({"updated": count})
