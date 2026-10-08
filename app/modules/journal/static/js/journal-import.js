/* ── Journal import ──
   Import dialog: upload a CSV or Excel file, preview the parsed rows, fix
   missing dates, and import the selected rows. Loaded with the journal dialogs;
   the list itself (loadJournal) lives in main.js. */
var _importPreviewData = null;

/* Rows by state: ready to import, duplicates of existing entries, and rows still missing a date. */
function journalImportSummary(rows) {
    var summary = {ready: 0, duplicates: 0, needsDate: 0};
    rows.forEach(function(row) {
        if (row.skipped || !row.date) summary.needsDate++;
        else if (row.duplicate) summary.duplicates++;
        else summary.ready++;
    });
    return summary;
}

/* The selected rows that have a date, as the import API expects them. */
function journalImportRows(rows, selectedIndexes) {
    var out = [];
    selectedIndexes.forEach(function(idx) {
        var row = rows[idx];
        if (row && row.date) out.push({date: row.date, title: row.title, description: row.description});
    });
    return out;
}

function _importSelectedIndexes() {
    var cbs = document.querySelectorAll('.import-row-cb');
    var indexes = [];
    for (var i = 0; i < cbs.length; i++) {
        if (cbs[i].checked) indexes.push(parseInt(cbs[i].getAttribute('data-idx')));
    }
    return indexes;
}

function openImportModal() {
    document.getElementById('import-upload-zone').hidden = false;
    document.getElementById('import-loading').hidden = true;
    document.getElementById('import-preview').hidden = true;
    document.getElementById('import-footer').hidden = true;
    document.getElementById('import-file-input').value = '';
    setImportValidationState(T.import_validation_choose || 'Choose a CSV or Excel file. DOCSight will preview rows before importing.', 'info');
    _importPreviewData = null;
    window.DOCSightModal.open('import-modal');
}

function closeImportModal() {
    window.DOCSightModal.close('import-modal');
}

function setImportValidationState(message, tone) {
    var el = document.getElementById('import-validation-state');
    if (!el) return;
    el.textContent = message || '';
    el.className = 'import-validation-state' + (tone ? ' is-' + tone : '');
}

function updateImportSelectionState() {
    if (!_importPreviewData) return;
    var indexes = _importSelectedIndexes();
    var selected = indexes.length;
    var selectedImportable = journalImportRows(_importPreviewData.rows, indexes).length;
    var btn = document.getElementById('import-confirm-btn');
    if (btn) {
        btn.disabled = selectedImportable === 0;
        btn.textContent = selectedImportable === 1 ? (T.import_selected_one || 'Import 1 selected entry') : (T.import_selected_count || 'Import {0} selected entries').replace('{0}', selectedImportable);
    }
    if (selectedImportable === 0) {
        var noneMessage = selected > 0
            ? (T.import_validation_no_valid || 'No valid rows selected. Add dates or select rows that are ready to import.')
            : (T.import_validation_no_valid || 'No valid rows selected. Select at least one ready row to import.');
        setImportValidationState(noneMessage, 'error');
    } else {
        updateImportValidationSummary();
    }
}

function updateImportValidationSummary() {
    if (!_importPreviewData) return;
    var summary = journalImportSummary(_importPreviewData.rows || []);
    var parts = [];
    parts.push((T.import_validation_ready || '{0} ready').replace('{0}', summary.ready));
    if (summary.duplicates) parts.push((T.import_validation_duplicates || '{0} duplicate').replace('{0}', summary.duplicates));
    if (summary.needsDate) parts.push((T.import_validation_dates || '{0} needs a date').replace('{0}', summary.needsDate));
    setImportValidationState(parts.join(', '), summary.needsDate ? 'warning' : 'success');
}

// Drag & drop support
(function() {
    var zone = document.getElementById('import-upload-zone');
    if (!zone) return;
    zone.addEventListener('click', function() {
        document.getElementById('import-file-input').click();
    });
    zone.addEventListener('dragover', function(e) {
        e.preventDefault();
        zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function() {
        zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', function(e) {
        e.preventDefault();
        zone.classList.remove('dragover');
        var files = e.dataTransfer.files;
        if (files.length > 0) {
            var input = document.getElementById('import-file-input');
            input.files = files;
            handleImportFile(input);
        }
    });
})();

function handleImportFile(input) {
    if (!input.files || input.files.length === 0) return;
    var file = input.files[0];
    var lower = file.name.toLowerCase();
    if (!lower.endsWith('.xlsx') && !lower.endsWith('.csv')) {
        setImportValidationState(T.import_validation_unsupported || 'Unsupported file type. Use CSV or Excel files.', 'error');
        return;
    }
    if (file.size > 5 * 1024 * 1024) {
        setImportValidationState(T.import_file_too_large || 'File is too large. Maximum size is 5 MB.', 'error');
        return;
    }

    document.getElementById('import-upload-zone').hidden = true;
    document.getElementById('import-loading').hidden = false;
    setImportValidationState(T.import_validation_parsing || 'Parsing file and checking rows...', 'progress');

    var formData = new FormData();
    formData.append('file', file);

    fetch(docsightUrl('/api/journal/import/preview'), {method: 'POST', body: formData})
        .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
        .then(function(res) {
            document.getElementById('import-loading').hidden = true;
            if (res.status >= 400) {
                setImportValidationState(res.data.error || T.error_prefix, 'error');
                document.getElementById('import-upload-zone').hidden = false;
                return;
            }
            _importPreviewData = res.data;
            renderImportPreview(res.data);
        })
        .catch(function() {
            document.getElementById('import-loading').hidden = true;
            document.getElementById('import-upload-zone').hidden = false;
            setImportValidationState(T.network_error || 'Error', 'error');
        });
}

function renderImportPreview(data) {
    _importPreviewData = data;
    var tbody = document.getElementById('import-tbody');
    tbody.innerHTML = '';

    var dupeCount = data.duplicates || 0;
    var validCount = data.total - data.skipped;
    var info = data.total + ' ' + T.import_entries_found;
    if (data.skipped > 0) info += ', ' + data.skipped + ' ' + T.import_skipped;
    if (dupeCount > 0) info += ', ' + dupeCount + ' ' + T.import_duplicates;
    document.getElementById('import-info').textContent = info;

    data.rows.forEach(function(row, i) {
        var tr = document.createElement('tr');
        var isSkipped = row.skipped;
        var isDupe = row.duplicate;
        if (isDupe) tr.className = 'import-row-duplicate';
        if (isSkipped) tr.className = 'import-row-skipped';
        var checked = (isDupe || isSkipped) ? '' : 'checked';
        var desc = row.description || '';
        if (desc.length > 60) desc = desc.substring(0, 60) + '...';
        var dupeBadge = isDupe ? '<span class="import-duplicate-badge">' + T.import_duplicate + '</span>' : '';
        var iconMatch = detectIcon(row.title, row.description);
        var iconHtml = iconMatch ? iconMatch.icon : '';
        var dateCell;
        if (isSkipped) {
            var rawHint = row.raw_date ? ' placeholder="' + escapeHtml(row.raw_date) + '"' : '';
            dateCell = '<input type="date" class="import-date-fix" data-idx="' + i + '"' + rawHint +
                ' data-change-action="fixImportDate" data-action-pass="element" data-action-args="[' + i + ']">' +
                '<span class="import-skipped-badge">' + (T.import_no_date || 'no date') + '</span>';
        } else {
            dateCell = escapeHtml(row.date);
        }
        tr.innerHTML =
            '<td class="dt-lead"><input type="checkbox" class="import-row-cb" data-idx="' + i + '" ' + checked + ' data-change-action="updateImportSelectionState"></td>' +
            '<td class="import-icon-cell">' + iconHtml + '</td>' +
            '<td class="import-date-cell">' + dateCell + '</td>' +
            '<td class="dt-primary">' + escapeHtml(row.title) + dupeBadge + '</td>' +
            '<td class="journal-hide-mobile">' + escapeHtml(desc) + '</td>';
        tbody.appendChild(tr);
    });
    labelDataTable(document.getElementById('import-table'));

    document.getElementById('import-select-all').checked = true;
    document.getElementById('import-preview').hidden = false;
    document.getElementById('import-footer').hidden = false;
    updateImportSelectionState();
}

function fixImportDate(input, idx) {
    if (!_importPreviewData || !_importPreviewData.rows[idx]) return;
    var val = input.value;
    if (val) {
        _importPreviewData.rows[idx].date = val;
        _importPreviewData.rows[idx].skipped = false;
        var tr = input.closest('tr');
        if (tr) {
            tr.classList.remove('import-row-skipped');
            var cb = tr.querySelector('.import-row-cb');
            if (cb) cb.checked = true;
        }
        var badge = tr.querySelector('.import-skipped-badge');
        if (badge) badge.style.display = 'none';
        updateImportSelectionState();
    }
}

function toggleImportAll(checked) {
    var cbs = document.querySelectorAll('.import-row-cb');
    for (var i = 0; i < cbs.length; i++) {
        cbs[i].checked = checked;
    }
    updateImportSelectionState();
}

function confirmImport() {
    if (!_importPreviewData) return;
    var selectedRows = journalImportRows(_importPreviewData.rows, _importSelectedIndexes());
    if (selectedRows.length === 0) {
        showToast(T.import_no_selection, 'error');
        return;
    }

    var btn = document.getElementById('import-confirm-btn');
    btn.disabled = true;
    btn.textContent = T.import_importing;

    fetch(docsightUrl('/api/journal/import/confirm'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rows: selectedRows})
    })
        .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
        .then(function(res) {
            btn.disabled = false;
            btn.textContent = T.import_selected;
            if (res.status >= 400) {
                showToast(res.data.error || T.error_prefix, 'error');
                return;
            }
            var msg = res.data.imported + ' ' + T.import_success;
            if (res.data.duplicates > 0) msg += ', ' + res.data.duplicates + ' ' + T.import_duplicates_skipped;
            showToast(msg, 'ok');
            closeImportModal();
            loadJournal();
        })
        .catch(function() {
            btn.disabled = false;
            btn.textContent = T.import_selected;
            showToast(T.network_error || 'Error', 'error');
        });
}

(function() {
    var importFile = document.getElementById('import-file-input');
    if (importFile) importFile.addEventListener('change', function() { handleImportFile(this); });
    var selectAll = document.getElementById('import-select-all');
    if (selectAll) selectAll.addEventListener('change', function() { toggleImportAll(this.checked); });
})();

/* Expose import functions for data-action handlers */
window.openImportModal = openImportModal;
window.closeImportModal = closeImportModal;
window.handleImportFile = handleImportFile;
window.confirmImport = confirmImport;
window.toggleImportAll = toggleImportAll;
window.fixImportDate = fixImportDate;
