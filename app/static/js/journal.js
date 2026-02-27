/* ── journal.js ─────────────────────────────────────────────
   Incident Journal, Incident Containers, Timeline, Import,
   Bulk Selection, Search, Export
   Extracted from the IIFE in index.html (Issue #119)
   ───────────────────────────────────────────────────────── */

/* ── Incident Journal ── */
var _journalLoaded = false;
var _journalSortCol = 'date';
var _journalSortAsc = false;
var _activeIncidentFilter = null; // null=all, 0=unassigned, N=incident id
var _selectedEntryIds = []; // bulk selection state
var _bulkMode = false;
var _incidentsData = []; // cached incident containers

var INCIDENT_ICONS = [
    {keys: ['telefon', 'anruf', 'hotline', 'telefonat', 'angerufen', 'rückruf', 'callcenter'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/></svg>', label: 'phone'},
    {keys: ['techniker', 'monteur', 'reparatur', 'vor ort', 'service-termin', 'servicetermin'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>', label: 'technician'},
    {keys: ['ausfall', 'störung', 'stoerung', 'offline', 'totalausfall', 'kein internet', 'abbruch', 'abbrüche', 'disconnect', 'unterbrechung'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>', label: 'outage'},
    {keys: ['email', 'e-mail', 'schreiben', 'einschreiben', 'schriftlich', 'brieflich', 'fax', 'per post', 'brief geschickt', 'brief gesendet', 'brief erhalten', 'brief geschrieben'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>', label: 'mail'},
    {keys: ['beschwerde', 'reklamation', 'widerspruch', 'einspruch', 'beanstandung'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>', label: 'complaint'},
    {keys: ['vertrag', 'kündigung', 'kuendigung', 'sonderkündigung', 'laufzeit', 'tarif', 'wechsel', 'anbieterwechsel'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>', label: 'contract'},
    {keys: ['messung', 'speedtest', 'breitbandmessung', 'bandbreite', 'geschwindigkeit', 'mbit'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>', label: 'measurement'},
    {keys: ['bundesnetzagentur', 'bnetz', 'bnetza', 'regulierung', 'schlichtung', 'behörde', 'behoerde'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-4h6v4"/></svg>', label: 'authority'},
    {keys: ['rechnung', 'zahlung', 'erstattung', 'gutschrift', 'kosten', 'minderung', 'geld'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>', label: 'billing'},
    {keys: ['router', 'modem', 'fritzbox', 'fritz!box', 'hardware', 'gerät', 'geraet', 'tausch', 'austausch'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><rect x="2" y="6" width="20" height="12" rx="2"/><line x1="6" y1="14" x2="6" y2="14.01"/><line x1="10" y1="14" x2="10" y2="14.01"/></svg>', label: 'hardware'},
    {keys: ['dokumentation', 'protokoll', 'nachweis', 'beweis', 'screenshot', 'foto', 'aufzeichnung'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>', label: 'documentation'},
    {keys: ['anwalt', 'rechtsanwalt', 'klage', 'gericht', 'rechtlich', 'jurist', 'mahnung', 'frist'], icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>', label: 'legal'}
];

// Pre-compile word-boundary regexes for icon detection
var _iconRegexCache = {};
function _getIconRegex(keyword) {
    if (!_iconRegexCache[keyword]) {
        // Use word boundaries for single words, plain indexOf for multi-word phrases
        if (keyword.indexOf(' ') !== -1) {
            _iconRegexCache[keyword] = new RegExp(keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
        } else {
            _iconRegexCache[keyword] = new RegExp('(?:^|[\\s,;.!?()\\[\\]"\'/\\-])' + keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?:$|[\\s,;.!?()\\[\\]"\'/\\-])', 'i');
        }
    }
    return _iconRegexCache[keyword];
}

function detectIcon(title, description) {
    if (!title && !description) return null;
    var text = ' ' + ((title || '') + ' ' + (description || '')).toLowerCase() + ' ';
    for (var i = 0; i < INCIDENT_ICONS.length; i++) {
        var entry = INCIDENT_ICONS[i];
        for (var j = 0; j < entry.keys.length; j++) {
            if (_getIconRegex(entry.keys[j]).test(text)) {
                return entry;
            }
        }
    }
    return null;
}

function getIconByLabel(label) {
    if (!label) return null;
    for (var i = 0; i < INCIDENT_ICONS.length; i++) {
        if (INCIDENT_ICONS[i].label === label) return INCIDENT_ICONS[i];
    }
    return null;
}

function resolveIcon(incident) {
    if (incident.icon) return getIconByLabel(incident.icon);
    return detectIcon(incident.title, incident.description);
}

function renderIconPicker(selectedLabel) {
    var picker = document.getElementById('entry-icon-picker');
    var hiddenInput = document.getElementById('entry-icon-value');
    picker.innerHTML = '';
    // "None" button
    var noneBtn = document.createElement('button');
    noneBtn.type = 'button';
    noneBtn.className = 'icon-pick' + (!selectedLabel ? ' active' : '');
    noneBtn.title = T.icon_auto;
    noneBtn.innerHTML = '<span style="font-size:14px;color:var(--muted);">' + T.icon_auto.toLowerCase() + '</span>';
    noneBtn.onclick = function() {
        hiddenInput.value = '';
        picker.querySelectorAll('.icon-pick').forEach(function(b) { b.classList.remove('active'); });
        noneBtn.classList.add('active');
        updateModalIcon();
    };
    picker.appendChild(noneBtn);

    INCIDENT_ICONS.forEach(function(entry) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'icon-pick' + (selectedLabel === entry.label ? ' active' : '');
        btn.title = T['icon_' + entry.label] || entry.label;
        btn.innerHTML = entry.icon;
        btn.onclick = function() {
            hiddenInput.value = entry.label;
            picker.querySelectorAll('.icon-pick').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            updateModalIcon();
        };
        picker.appendChild(btn);
    });
}

var MONTH_NAMES = T.month_names || ['January', 'February', 'March', 'April', 'May', 'June',
                      'July', 'August', 'September', 'October', 'November', 'December'];

var _journalSearchQuery = '';
var _journalSearchTimer = null;
var _journalAllData = null;

function loadJournal(searchQuery) {
    var tableCard = document.getElementById('journal-table-card');
    var tbody = document.getElementById('journal-tbody');
    var empty = document.getElementById('journal-empty');
    var loading = document.getElementById('journal-loading');
    var deleteAllBtn = document.getElementById('btn-delete-all-entries');
    var searchWrap = document.getElementById('journal-search-wrap');
    var searchCount = document.getElementById('journal-search-count');
    loading.style.display = '';
    tbody.innerHTML = '';
    if (tableCard) tableCard.style.display = 'none';
    empty.style.display = 'none';
    if (deleteAllBtn) deleteAllBtn.style.display = 'none';
    var bulkToggle = document.getElementById('btn-bulk-toggle');
    if (bulkToggle) bulkToggle.style.display = 'none';
    if (searchCount) searchCount.textContent = '';
    /* Reset bulk selection on reload */
    _selectedEntryIds = [];
    var master = document.getElementById('journal-select-all');
    if (master) master.checked = false;
    var bulkBar = document.getElementById('journal-bulk-bar');
    if (bulkBar) bulkBar.style.display = 'none';

    var url = '/api/journal?limit=1000';
    if (searchQuery) url += '&search=' + encodeURIComponent(searchQuery);
    if (_activeIncidentFilter !== null) url += '&incident_id=' + _activeIncidentFilter;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            loading.style.display = 'none';
            if (!searchQuery) _journalAllData = data;
            if (!data || data.length === 0) {
                if (searchQuery) {
                    empty.textContent = T.search_no_results + ' "' + searchQuery + '"';
                    if (searchCount) searchCount.textContent = '0 ' + T.search_results;
                } else {
                    empty.textContent = T.no_incidents || 'No incidents logged yet.';
                }
                empty.style.display = '';
                if (searchWrap && !searchQuery) searchWrap.style.display = 'none';
                return;
            }
            _journalLoaded = true;
            if (searchWrap) searchWrap.style.display = '';
            if (deleteAllBtn && !searchQuery) deleteAllBtn.style.display = '';
            var bulkToggle = document.getElementById('btn-bulk-toggle');
            if (bulkToggle && !searchQuery) bulkToggle.style.display = '';
            if (searchQuery && searchCount) {
                searchCount.textContent = data.length + ' ' + (data.length !== 1 ? T.search_results : T.search_result);
            }
            renderJournalTable(data, searchQuery);
        })
        .catch(function() {
            loading.style.display = 'none';
            empty.textContent = T.network_error || 'Error';
            empty.style.display = '';
        });
}

function highlightText(text, query) {
    if (!query || !text) return escapeHtml(text);
    var escaped = escapeHtml(text);
    var lowerEscaped = escaped.toLowerCase();
    var lowerQuery = query.toLowerCase();
    var result = '';
    var lastIdx = 0;
    var idx = lowerEscaped.indexOf(lowerQuery);
    while (idx !== -1) {
        result += escaped.substring(lastIdx, idx);
        result += '<mark class="search-highlight">' + escaped.substring(idx, idx + lowerQuery.length) + '</mark>';
        lastIdx = idx + lowerQuery.length;
        idx = lowerEscaped.indexOf(lowerQuery, lastIdx);
    }
    result += escaped.substring(lastIdx);
    return result;
}

function renderJournalTable(data, searchQuery) {
    var table = document.getElementById('journal-table');
    var tbody = document.getElementById('journal-tbody');
    data.sort(function(a, b) {
        var va, vb;
        if (_journalSortCol === 'date') { va = a.date || ''; vb = b.date || ''; }
        else if (_journalSortCol === 'title') { va = (a.title || '').toLowerCase(); vb = (b.title || '').toLowerCase(); }
        else { va = (a.description || '').toLowerCase(); vb = (b.description || '').toLowerCase(); }
        if (va < vb) return _journalSortAsc ? -1 : 1;
        if (va > vb) return _journalSortAsc ? 1 : -1;
        return 0;
    });
    tbody.innerHTML = '';
    var lastMonthKey = '';
    var sortByDate = _journalSortCol === 'date';
    var q = searchQuery || '';
    data.forEach(function(inc) {
        // Month/Year grouping headers (only when sorted by date)
        if (sortByDate && inc.date) {
            var parts = inc.date.split('-');
            var monthKey = parts[0] + '-' + parts[1];
            if (monthKey !== lastMonthKey) {
                lastMonthKey = monthKey;
                var monthIdx = parseInt(parts[1], 10) - 1;
                var monthLabel = MONTH_NAMES[monthIdx] + ' ' + parts[0];
                var groupTr = document.createElement('tr');
                groupTr.className = 'journal-month-header';
                groupTr.innerHTML = '<td colspan="' + (_bulkMode ? 6 : 5) + '">' + monthLabel + '</td>';
                tbody.appendChild(groupTr);
            }
        }
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', inc.id);
        var isSelected = _selectedEntryIds.indexOf(inc.id) !== -1;
        if (isSelected) tr.classList.add('journal-row-selected');
        tr.onclick = function(e) {
            if (e.target.closest('.journal-check-cell')) return;
            openEntryModal(inc.id);
        };
        var desc = inc.description || '';
        if (desc.length > 80) desc = desc.substring(0, 80) + '\u2026';
        var clipCell = inc.attachment_count > 0 ? '&#128206; ' + inc.attachment_count : '';
        var iconMatch = resolveIcon(inc);
        var iconHtml = iconMatch ? iconMatch.icon : '<span class="incident-icon-placeholder"></span>';
        var titleHtml = q ? highlightText(inc.title, q) : escapeHtml(inc.title);
        var descHtml = q ? highlightText(desc, q) : escapeHtml(desc);
        var dateHtml = q ? highlightText(formatDateDE(inc.date), q) : formatDateDE(inc.date);
        tr.innerHTML =
            (_bulkMode ? '<td class="journal-check-cell"><input type="checkbox" class="journal-row-check" data-entry-id="' + inc.id + '"' + (isSelected ? ' checked' : '') + ' onclick="toggleEntrySelection(this, ' + inc.id + ')"></td>' : '') +
            '<td class="journal-icon-cell">' + iconHtml + '</td>' +
            '<td>' + dateHtml + '</td>' +
            '<td>' + titleHtml + '</td>' +
            '<td class="journal-desc journal-hide-mobile">' + descHtml + '</td>' +
            '<td class="journal-clip">' + clipCell + '</td>';
        tbody.appendChild(tr);
    });
    // Update sort indicators in header
    var ths = table.querySelectorAll('thead th[data-col]');
    for (var i = 0; i < ths.length; i++) {
        ths[i].className = ths[i].getAttribute('data-col') === _journalSortCol ? (_journalSortAsc ? 'sort-asc' : 'sort-desc') : '';
        // Preserve journal-hide-mobile on description column
        if (ths[i].getAttribute('data-col') === 'description') {
            ths[i].className = (ths[i].className ? ths[i].className + ' ' : '') + 'journal-hide-mobile';
        }
    }
    var tableCard = document.getElementById('journal-table-card');
    if (tableCard) tableCard.style.display = '';
}

(function() {
    var table = document.getElementById('journal-table');
    if (table) {
        table.addEventListener('click', function(e) {
            var th = e.target.closest ? e.target.closest('th[data-col]') : null;
            if (!th) return;
            var col = th.getAttribute('data-col');
            if (col === _journalSortCol) {
                _journalSortAsc = !_journalSortAsc;
            } else {
                _journalSortCol = col;
                _journalSortAsc = col === 'date' ? false : true;
            }
            loadJournal();
        });
    }
})();

/* ── Entry Modal ── */

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

function openEntryModal(entryId) {
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

    attachList.innerHTML = '';

    if (entryId) {
        titleEl.textContent = T.edit_entry || 'Edit Entry';
        deleteBtn.style.display = '';
        fetch('/api/journal/' + entryId)
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
                attachSection.style.display = '';
                modal.classList.add('open');
            });
    } else {
        titleEl.textContent = T.new_entry || 'New Entry';
        idEl.value = '';
        dateEl.value = todayStr();
        titleInput.value = '';
        descEl.value = '';
        iconVal.value = '';
        renderIconPicker('');
        updateModalIcon();
        populateIncidentSelect(_activeIncidentFilter > 0 ? _activeIncidentFilter : null);
        deleteBtn.style.display = 'none';
        attachSection.style.display = 'none';
        modal.classList.add('open');
    }
}

// Live icon update when typing title
(function() {
    var ti = document.getElementById('entry-title-input');
    if (ti) ti.addEventListener('input', updateModalIcon);
})();

function closeEntryModal() {
    document.getElementById('entry-modal').classList.remove('open');
}

function renderAttachments(attachments, container, incidentId) {
    container.innerHTML = '';
    attachments.forEach(function(att) {
        var item = document.createElement('div');
        item.className = 'attachment-item';
        var isImage = att.mime_type && att.mime_type.indexOf('image/') === 0;
        var thumbHtml = '';
        if (isImage) {
            thumbHtml = '<img class="attachment-thumb" src="/api/attachments/' + att.id + '" alt="">';
        } else if (att.mime_type === 'application/pdf') {
            thumbHtml = '<div class="attachment-icon">&#128196;</div>';
        } else {
            thumbHtml = '<div class="attachment-icon">&#128462;</div>';
        }
        item.innerHTML = thumbHtml +
            '<div class="attachment-info">' +
                '<span class="attachment-name">' + escapeHtml(att.filename) + '</span>' +
                '<div class="attachment-actions">' +
                    '<a href="/api/attachments/' + att.id + '" download title="Download">&#11015;</a>' +
                    '<button onclick="deleteAttachment(' + att.id + ', ' + incidentId + ')" title="Delete">&#128465;</button>' +
                '</div>' +
            '</div>';
        container.appendChild(item);
    });
}

function saveEntry() {
    var idEl = document.getElementById('entry-id');
    var dateVal = document.getElementById('entry-date').value;
    var titleVal = document.getElementById('entry-title-input').value.trim();
    var descVal = document.getElementById('entry-desc').value.trim();
    var entryId = idEl.value;

    if (!titleVal) {
        showToast(T.incident_title + ' required', 'error');
        return;
    }

    var iconVal = document.getElementById('entry-icon-value').value || '';
    var incidentSel = document.getElementById('entry-incident-select');
    var incidentIdVal = incidentSel ? incidentSel.value : '';
    var payload = JSON.stringify({date: dateVal, title: titleVal, description: descVal, icon: iconVal, incident_id: incidentIdVal ? parseInt(incidentIdVal) : null});
    var url = entryId ? '/api/journal/' + entryId : '/api/journal';
    var method = entryId ? 'PUT' : 'POST';

    fetch(url, {method: method, headers: {'Content-Type': 'application/json'}, body: payload})
        .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
        .then(function(res) {
            if (res.status >= 400) {
                showToast(res.data.error || 'Error', 'error');
                return;
            }
            loadJournal();
            loadIncidents();
            if (!entryId && res.data.id) {
                // New entry: switch modal to edit mode in-place (keep it open)
                idEl.value = res.data.id;
                document.getElementById('entry-modal-title').textContent = T.edit_entry || 'Edit Entry';
                document.getElementById('entry-delete-btn').style.display = '';
                document.getElementById('entry-attachments-section').style.display = '';
                showToast(T.saved || 'Saved', 'ok');
            } else {
                closeEntryModal();
            }
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

function deleteEntry() {
    var entryId = document.getElementById('entry-id').value;
    if (!entryId) return;
    if (!confirm(T.confirm_delete || 'Are you sure?')) return;
    fetch('/api/journal/' + entryId, {method: 'DELETE'})
        .then(function(r) { return r.json(); })
        .then(function() {
            closeEntryModal();
            loadJournal();
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

function handleEntryFileUpload(input) {
    var incidentId = document.getElementById('entry-id').value;
    if (!incidentId || !input.files || input.files.length === 0) return;
    var spinner = document.getElementById('entry-upload-spinner');
    var uploadBtn = document.getElementById('entry-upload-btn');
    spinner.style.display = 'inline';
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
            spinner.style.display = 'none';
            uploadBtn.disabled = false;
            input.value = '';
            // Reload attachments
            fetch('/api/journal/' + incidentId)
                .then(function(r) { return r.json(); })
                .then(function(inc) {
                    renderAttachments(inc.attachments || [], document.getElementById('entry-attachment-list'), incidentId);
                });
        })
        .catch(function() {
            spinner.style.display = 'none';
            uploadBtn.disabled = false;
            showToast(T.network_error || 'Error', 'error');
        });
}

function uploadOneFile(incidentId, file) {
    var formData = new FormData();
    formData.append('file', file);
    return fetch('/api/journal/' + incidentId + '/attachments', {method: 'POST', body: formData})
        .then(function(r) { return r.json().then(function(d) { return r.status >= 400 ? {error: d.error} : d; }); })
        .catch(function() { return {error: T.network_error || 'Upload failed'}; });
}

function deleteAttachment(attachmentId, incidentId) {
    fetch('/api/attachments/' + attachmentId, {method: 'DELETE'})
        .then(function(r) { return r.json(); })
        .then(function() {
            fetch('/api/journal/' + incidentId)
                .then(function(r) { return r.json(); })
                .then(function(inc) {
                    renderAttachments(inc.attachments || [], document.getElementById('entry-attachment-list'), incidentId);
                });
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

/* ── Import Modal ── */
var _importPreviewData = null;

function openImportModal() {
    var modal = document.getElementById('import-modal');
    document.getElementById('import-upload-zone').style.display = '';
    document.getElementById('import-loading').style.display = 'none';
    document.getElementById('import-preview').style.display = 'none';
    document.getElementById('import-footer').style.display = 'none';
    document.getElementById('import-file-input').value = '';
    _importPreviewData = null;
    modal.classList.add('open');
}

function closeImportModal() {
    document.getElementById('import-modal').classList.remove('open');
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
        showToast(T.import_file_unsupported, 'error');
        return;
    }
    if (file.size > 5 * 1024 * 1024) {
        showToast(T.import_file_too_large, 'error');
        return;
    }

    document.getElementById('import-upload-zone').style.display = 'none';
    document.getElementById('import-loading').style.display = '';

    var formData = new FormData();
    formData.append('file', file);

    fetch('/api/journal/import/preview', {method: 'POST', body: formData})
        .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
        .then(function(res) {
            document.getElementById('import-loading').style.display = 'none';
            if (res.status >= 400) {
                showToast(res.data.error || T.error_prefix, 'error');
                document.getElementById('import-upload-zone').style.display = '';
                return;
            }
            _importPreviewData = res.data;
            renderImportPreview(res.data);
        })
        .catch(function() {
            document.getElementById('import-loading').style.display = 'none';
            document.getElementById('import-upload-zone').style.display = '';
            showToast(T.network_error || 'Error', 'error');
        });
}

function renderImportPreview(data) {
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
                ' style="width:140px;padding:2px 4px;border:1px solid var(--accent);border-radius:4px;background:var(--bg);color:var(--fg);font-size:0.85em;"' +
                ' onchange="fixImportDate(this,' + i + ')">' +
                '<span class="import-skipped-badge">' + (T.import_no_date || 'no date') + '</span>';
        } else {
            dateCell = escapeHtml(row.date);
        }
        tr.innerHTML =
            '<td><input type="checkbox" class="import-row-cb" data-idx="' + i + '" ' + checked + '></td>' +
            '<td style="text-align:center;">' + iconHtml + '</td>' +
            '<td>' + dateCell + '</td>' +
            '<td>' + escapeHtml(row.title) + dupeBadge + '</td>' +
            '<td class="journal-hide-mobile">' + escapeHtml(desc) + '</td>';
        tbody.appendChild(tr);
    });

    document.getElementById('import-select-all').checked = true;
    document.getElementById('import-preview').style.display = '';
    document.getElementById('import-footer').style.display = '';
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
    }
}

function toggleImportAll(checked) {
    var cbs = document.querySelectorAll('.import-row-cb');
    for (var i = 0; i < cbs.length; i++) {
        cbs[i].checked = checked;
    }
}

function confirmImport() {
    if (!_importPreviewData) return;
    var cbs = document.querySelectorAll('.import-row-cb');
    var selectedRows = [];
    for (var i = 0; i < cbs.length; i++) {
        if (cbs[i].checked) {
            var idx = parseInt(cbs[i].getAttribute('data-idx'));
            var row = _importPreviewData.rows[idx];
            if (row && row.date) {
                selectedRows.push({
                    date: row.date,
                    title: row.title,
                    description: row.description
                });
            }
        }
    }
    if (selectedRows.length === 0) {
        showToast(T.import_no_selection, 'error');
        return;
    }

    var btn = document.getElementById('import-confirm-btn');
    btn.disabled = true;
    btn.textContent = T.import_importing;

    fetch('/api/journal/import/confirm', {
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

/* ── Delete All ── */
function deleteAllEntries() {
    var count = document.querySelectorAll('#journal-tbody tr').length;
    if (count === 0) return;
    if (!confirm(T.delete_all_confirm.replace('{n}', count))) return;
    var confirmation = prompt(T.delete_all_type_confirm);
    if (confirmation !== 'DELETE') {
        showToast(T.delete_all_cancelled, 'error');
        return;
    }
    fetch('/api/journal/batch', {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({all: true, confirm: 'DELETE_ALL'})
    })
        .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
        .then(function(res) {
            if (res.status >= 400) {
                showToast(res.data.error || T.delete_failed, 'error');
                return;
            }
            showToast(res.data.deleted + ' ' + T.delete_all_success, 'ok');
            loadJournal();
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

/* ── Incident Containers ── */
function loadIncidents() {
    fetch('/api/incidents')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _incidentsData = data || [];
            renderIncidentBar(_incidentsData);
        })
        .catch(function() { _incidentsData = []; });
}

function renderIncidentBar(incidents) {
    var bar = document.getElementById('incident-filter-bar');
    if (!bar) return;
    bar.innerHTML = '';
    bar.style.display = '';

    // "All" pill
    var totalCount = 0;
    incidents.forEach(function(inc) { totalCount += (inc.entry_count || 0); });
    var allPill = document.createElement('button');
    allPill.className = 'incident-pill' + (_activeIncidentFilter === null ? ' active' : '');
    allPill.innerHTML = (T.incident_filter_all || 'All');
    allPill.onclick = function() { filterByIncident(null); };
    bar.appendChild(allPill);

    // "Unassigned" pill
    var unPill = document.createElement('button');
    unPill.className = 'incident-pill' + (_activeIncidentFilter === 0 ? ' active' : '');
    unPill.innerHTML = (T.incident_filter_unassigned || 'Unassigned');
    unPill.onclick = function() { filterByIncident(0); };
    bar.appendChild(unPill);

    // Incident pills
    incidents.forEach(function(inc) {
        var pill = document.createElement('button');
        pill.className = 'incident-pill incident-pill-has-edit' + (_activeIncidentFilter === inc.id ? ' active' : '');
        var statusDot = '<span class="incident-pill-status incident-pill-status-' + inc.status + '"></span>';
        pill.innerHTML = statusDot + ' ' + escapeHtml(inc.name) + ' <span class="incident-pill-count">(' + (inc.entry_count || 0) + ')</span>' +
            '<span class="incident-pill-edit" title="' + (T.incident_edit || 'Edit') + '">&#9998;</span>';
        pill.onclick = function(e) {
            if (e.target.closest('.incident-pill-edit')) { e.stopPropagation(); openIncidentModal(inc.id); return; }
            filterByIncident(inc.id);
        };
        bar.appendChild(pill);
    });

    // "+" add pill
    var addPill = document.createElement('button');
    addPill.className = 'incident-pill incident-pill-add';
    addPill.innerHTML = '+';
    addPill.title = T.incident_new || 'New Incident';
    addPill.onclick = function() { openIncidentModal(); };
    bar.appendChild(addPill);
}

function filterByIncident(incidentId) {
    _activeIncidentFilter = incidentId;
    renderIncidentBar(_incidentsData);
    renderIncidentSummary(incidentId);
    loadJournal();
}

function renderIncidentSummary(incidentId) {
    var el = document.getElementById('incident-summary');
    if (!el) return;
    if (!incidentId || incidentId === 0) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }
    var inc = null;
    for (var i = 0; i < _incidentsData.length; i++) {
        if (_incidentsData[i].id === incidentId) { inc = _incidentsData[i]; break; }
    }
    if (!inc) { el.style.display = 'none'; return; }

    var statusLabel = T['incident_status_' + inc.status] || inc.status;
    var statusClass = 'incident-summary-status-' + inc.status;
    var dateRange = '';
    if (inc.start_date) {
        dateRange = formatDateDE(inc.start_date);
        if (inc.end_date) dateRange += ' \u2013 ' + formatDateDE(inc.end_date);
        else dateRange += ' \u2013 ' + (T.incident_status_open || 'ongoing').toLowerCase();
    }

    var html = '<div class="incident-summary-header">';
    html += '<div class="incident-summary-title">' + escapeHtml(inc.name) + '</div>';
    html += '<span class="incident-summary-badge ' + statusClass + '">' + statusLabel + '</span>';
    if (dateRange) html += '<span class="incident-summary-date">' + dateRange + '</span>';
    html += '<span class="incident-summary-count">' + (inc.entry_count || 0) + ' ' + (T.incident_entry_count || 'Entries') + '</span>';
    html += '<button class="incident-summary-edit" onclick="openIncidentModal(' + inc.id + ')" title="' + (T.incident_edit || 'Edit') + '">&#9998;</button>';
    html += '<button class="incident-summary-timeline-btn" onclick="openIncidentTimeline(' + inc.id + ')">' + (T.incident_view_timeline || 'View Timeline') + '</button>';
    html += '</div>';
    if (inc.description) {
        var desc = inc.description.length > 200 ? inc.description.substring(0, 200) + '\u2026' : inc.description;
        html += '<div class="incident-summary-desc">' + escapeHtml(desc) + '</div>';
    }
    el.innerHTML = html;
    el.style.display = '';
}

/* ── Incident Timeline ── */
var _timelineActive = false;
var _timelineChartInstance = null;

window.openIncidentTimeline = function(incidentId) {
    // Hide journal UI elements
    var tableCard = document.getElementById('journal-table-card');
    var searchWrap = document.getElementById('journal-search-wrap');
    var bulkBar = document.getElementById('journal-bulk-bar');
    var empty = document.getElementById('journal-empty');
    var deleteAllBtn = document.getElementById('btn-delete-all-entries');
    if (tableCard) tableCard.style.display = 'none';
    if (searchWrap) searchWrap.style.display = 'none';
    if (bulkBar) bulkBar.style.display = 'none';
    if (empty) empty.style.display = 'none';
    if (deleteAllBtn) deleteAllBtn.style.display = 'none';

    // Show timeline container with loading state
    var timelineView = document.getElementById('incident-timeline-view');
    timelineView.style.display = '';
    var header = document.getElementById('incident-timeline-header');
    header.innerHTML = '<div class="spinner" style="margin:20px auto;"></div>';

    _timelineActive = true;

    fetch('/api/incidents/' + incidentId + '/timeline')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                header.innerHTML = '<div class="incident-timeline-empty">' + escapeHtml(data.error) + '</div>';
                return;
            }
            renderIncidentTimeline(data);
        })
        .catch(function() {
            header.innerHTML = '<div class="incident-timeline-empty">' + (T.network_error || 'Error') + '</div>';
        });
};

window.closeIncidentTimeline = function() {
    var timelineView = document.getElementById('incident-timeline-view');
    timelineView.style.display = 'none';
    _timelineActive = false;

    // Destroy chart to free memory
    if (_timelineChartInstance) {
        _timelineChartInstance = null;
    }

    // Re-show journal
    loadJournal();
};

window.downloadIncidentPdf = function(incidentId, incidentName) {
    var btn = document.querySelector('.incident-timeline-pdf-btn');
    var origHtml = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.textContent = '\u23F3'; }
    fetch('/api/incidents/' + incidentId + '/report')
        .then(function(r) {
            if (!r.ok) throw new Error('Failed');
            return r.blob();
        })
        .then(function(blob) {
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'DOCSight_Beschwerde_' + incidentName.replace(/[^a-zA-Z0-9]/g, '_') + '_' + new Date().toISOString().slice(0, 10) + '.pdf';
            a.click();
            URL.revokeObjectURL(a.href);
        })
        .catch(function() {
            alert(T.network_error || 'Error generating report');
        })
        .finally(function() {
            if (btn) { btn.disabled = false; btn.innerHTML = origHtml; }
        });
};

function renderIncidentTimeline(data) {
    var inc = data.incident;
    var entries = data.entries || [];
    var timeline = data.timeline || [];
    var bnetz = data.bnetz || [];

    // -- 1. Header Card --
    var header = document.getElementById('incident-timeline-header');
    var statusLabel = T['incident_status_' + inc.status] || inc.status;
    var statusClass = 'incident-summary-status-' + inc.status;

    var dateRange = '';
    var durationText = '';
    if (inc.start_date) {
        dateRange = formatDateDE(inc.start_date);
        if (inc.end_date) {
            dateRange += ' \u2013 ' + formatDateDE(inc.end_date);
            var d1 = new Date(inc.start_date), d2 = new Date(inc.end_date);
            var diffDays = Math.ceil((d2 - d1) / (1000 * 60 * 60 * 24));
            durationText = diffDays + ' ' + (T.incident_duration_days || 'days');
        } else {
            dateRange += ' \u2013 ' + (T.incident_duration_ongoing || 'ongoing');
        }
    }

    var hHtml = '<div class="incident-timeline-header-title">';
    hHtml += escapeHtml(inc.name);
    hHtml += ' <span class="incident-summary-badge ' + statusClass + '">' + statusLabel + '</span>';
    hHtml += '</div>';
    hHtml += '<div class="incident-timeline-meta">';
    if (dateRange) {
        hHtml += '<span class="incident-timeline-meta-item">';
        hHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>';
        hHtml += dateRange;
        hHtml += '</span>';
    }
    if (durationText) {
        hHtml += '<span class="incident-timeline-meta-item">';
        hHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
        hHtml += durationText;
        hHtml += '</span>';
    }
    hHtml += '<span class="incident-timeline-meta-item">';
    hHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    hHtml += entries.length + ' ' + (T.incident_entry_count || 'Entries');
    hHtml += '</span>';
    hHtml += '</div>';
    if (inc.description) {
        hHtml += '<div class="incident-timeline-desc">' + escapeHtml(inc.description) + '</div>';
    }
    hHtml += '<button class="incident-timeline-pdf-btn" onclick="downloadIncidentPdf(' + inc.id + ', \'' + escapeHtml(inc.name).replace(/'/g, "\\'") + '\')">';
    hHtml += '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> ';
    hHtml += (T.incident_download_pdf || 'Download PDF Report');
    hHtml += '</button>';
    header.innerHTML = hHtml;

    // -- 2. Journal Entries as Cards --
    var entriesDiv = document.getElementById('incident-timeline-entries');
    if (entries.length === 0) {
        entriesDiv.style.display = 'none';
    } else {
        entriesDiv.style.display = '';
        var eHtml = '<div class="incident-timeline-section-title">';
        eHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2z"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>';
        eHtml += (T.incident_journal_entries || 'Journal Entries');
        eHtml += '</div>';
        eHtml += '<div class="incident-timeline-entries-grid">';
        entries.forEach(function(entry) {
            var icon = _getEntryIcon(entry);
            eHtml += '<div class="incident-timeline-entry" onclick="openEntryModal(' + entry.id + ')">';
            eHtml += '<div class="incident-timeline-entry-icon">' + icon + '</div>';
            eHtml += '<div class="incident-timeline-entry-body">';
            eHtml += '<div class="incident-timeline-entry-date">' + formatDateDE(entry.date) + '</div>';
            eHtml += '<div class="incident-timeline-entry-title">' + escapeHtml(entry.title) + '</div>';
            if (entry.description) {
                var desc = entry.description.length > 120 ? entry.description.substring(0, 120) + '\u2026' : entry.description;
                eHtml += '<div class="incident-timeline-entry-desc">' + escapeHtml(desc) + '</div>';
            }
            if (entry.attachment_count) {
                eHtml += '<div class="incident-timeline-entry-att">\uD83D\uDCCE ' + entry.attachment_count + '</div>';
            }
            eHtml += '</div></div>';
        });
        eHtml += '</div>';
        entriesDiv.innerHTML = eHtml;
    }

    // -- 3. Signal Timeline Chart --
    var chartCard = document.getElementById('incident-timeline-chart-card');
    if (timeline.length === 0) {
        chartCard.querySelector('.incident-timeline-chart-wrap').innerHTML =
            '<div class="incident-timeline-empty">' + (T.timeline_no_data || 'No signal data for this period') + '</div>';
    } else {
        chartCard.querySelector('.incident-timeline-chart-wrap').innerHTML =
            '<canvas id="incident-timeline-canvas"></canvas>';
        _renderTimelineChart(timeline);
    }

    // -- 4. Signal Timeline Table --
    var signalsDiv = document.getElementById('incident-timeline-signals');
    if (timeline.length === 0) {
        signalsDiv.style.display = 'none';
    } else {
        signalsDiv.style.display = '';
        _renderTimelineTable(timeline);
    }

    // -- 5. BNetzA Section --
    var bnetzDiv = document.getElementById('incident-timeline-bnetz');
    if (bnetz.length === 0) {
        bnetzDiv.style.display = 'none';
    } else {
        bnetzDiv.style.display = '';
        var bHtml = '<div class="incident-timeline-section-title">';
        bHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>';
        bHtml += (T.incident_bnetz_measurements || 'BNetzA Measurements');
        bHtml += '</div>';
        bnetz.forEach(function(m) {
            var hasDeviation = m.verdict_download === 'deviation' || m.verdict_upload === 'deviation';
            var verdictText = hasDeviation ? (T.bnetz_verdict_deviation || 'Deviation') : (T.bnetz_verdict_ok || 'OK');
            var verdictClass = hasDeviation ? 'val-crit' : 'val-good';
            bHtml += '<div class="incident-timeline-bnetz-item">';
            bHtml += '<span>' + formatDateDE(m.date) + '</span>';
            bHtml += '<span>\u2193 ' + (m.download_measured_avg || 0).toFixed(1) + ' / ' + (m.download_max_tariff || 0).toFixed(0) + ' Mbps</span>';
            bHtml += '<span>\u2191 ' + (m.upload_measured_avg || 0).toFixed(1) + ' / ' + (m.upload_max_tariff || 0).toFixed(0) + ' Mbps</span>';
            bHtml += '<span class="incident-timeline-bnetz-verdict ' + verdictClass + '">' + verdictText + '</span>';
            bHtml += '</div>';
        });
        bnetzDiv.innerHTML = bHtml;
    }

    // Re-initialize Lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function _getEntryIcon(entry) {
    // Try to find icon from label
    if (entry.icon) {
        for (var i = 0; i < INCIDENT_ICONS.length; i++) {
            if (INCIDENT_ICONS[i].label === entry.icon) return INCIDENT_ICONS[i].icon;
        }
    }
    // Auto-detect from title
    var title = (entry.title || '').toLowerCase();
    for (var i = 0; i < INCIDENT_ICONS.length; i++) {
        for (var j = 0; j < INCIDENT_ICONS[i].keys.length; j++) {
            if (title.indexOf(INCIDENT_ICONS[i].keys[j]) !== -1) return INCIDENT_ICONS[i].icon;
        }
    }
    // Default icon
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
}

function _renderTimelineChart(data) {
    var canvas = document.getElementById('incident-timeline-canvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    var W = rect.width;
    var H = 280;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    var pad = { top: 20, right: 60, bottom: 40, left: 60 };
    var plotW = W - pad.left - pad.right;
    var plotH = H - pad.top - pad.bottom;

    var modem = data.filter(function(d) { return d.source === 'modem'; });
    var speedtest = data.filter(function(d) { return d.source === 'speedtest'; });
    var events = data.filter(function(d) { return d.source === 'event'; });

    if (modem.length === 0 && speedtest.length === 0) {
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
        ctx.font = '13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(T.timeline_no_data || 'No signal data', W / 2, H / 2);
        return;
    }

    // Time range
    var allTs = data.map(function(d) { return new Date(d.timestamp).getTime(); });
    var tMin = Math.min.apply(null, allTs);
    var tMax = Math.max.apply(null, allTs);
    if (tMin === tMax) tMax = tMin + 86400000;

    function xScale(ts) { return pad.left + (ts - tMin) / (tMax - tMin) * plotW; }

    // SNR axis
    var snrValues = modem.map(function(d) { return d.ds_snr_min || 0; }).filter(function(v) { return v > 0; });
    var snrMin = snrValues.length ? Math.floor(Math.min.apply(null, snrValues) - 2) : 20;
    var snrMax = snrValues.length ? Math.ceil(Math.max.apply(null, snrValues) + 2) : 45;
    function ySnr(v) { return pad.top + plotH - (v - snrMin) / (snrMax - snrMin) * plotH; }

    // Speed axis (right)
    var dlValues = speedtest.map(function(d) { return d.download_mbps || 0; });
    var speedMax = dlValues.length ? Math.ceil(Math.max.apply(null, dlValues) * 1.1) : 500;
    if (speedMax < 10) speedMax = 100;
    function yDl(v) { return pad.top + plotH - v / speedMax * plotH; }

    var style = getComputedStyle(document.documentElement);
    var textColor = style.getPropertyValue('--muted').trim() || '#888';
    var gridColor = style.getPropertyValue('--input-border').trim() || '#333';
    var goodColor = style.getPropertyValue('--good').trim() || '#4caf50';
    var warnColor = style.getPropertyValue('--warn').trim() || '#ff9800';
    var critColor = style.getPropertyValue('--crit').trim() || '#f44336';
    var accentColor = style.getPropertyValue('--accent').trim() || '#a855f7';
    var uploadColor = '#06b6d4';

    // Grid
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 0.5;
    ctx.setLineDash([2, 4]);
    for (var s = Math.ceil(snrMin); s <= snrMax; s += 5) {
        var y = ySnr(s);
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + plotW, y); ctx.stroke();
    }
    ctx.setLineDash([]);

    // Time axis labels
    ctx.fillStyle = textColor;
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    var tRange = tMax - tMin;
    var labelCount = Math.min(8, Math.floor(plotW / 80));
    for (var i = 0; i <= labelCount; i++) {
        var t = tMin + tRange * i / labelCount;
        var d = new Date(t);
        var label;
        if (tRange > 172800000) { // > 2 days
            label = (d.getMonth() + 1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        } else {
            label = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        }
        ctx.fillText(label, xScale(t), H - pad.bottom + 18);
    }

    // Left axis labels (SNR)
    if (modem.length > 0) {
        ctx.textAlign = 'right';
        ctx.fillStyle = accentColor;
        for (var s = Math.ceil(snrMin); s <= snrMax; s += 5) {
            ctx.fillText(s + ' dB', pad.left - 6, ySnr(s) + 3);
        }
    }

    // Right axis labels (Speed)
    if (speedtest.length > 0) {
        ctx.textAlign = 'left';
        ctx.fillStyle = goodColor;
        var speedStep = speedMax > 400 ? 100 : speedMax > 200 ? 50 : 25;
        for (var v = 0; v <= speedMax; v += speedStep) {
            ctx.fillText(v + ' Mbps', pad.left + plotW + 6, yDl(v) + 3);
        }
    }

    // SNR line (modem)
    if (modem.length > 1) {
        var sorted = modem.slice().sort(function(a, b) {
            return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
        });
        ctx.strokeStyle = accentColor;
        ctx.lineWidth = 2;
        ctx.beginPath();
        sorted.forEach(function(d, i) {
            var x = xScale(new Date(d.timestamp).getTime());
            var y = ySnr(d.ds_snr_min || snrMin);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
    }

    // Speed dots
    speedtest.forEach(function(d) {
        var x = xScale(new Date(d.timestamp).getTime());
        // Download dot
        ctx.fillStyle = goodColor;
        ctx.beginPath();
        ctx.arc(x, yDl(d.download_mbps || 0), 4, 0, Math.PI * 2);
        ctx.fill();
        // Upload dot (smaller)
        ctx.fillStyle = uploadColor;
        ctx.beginPath();
        ctx.arc(x, yDl(d.upload_mbps || 0), 3, 0, Math.PI * 2);
        ctx.fill();
    });

    // Event markers
    events.forEach(function(d) {
        var x = xScale(new Date(d.timestamp).getTime());
        var col = d.severity === 'critical' ? critColor : d.severity === 'warning' ? warnColor : textColor;
        ctx.strokeStyle = col;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
        // Triangle marker
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.moveTo(x, pad.top - 2);
        ctx.lineTo(x - 4, pad.top - 8);
        ctx.lineTo(x + 4, pad.top - 8);
        ctx.closePath();
        ctx.fill();
    });

    // Legend
    var legendY = H - 6;
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'left';
    var lx = pad.left;
    if (modem.length > 0) {
        ctx.fillStyle = accentColor;
        ctx.fillRect(lx, legendY - 6, 12, 3);
        ctx.fillStyle = textColor;
        ctx.fillText('SNR', lx + 16, legendY);
        lx += 50;
    }
    if (speedtest.length > 0) {
        ctx.fillStyle = goodColor;
        ctx.beginPath(); ctx.arc(lx + 4, legendY - 4, 3, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = textColor;
        ctx.fillText('DL', lx + 12, legendY);
        lx += 36;
        ctx.fillStyle = uploadColor;
        ctx.beginPath(); ctx.arc(lx + 4, legendY - 4, 3, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = textColor;
        ctx.fillText('UL', lx + 12, legendY);
        lx += 36;
    }
    if (events.length > 0) {
        ctx.fillStyle = warnColor;
        ctx.beginPath();
        ctx.moveTo(lx + 4, legendY - 2);
        ctx.lineTo(lx, legendY - 8);
        ctx.lineTo(lx + 8, legendY - 8);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = textColor;
        ctx.fillText(T.timeline_source_event || 'Event', lx + 12, legendY);
    }
}

function _renderTimelineTable(data) {
    var div = document.getElementById('incident-timeline-signals');

    var healthLabels = {
        good: T.health_good || 'Good',
        marginal: T.health_marginal || 'Marginal',
        poor: T.health_poor || 'Poor',
        critical: T.health_critical || 'Critical'
    };

    var tHtml = '<div class="incident-timeline-section-title">';
    tHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
    tHtml += (T.correlation_timeline || 'Unified Timeline');
    tHtml += '</div>';
    tHtml += '<table><thead><tr>';
    tHtml += '<th>' + (T.timestamp || 'Timestamp') + '</th>';
    tHtml += '<th>Source</th>';
    tHtml += '<th>Details</th>';
    tHtml += '</tr></thead><tbody>';

    // Show newest first, limit to 200
    var sorted = data.slice().reverse();
    var modemTransitions = {};
    var lastHealth = null;
    var chrono = data.slice().sort(function(a, b) {
        return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
    });
    for (var i = 0; i < chrono.length; i++) {
        if (chrono[i].source !== 'modem') continue;
        var h = chrono[i].health || 'unknown';
        if (h !== lastHealth) { modemTransitions[chrono[i].timestamp] = true; lastHealth = h; }
    }

    var count = 0;
    for (var i = 0; i < sorted.length && count < 200; i++) {
        var e = sorted[i];
        if (e.source === 'modem' && !modemTransitions[e.timestamp]) continue;

        var ts = escapeHtml(e.timestamp.replace('T', ' '));
        var srcBadge = '';
        var details = '';

        if (e.source === 'modem') {
            srcBadge = '<span class="timeline-source-badge timeline-source-badge-modem">' + (T.timeline_source_modem || 'Modem') + '</span>';
            var hLabel = healthLabels[e.health] || e.health;
            details = '<span class="st-health-badge health-' + (e.health || 'unknown') + '">' + hLabel + '</span>';
            details += ' SNR ' + (e.ds_snr_min != null ? e.ds_snr_min + ' dB' : '-');
            details += ' | Power ' + (e.ds_power_avg != null ? e.ds_power_avg + ' dBmV' : '-');
        } else if (e.source === 'speedtest') {
            srcBadge = '<span class="timeline-source-badge timeline-source-badge-speedtest">' + (T.timeline_source_speedtest || 'Speedtest') + '</span>';
            details = (e.download_mbps ? e.download_mbps.toFixed(1) + ' / ' + (e.upload_mbps || 0).toFixed(1) + ' Mbps' : '');
            if (e.ping_ms) details += ' | Ping ' + e.ping_ms + ' ms';
        } else if (e.source === 'event') {
            srcBadge = '<span class="timeline-source-badge timeline-source-badge-event">' + (T.timeline_source_event || 'Event') + '</span>';
            details = escapeHtml(e.message || '');
        }

        tHtml += '<tr><td style="white-space:nowrap;font-size:0.82em;">' + ts + '</td>';
        tHtml += '<td>' + srcBadge + '</td>';
        tHtml += '<td style="font-size:0.85em;">' + details + '</td></tr>';
        count++;
    }

    tHtml += '</tbody></table>';
    div.innerHTML = tHtml;
}

function renderContainerIconPicker(selectedLabel) {
    var picker = document.getElementById('incident-container-icon-picker');
    var hiddenInput = document.getElementById('incident-container-icon-value');
    picker.innerHTML = '';
    var noneBtn = document.createElement('button');
    noneBtn.type = 'button';
    noneBtn.className = 'icon-pick' + (!selectedLabel ? ' active' : '');
    noneBtn.title = T.icon_auto || 'Auto';
    noneBtn.innerHTML = '<span style="font-size:14px;color:var(--muted);">' + (T.icon_auto || 'auto').toLowerCase() + '</span>';
    noneBtn.onclick = function() {
        hiddenInput.value = '';
        picker.querySelectorAll('.icon-pick').forEach(function(b) { b.classList.remove('active'); });
        noneBtn.classList.add('active');
    };
    picker.appendChild(noneBtn);
    INCIDENT_ICONS.forEach(function(entry) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'icon-pick' + (selectedLabel === entry.label ? ' active' : '');
        btn.title = T['icon_' + entry.label] || entry.label;
        btn.innerHTML = entry.icon;
        btn.onclick = function() {
            hiddenInput.value = entry.label;
            picker.querySelectorAll('.icon-pick').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
        };
        picker.appendChild(btn);
    });
}

function openIncidentModal(incidentId) {
    var modal = document.getElementById('incident-container-modal');
    var titleEl = document.getElementById('incident-container-modal-title');
    var idEl = document.getElementById('incident-container-id');
    var nameEl = document.getElementById('incident-container-name');
    var statusEl = document.getElementById('incident-container-status');
    var startEl = document.getElementById('incident-container-start');
    var endEl = document.getElementById('incident-container-end');
    var descEl = document.getElementById('incident-container-desc');
    var iconVal = document.getElementById('incident-container-icon-value');
    var deleteBtn = document.getElementById('incident-container-delete-btn');
    var countSection = document.getElementById('incident-container-entry-count-section');
    var countEl = document.getElementById('incident-container-entry-count');

    if (incidentId) {
        titleEl.textContent = T.incident_edit || 'Edit Incident';
        deleteBtn.style.display = '';
        fetch('/api/incidents/' + incidentId)
            .then(function(r) { return r.json(); })
            .then(function(inc) {
                idEl.value = inc.id;
                nameEl.value = inc.name;
                statusEl.value = inc.status;
                startEl.value = inc.start_date || '';
                endEl.value = inc.end_date || '';
                descEl.value = inc.description || '';
                iconVal.value = inc.icon || '';
                renderContainerIconPicker(inc.icon || '');
                if (inc.entry_count !== undefined) {
                    countEl.textContent = inc.entry_count;
                    countSection.style.display = '';
                } else {
                    countSection.style.display = 'none';
                }
                modal.classList.add('open');
            });
    } else {
        titleEl.textContent = T.incident_new || 'New Incident';
        idEl.value = '';
        nameEl.value = '';
        statusEl.value = 'open';
        startEl.value = todayStr();
        endEl.value = '';
        descEl.value = '';
        iconVal.value = '';
        renderContainerIconPicker('');
        deleteBtn.style.display = 'none';
        countSection.style.display = 'none';
        modal.classList.add('open');
    }
}

function closeIncidentModal() {
    document.getElementById('incident-container-modal').classList.remove('open');
}

function saveIncident() {
    var idEl = document.getElementById('incident-container-id');
    var nameVal = document.getElementById('incident-container-name').value.trim();
    var statusVal = document.getElementById('incident-container-status').value;
    var startVal = document.getElementById('incident-container-start').value;
    var endVal = document.getElementById('incident-container-end').value;
    var descVal = document.getElementById('incident-container-desc').value.trim();
    var iconVal = document.getElementById('incident-container-icon-value').value || '';
    var incidentId = idEl.value;

    if (!nameVal) {
        showToast((T.incident_name || 'Name') + ' required', 'error');
        return;
    }

    var payload = JSON.stringify({name: nameVal, description: descVal, status: statusVal, start_date: startVal, end_date: endVal, icon: iconVal});
    var url = incidentId ? '/api/incidents/' + incidentId : '/api/incidents';
    var method = incidentId ? 'PUT' : 'POST';

    fetch(url, {method: method, headers: {'Content-Type': 'application/json'}, body: payload})
        .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
        .then(function(res) {
            if (res.status >= 400) {
                showToast(res.data.error || 'Error', 'error');
                return;
            }
            closeIncidentModal();
            loadIncidents();
            loadJournal();
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

function deleteIncident() {
    var incidentId = document.getElementById('incident-container-id').value;
    if (!incidentId) return;
    if (!confirm(T.incident_delete_confirm || 'Delete this incident? Entries will become unassigned.')) return;
    fetch('/api/incidents/' + incidentId, {method: 'DELETE'})
        .then(function(r) { return r.json(); })
        .then(function() {
            closeIncidentModal();
            _activeIncidentFilter = null;
            loadIncidents();
            loadJournal();
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

/* ── Bulk Selection & Assignment ── */

function toggleBulkMode() {
    if (_bulkMode) {
        exitBulkMode();
    } else {
        _bulkMode = true;
        var label = document.getElementById('btn-bulk-toggle-label');
        var btn = document.getElementById('btn-bulk-toggle');
        label.textContent = T.bulk_cancel || 'Cancel';
        btn.classList.add('btn-bulk-active');
        // Insert checkbox header column
        var headRow = document.getElementById('journal-thead-row');
        var th = document.createElement('th');
        th.className = 'journal-check-col';
        th.style.width = '36px';
        th.innerHTML = '<input type="checkbox" id="journal-select-all" onclick="toggleSelectAll(this)" title="' + (T.bulk_select_all || 'Select All') + '">';
        headRow.insertBefore(th, headRow.firstChild);
        // Re-render table with checkboxes
        if (_journalAllData) renderJournalTable(_journalAllData, _journalSearchQuery);
    }
}

function exitBulkMode() {
    _bulkMode = false;
    _selectedEntryIds = [];
    var label = document.getElementById('btn-bulk-toggle-label');
    var btn = document.getElementById('btn-bulk-toggle');
    if (label) label.textContent = T.bulk_select || 'Select';
    if (btn) btn.classList.remove('btn-bulk-active');
    // Remove checkbox header column
    var headRow = document.getElementById('journal-thead-row');
    var checkTh = headRow.querySelector('.journal-check-col');
    if (checkTh) headRow.removeChild(checkTh);
    // Re-render table without checkboxes
    var bulkBar = document.getElementById('journal-bulk-bar');
    if (bulkBar) bulkBar.style.display = 'none';
    if (_journalAllData) renderJournalTable(_journalAllData, _journalSearchQuery);
}

function toggleEntrySelection(checkbox, entryId) {
    var idx = _selectedEntryIds.indexOf(entryId);
    if (checkbox.checked && idx === -1) {
        _selectedEntryIds.push(entryId);
    } else if (!checkbox.checked && idx !== -1) {
        _selectedEntryIds.splice(idx, 1);
    }
    var row = checkbox.closest('tr');
    if (row) row.classList.toggle('journal-row-selected', checkbox.checked);
    updateBulkBar();
}

function toggleSelectAll(masterCheckbox) {
    var checkboxes = document.querySelectorAll('.journal-row-check');
    _selectedEntryIds = [];
    for (var i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = masterCheckbox.checked;
        var row = checkboxes[i].closest('tr');
        if (row) row.classList.toggle('journal-row-selected', masterCheckbox.checked);
        if (masterCheckbox.checked) {
            _selectedEntryIds.push(parseInt(checkboxes[i].getAttribute('data-entry-id')));
        }
    }
    updateBulkBar();
}

function clearBulkSelection() {
    _selectedEntryIds = [];
    var checkboxes = document.querySelectorAll('.journal-row-check');
    for (var i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = false;
        var row = checkboxes[i].closest('tr');
        if (row) row.classList.remove('journal-row-selected');
    }
    var master = document.getElementById('journal-select-all');
    if (master) master.checked = false;
    updateBulkBar();
}

function updateBulkBar() {
    var bar = document.getElementById('journal-bulk-bar');
    var count = _selectedEntryIds.length;
    if (count === 0) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = '';
    var countEl = document.getElementById('journal-bulk-count');
    countEl.textContent = count + ' ' + (count === 1 ? (T.entry_selected || 'entry selected') : (T.entries_selected || 'entries selected'));
    populateBulkIncidentSelect();
}

function populateBulkIncidentSelect() {
    var sel = document.getElementById('journal-bulk-incident-select');
    var prev = sel.value;
    sel.innerHTML = '<option value="" disabled selected>' + (T.incident_assign || 'Assign to Incident') + '\u2026</option>';
    _incidentsData.forEach(function(inc) {
        var opt = document.createElement('option');
        opt.value = inc.id;
        opt.textContent = inc.name + ' (' + (T['incident_status_' + inc.status] || inc.status) + ')';
        sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
}

function bulkAssign() {
    var sel = document.getElementById('journal-bulk-incident-select');
    var incidentId = sel.value;
    if (!incidentId) {
        showToast(T.bulk_select_incident || 'Select an incident first', 'warning');
        return;
    }
    if (_selectedEntryIds.length === 0) return;
    fetch('/api/incidents/' + incidentId + '/assign', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({entry_ids: _selectedEntryIds})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast((data.updated || 0) + ' ' + (T.entries_assigned || 'entries assigned'), 'success');
        exitBulkMode();
        loadIncidents();
        loadJournal();
    })
    .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

function bulkUnassign() {
    if (_selectedEntryIds.length === 0) return;
    fetch('/api/journal/unassign', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({entry_ids: _selectedEntryIds})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast((data.updated || 0) + ' ' + (T.entries_unassigned || 'entries unassigned'), 'success');
        exitBulkMode();
        loadIncidents();
        loadJournal();
    })
    .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

/* ── Export Dropdown ── */
function toggleExportDropdown(e) {
    e.stopPropagation();
    var dd = document.getElementById('journal-export-dropdown');
    dd.classList.toggle('open');
}
function exportJournal(fmt) {
    var dd = document.getElementById('journal-export-dropdown');
    dd.classList.remove('open');
    var url = '/api/journal/export?format=' + fmt;
    if (_activeIncidentFilter !== null && _activeIncidentFilter > 0) {
        url += '&incident_id=' + _activeIncidentFilter;
    }
    window.location.href = url;
}
document.addEventListener('click', function() {
    var dd = document.getElementById('journal-export-dropdown');
    if (dd) dd.classList.remove('open');
});

/* Expose Journal functions for HTML onclick/onchange handlers */
window.openEntryModal = openEntryModal;
window.closeEntryModal = closeEntryModal;
window.saveEntry = saveEntry;
window.deleteEntry = deleteEntry;
window.deleteAttachment = deleteAttachment;
window.handleEntryFileUpload = handleEntryFileUpload;
window.loadJournal = loadJournal;
window.openImportModal = openImportModal;
window.closeImportModal = closeImportModal;
window.handleImportFile = handleImportFile;
window.confirmImport = confirmImport;
window.toggleImportAll = toggleImportAll;
window.fixImportDate = fixImportDate;
window.deleteAllEntries = deleteAllEntries;
window.clearJournalSearch = clearJournalSearch;
window.loadIncidents = loadIncidents;
window.openIncidentModal = openIncidentModal;
window.closeIncidentModal = closeIncidentModal;
window.saveIncident = saveIncident;
window.deleteIncident = deleteIncident;
window.filterByIncident = filterByIncident;
window.toggleBulkMode = toggleBulkMode;
window.toggleEntrySelection = toggleEntrySelection;
window.toggleSelectAll = toggleSelectAll;
window.clearBulkSelection = clearBulkSelection;
window.bulkAssign = bulkAssign;
window.bulkUnassign = bulkUnassign;
window.toggleExportDropdown = toggleExportDropdown;
window.exportJournal = exportJournal;

/* ── Journal Search ── */
function clearJournalSearch() {
    var input = document.getElementById('journal-search-input');
    input.value = '';
    _journalSearchQuery = '';
    document.getElementById('journal-search-clear').style.display = 'none';
    document.getElementById('journal-search-count').textContent = '';
    loadJournal();
}

(function() {
    var input = document.getElementById('journal-search-input');
    if (!input) return;
    input.addEventListener('input', function() {
        var val = input.value.trim();
        var clearBtn = document.getElementById('journal-search-clear');
        clearBtn.style.display = val ? '' : 'none';
        if (_journalSearchTimer) clearTimeout(_journalSearchTimer);
        _journalSearchTimer = setTimeout(function() {
            _journalSearchQuery = val;
            if (val.length === 0) {
                loadJournal();
            } else if (val.length >= 2) {
                loadJournal(val);
            }
        }, 300);
    });
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            clearJournalSearch();
            input.blur();
        }
    });
})();
