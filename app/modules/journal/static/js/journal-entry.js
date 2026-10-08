/* ── Journal entry dialog ──
   Create, edit and delete an entry, pick its icon and case, and attach
   evidence files. Loaded with the journal dialogs; the list it refreshes
   lives in main.js. */

/* The fields an entry is saved with: trimmed text, the case id as a number or null. */
function journalEntryPayload(fields) {
    return {
        date: fields.date,
        title: (fields.title || '').trim(),
        description: (fields.description || '').trim(),
        icon: fields.icon || '',
        incident_id: fields.incident ? parseInt(fields.incident) : null
    };
}

function updateModalIcon() {
    var iconEl = document.getElementById('entry-modal-icon');
    var manualIcon = document.getElementById('entry-icon-value').value;
    var match;
    if (manualIcon) {
        match = getIconByLabel(manualIcon);
    } else {
        var title = document.getElementById('entry-title-input').value;
        var desc = document.getElementById('entry-desc').value;
        match = detectIcon(title, desc);
    }
    iconEl.innerHTML = match ? match.icon : '';
}

function populateIncidentSelect(selectedId) {
    var sel = document.getElementById('entry-incident-select');
    sel.innerHTML = '<option value="">' + (T.incident_none || 'No Incident') + '</option>';
    _incidentsData.forEach(function(inc) {
        var opt = document.createElement('option');
        opt.value = inc.id;
        opt.textContent = inc.name + ' (' + (T['incident_status_' + inc.status] || inc.status) + ')';
        if (selectedId && parseInt(selectedId) === inc.id) opt.selected = true;
        sel.appendChild(opt);
    });
}

function openEntryModal(entryId, incidentId) {
    var modal = document.getElementById('entry-modal');
    var titleEl = document.getElementById('entry-modal-title');
    var idEl = document.getElementById('entry-id');
    var dateEl = document.getElementById('entry-date');
    var titleInput = document.getElementById('entry-title-input');
    var descEl = document.getElementById('entry-desc');
    var iconVal = document.getElementById('entry-icon-value');
    var deleteBtn = document.getElementById('entry-delete-btn');
    var attachSection = document.getElementById('entry-attachments-section');
    var attachList = document.getElementById('entry-attachment-list');
    var uploadBtn = document.getElementById('entry-upload-btn');
    var uploadHint = document.getElementById('entry-upload-hint');
    var saveBtn = document.getElementById('entry-save-btn');

    attachList.innerHTML = '';

    if (entryId) {
        titleEl.textContent = T.edit_entry || 'Edit Entry';
        if (saveBtn) saveBtn.textContent = T.entry_update_action || 'Update entry';
        deleteBtn.hidden = false;
        fetch(docsightUrl('/api/journal/' + entryId))
            .then(function(r) { return r.json(); })
            .then(function(entry) {
                idEl.value = entry.id;
                dateEl.value = entry.date;
                titleInput.value = entry.title;
                descEl.value = entry.description || '';
                iconVal.value = entry.icon || '';
                renderIconPicker(entry.icon || '');
                updateModalIcon();
                populateIncidentSelect(entry.incident_id);
                renderAttachments(entry.attachments || [], attachList, entryId);
                attachSection.hidden = false;
                if (uploadBtn) uploadBtn.disabled = false;
                if (uploadHint) uploadHint.textContent = '';
                window.DOCSightModal.open(modal);
            });
    } else {
        titleEl.textContent = T.new_entry || 'New Entry';
        if (saveBtn) saveBtn.textContent = T.entry_create_action || 'Create entry';
        idEl.value = '';
        dateEl.value = todayStr();
        titleInput.value = '';
        descEl.value = '';
        iconVal.value = '';
        renderIconPicker('');
        updateModalIcon();
        populateIncidentSelect(incidentId || (_activeIncidentFilter > 0 ? _activeIncidentFilter : null));
        deleteBtn.hidden = true;
        attachSection.hidden = false;
        if (uploadBtn) uploadBtn.disabled = true;
        if (uploadHint) uploadHint.textContent = T.entry_save_before_upload || 'Create the entry first, then attach evidence files.';
        window.DOCSightModal.open(modal);
    }
}

// Live icon update when typing title
(function() {
    var ti = document.getElementById('entry-title-input');
    if (ti) ti.addEventListener('input', updateModalIcon);
})();

function closeEntryModal() {
    window.DOCSightModal.close('entry-modal');
}

function renderAttachments(attachments, container, incidentId) {
    container.textContent = '';
    attachments.forEach(function(att) {
        var item = document.createElement('div');
        item.className = 'attachment-item';
        var isImage = att.mime_type && att.mime_type.indexOf('image/') === 0;
        var attachmentUrl = docsightUrl('/api/attachments/' + att.id);
        var thumb;
        if (isImage) {
            thumb = document.createElement('img');
            thumb.className = 'attachment-thumb';
            thumb.src = attachmentUrl;
            thumb.alt = '';
        } else {
            thumb = document.createElement('div');
            thumb.className = 'attachment-icon';
            thumb.textContent = att.mime_type === 'application/pdf' ? '\uD83D\uDCC4' : '\uD83D\uDDCE';
        }
        item.appendChild(thumb);

        var info = document.createElement('div');
        info.className = 'attachment-info';
        var name = document.createElement('span');
        name.className = 'attachment-name';
        name.textContent = att.filename;
        info.appendChild(name);

        var actions = document.createElement('div');
        actions.className = 'attachment-actions';
        var download = document.createElement('a');
        download.href = attachmentUrl;
        download.download = '';
        download.title = T.download || 'Download';
        download.textContent = '\u2B07';
        actions.appendChild(download);

        var deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.title = T.delete || 'Delete';
        deleteBtn.textContent = '\uD83D\uDDD1';
        deleteBtn.addEventListener('click', function() {
            deleteAttachment(att.id, incidentId);
        });
        actions.appendChild(deleteBtn);
        info.appendChild(actions);
        item.appendChild(info);
        container.appendChild(item);
    });
}

function saveEntry() {
    var idEl = document.getElementById('entry-id');
    var entryId = idEl.value;
    var incidentSel = document.getElementById('entry-incident-select');
    var entry = journalEntryPayload({
        date: document.getElementById('entry-date').value,
        title: document.getElementById('entry-title-input').value,
        description: document.getElementById('entry-desc').value,
        icon: document.getElementById('entry-icon-value').value,
        incident: incidentSel ? incidentSel.value : ''
    });

    if (!entry.title) {
        showToast(T.incident_title + ' required', 'error');
        return;
    }

    var payload = JSON.stringify(entry);
    var url = docsightUrl(entryId ? '/api/journal/' + entryId : '/api/journal');
    var method = entryId ? 'PUT' : 'POST';

    fetch(url, {method: method, headers: {'Content-Type': 'application/json'}, body: payload})
        .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
        .then(function(res) {
            if (res.status >= 400) {
                showToast(res.data.error || 'Error', 'error');
                return;
            }
            // A note added from a case lands in that case's timeline.
            if (_timelineActive && _timelineIncidentId) openIncidentTimeline(_timelineIncidentId);
            else loadJournal();
            loadIncidents();
            if (!entryId && res.data.id) {
                // New entry: switch modal to edit mode in-place (keep it open)
                idEl.value = res.data.id;
                document.getElementById('entry-modal-title').textContent = T.edit_entry || 'Edit Entry';
                document.getElementById('entry-delete-btn').hidden = false;
                document.getElementById('entry-attachments-section').hidden = false;
                var uploadBtn = document.getElementById('entry-upload-btn');
                var uploadHint = document.getElementById('entry-upload-hint');
                var saveBtn = document.getElementById('entry-save-btn');
                if (uploadBtn) uploadBtn.disabled = false;
                if (uploadHint) uploadHint.textContent = '';
                if (saveBtn) saveBtn.textContent = T.entry_update_action || 'Update entry';
                showToast(T.entry_saved || 'Entry saved', 'ok');
            } else {
                closeEntryModal();
            }
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

/* A single entry disappears at once and is deleted when its Undo toast runs out,
   or right away when the page is left; Undo brings it back. Deleting everything
   keeps its confirmation. */
function deleteEntry() {
    var entryId = document.getElementById('entry-id').value;
    if (!entryId) return;
    _journalPendingDeletes[entryId] = true;
    closeEntryModal();
    loadJournal();
    var sent = false;
    function commit() {
        if (sent || !_journalPendingDeletes[entryId]) return;
        sent = true;
        window.removeEventListener('pagehide', commit);
        fetch(docsightUrl('/api/journal/' + entryId), {method: 'DELETE', keepalive: true})
            .then(function(r) {
                if (!r.ok) throw new Error('Delete failed');
                delete _journalPendingDeletes[entryId];
            })
            .catch(function() {
                delete _journalPendingDeletes[entryId];
                loadJournal();
                showToast(T.delete_failed || 'Delete failed', 'error');
            });
    }
    window.addEventListener('pagehide', commit);
    showToast(T.entry_deleted || 'Entry deleted', 'info', {
        action: {label: T.undo || 'Undo', onClick: function() {
            window.removeEventListener('pagehide', commit);
            delete _journalPendingDeletes[entryId];
            loadJournal();
        }},
        onExpire: commit
    });
}

function handleEntryFileUpload(input) {
    var incidentId = document.getElementById('entry-id').value;
    if (!incidentId) {
        showToast(T.entry_save_before_upload || 'Create the entry first, then attach evidence files.', 'info');
        input.value = '';
        return;
    }
    if (!input.files || input.files.length === 0) return;
    var spinner = document.getElementById('entry-upload-spinner');
    var uploadBtn = document.getElementById('entry-upload-btn');
    spinner.hidden = false;
    uploadBtn.disabled = true;
    var uploads = [];
    for (var i = 0; i < input.files.length; i++) {
        uploads.push(uploadOneFile(incidentId, input.files[i]));
    }
    Promise.all(uploads)
        .then(function(results) {
            var errors = results.filter(function(r) { return r.error; });
            if (errors.length > 0) {
                showToast(errors[0].error, 'error');
            }
            spinner.hidden = true;
            uploadBtn.disabled = false;
            input.value = '';
            // Reload attachments
            fetch(docsightUrl('/api/journal/' + incidentId))
                .then(function(r) { return r.json(); })
                .then(function(inc) {
                    renderAttachments(inc.attachments || [], document.getElementById('entry-attachment-list'), incidentId);
                });
        })
        .catch(function() {
            spinner.hidden = true;
            uploadBtn.disabled = false;
            showToast(T.network_error || 'Error', 'error');
        });
}

function uploadOneFile(incidentId, file) {
    var formData = new FormData();
    formData.append('file', file);
    return fetch(docsightUrl('/api/journal/' + incidentId + '/attachments'), {method: 'POST', body: formData})
        .then(function(r) { return r.json().then(function(d) { return r.status >= 400 ? {error: d.error} : d; }); })
        .catch(function() { return {error: T.network_error || 'Upload failed'}; });
}

function deleteAttachment(attachmentId, incidentId) {
    fetch(docsightUrl('/api/attachments/' + attachmentId), {method: 'DELETE'})
        .then(function(r) { return r.json(); })
        .then(function() {
            fetch(docsightUrl('/api/journal/' + incidentId))
                .then(function(r) { return r.json(); })
                .then(function(inc) {
                    renderAttachments(inc.attachments || [], document.getElementById('entry-attachment-list'), incidentId);
                });
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

(function() {
    var entryFiles = document.getElementById('entry-file-input');
    if (entryFiles) entryFiles.addEventListener('change', function() { handleEntryFileUpload(this); });
})();

/* Expose entry functions for data-action handlers */
window.openEntryModal = openEntryModal;
window.closeEntryModal = closeEntryModal;
window.saveEntry = saveEntry;
window.deleteEntry = deleteEntry;
window.deleteAttachment = deleteAttachment;
window.handleEntryFileUpload = handleEntryFileUpload;
