/* ── Journal module ─────────────────────────────────────────────
   Incident Journal list, entry dialog, Bulk Selection, Search, Export.
   The import dialog lives in js/journal-import.js, the case timeline in
   js/journal-timeline.js, case cards, steps and the case dialog in
   js/journal-cases.js
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
var _timelineActive = false; // a case is open as a timeline (journal-timeline.js)
var _timelineIncidentId = null;

window.initJournalView = function() {
    if (!document.getElementById('view-journal')) return;
    if (_timelineActive) closeIncidentTimeline();
    loadIncidents();
    loadJournal();
};

var AUTO_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/><path d="M20 2v4"/><path d="M22 4h-4"/><circle cx="4" cy="20" r="2"/></svg>';

var INCIDENT_ICONS = [
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/></svg>', label: 'phone'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>', label: 'technician'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>', label: 'outage'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>', label: 'mail'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>', label: 'complaint'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>', label: 'contract'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>', label: 'measurement'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-4h6v4"/></svg>', label: 'authority'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>', label: 'billing'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><rect x="2" y="6" width="20" height="12" rx="2"/><line x1="6" y1="14" x2="6" y2="14.01"/><line x1="10" y1="14" x2="10" y2="14.01"/></svg>', label: 'hardware'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>', label: 'documentation'},
    {icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="incident-icon"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>', label: 'legal'}
];

// Category keywords come from the journal catalogs: the UI language plus English
// and German, because entries are often written or imported in another language.
var _iconKeywords = {};
var _iconKeywordsLoading = null;

function loadIconKeywords() {
    if (!_iconKeywordsLoading) {
        var lang = document.documentElement.lang || '';
        _iconKeywordsLoading = fetch(docsightUrl('/api/journal/icon-keywords' + (lang ? '?lang=' + encodeURIComponent(lang) : '')))
            .then(function(r) { return r.ok ? r.json() : {}; })
            .then(function(data) { _iconKeywords = data || {}; })
            .catch(function() { _iconKeywords = {}; });
    }
    return _iconKeywordsLoading;
}

// Longer keywords also match inside words (compounds, inflected forms); short
// ones must start a word so they do not hit unrelated longer words.
var _iconWordStartCache = {};
function _iconKeywordMatches(text, keyword) {
    if (keyword.length >= 5) return text.indexOf(keyword) !== -1;
    if (!_iconWordStartCache[keyword]) {
        var escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        _iconWordStartCache[keyword] = new RegExp('(?:^|[^\\p{L}\\p{N}])' + escaped, 'u');
    }
    return _iconWordStartCache[keyword].test(text);
}

function detectIcon(title, description) {
    var text = ((title || '') + ' ' + (description || '')).toLowerCase();
    if (!text.trim()) return null;
    for (var i = 0; i < INCIDENT_ICONS.length; i++) {
        var keywords = _iconKeywords[INCIDENT_ICONS[i].label] || [];
        for (var j = 0; j < keywords.length; j++) {
            if (_iconKeywordMatches(text, keywords[j])) return INCIDENT_ICONS[i];
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

function _getEntryIcon(entry) {
    var match = resolveIcon(entry);
    if (match) return match.icon;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
}

function renderIconPicker(selectedLabel) {
    var picker = document.getElementById('entry-icon-picker');
    var hiddenInput = document.getElementById('entry-icon-value');
    picker.innerHTML = '';
    function markSelected(selectedButton) {
        picker.querySelectorAll('.icon-pick').forEach(function(b) {
            b.classList.remove('active');
            b.setAttribute('aria-pressed', 'false');
        });
        selectedButton.classList.add('active');
        selectedButton.setAttribute('aria-pressed', 'true');
    }
    // "None" button
    var noneBtn = document.createElement('button');
    noneBtn.type = 'button';
    noneBtn.className = 'icon-pick' + (!selectedLabel ? ' active' : '');
    noneBtn.title = T.icon_auto;
    noneBtn.setAttribute('aria-pressed', !selectedLabel ? 'true' : 'false');
    noneBtn.innerHTML = '<span class="icon-pick-symbol">' + AUTO_ICON + '</span><span class="icon-pick-label">' + T.icon_auto + '</span>';
    noneBtn.onclick = function() {
        hiddenInput.value = '';
        markSelected(noneBtn);
        updateModalIcon();
    };
    picker.appendChild(noneBtn);

    INCIDENT_ICONS.forEach(function(entry) {
        var btn = document.createElement('button');
        var label = T['icon_' + entry.label] || entry.label;
        btn.type = 'button';
        btn.className = 'icon-pick' + (selectedLabel === entry.label ? ' active' : '');
        btn.title = label;
        btn.setAttribute('aria-pressed', selectedLabel === entry.label ? 'true' : 'false');
        btn.innerHTML = '<span class="icon-pick-symbol">' + entry.icon + '</span><span class="icon-pick-label">' + label + '</span>';
        btn.onclick = function() {
            hiddenInput.value = entry.label;
            markSelected(btn);
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
var _journalPendingDeletes = {};

function loadJournal(searchQuery) {
    var tableCard = document.getElementById('journal-table-card');
    var tbody = document.getElementById('journal-tbody');
    var empty = document.getElementById('journal-empty');
    var loading = document.getElementById('journal-loading');
    var deleteAllBtn = document.getElementById('journal-more-actions');
    var searchWrap = document.getElementById('journal-search-wrap');
    var searchCount = document.getElementById('journal-search-count');
    loading.hidden = false;
    tbody.innerHTML = '';
    if (tableCard) tableCard.hidden = true;
    DOCSightEmptyState.hide(empty);
    if (deleteAllBtn) deleteAllBtn.hidden = true;
    var bulkToggle = document.getElementById('btn-bulk-toggle');
    if (bulkToggle) bulkToggle.hidden = true;
    if (searchCount) searchCount.textContent = '';
    /* Reset bulk selection on reload */
    _selectedEntryIds = [];
    var master = document.getElementById('journal-select-all');
    if (master) master.checked = false;
    var bulkBar = document.getElementById('journal-bulk-bar');
    if (bulkBar) bulkBar.hidden = true;

    var url = docsightUrl('/api/journal?limit=1000');
    if (searchQuery) url += '&search=' + encodeURIComponent(searchQuery);
    if (_activeIncidentFilter !== null) url += '&incident_id=' + _activeIncidentFilter;

    // Icons are detected while rendering, so the keywords load alongside the entries.
    Promise.all([fetch(url).then(function(r) { return r.json(); }), loadIconKeywords()])
        .then(function(results) {
            // Entries waiting out their Undo toast are already gone from the user's view.
            var data = (results[0] || []).filter(function(entry) { return !_journalPendingDeletes[String(entry.id)]; });
            loading.hidden = true;
            if (!searchQuery) _journalAllData = data;
            if (!data || data.length === 0) {
                if (searchQuery && searchCount) searchCount.textContent = '0 ' + T.search_results;
                _showJournalEmpty(empty, searchQuery);
                if (searchWrap && !searchQuery) searchWrap.hidden = true;
                return;
            }
            _journalLoaded = true;
            if (searchWrap) searchWrap.hidden = false;
            if (deleteAllBtn && !searchQuery) deleteAllBtn.hidden = false;
            var bulkToggle = document.getElementById('btn-bulk-toggle');
            if (bulkToggle && !searchQuery) bulkToggle.hidden = false;
            if (searchQuery && searchCount) {
                searchCount.textContent = data.length + ' ' + (data.length !== 1 ? T.search_results : T.search_result);
            }
            renderJournalTable(data, searchQuery);
        })
        .catch(function() {
            loading.hidden = true;
            DOCSightEmptyState.showError(empty, {retry: function() { loadJournal(searchQuery); }});
        });
}

/* Empty because of a search, because the selected case has no entries yet,
   or because nothing was logged so far; each offers its own way forward. */
function _showJournalEmpty(empty, searchQuery) {
    if (searchQuery) {
        DOCSightEmptyState.show(empty, {
            icon: 'clipboard-list',
            title: (T.search_no_results || 'No results for') + ' "' + searchQuery + '"',
            text: T.journal_empty_search_text,
            action: {label: T.journal_empty_search_action || 'Clear search', onClick: clearJournalSearch}
        });
    } else if (_activeIncidentFilter !== null) {
        DOCSightEmptyState.show(empty, {
            icon: 'folder-open',
            title: T.journal_empty_case_title || 'No entries in this case',
            text: T.journal_empty_case_text,
            action: {label: T.journal_empty_case_action || 'Show all entries', onClick: function() { filterByIncident(null); }},
            glossary: 'incident_journal'
        });
    } else {
        DOCSightEmptyState.show(empty, {
            icon: 'clipboard-list',
            title: T.journal_empty_title || 'No entries yet',
            text: T.no_incidents,
            action: {label: T.new_entry || 'New Entry', onClick: function() { openEntryModal(); }},
            glossary: 'incident_journal'
        });
    }
}

function escapeHtmlAttribute(value) {
    return escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
                groupTr.className = 'journal-month-header dt-detail';
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
            (_bulkMode ? '<td class="journal-check-cell" data-label="' + escapeHtmlAttribute(T.bulk_select || 'Select') + '"><input type="checkbox" class="journal-row-check" data-entry-id="' + inc.id + '"' + (isSelected ? ' checked' : '') + ' data-action="toggleEntrySelection" data-action-pass="element" data-action-args="[' + inc.id + ']"></td>' : '') +
            '<td class="journal-icon-cell dt-lead" aria-hidden="true">' + iconHtml + '</td>' +
            '<td class="journal-date-cell" data-label="' + escapeHtmlAttribute(T.incident_date || 'Date') + '">' + dateHtml + '</td>' +
            '<td class="journal-title-cell dt-primary">' + titleHtml + '</td>' +
            '<td class="journal-desc journal-hide-mobile" data-label="' + escapeHtmlAttribute(T.incident_description || 'Description') + '">' + descHtml + '</td>' +
            '<td class="journal-clip" data-label="' + escapeHtmlAttribute(T.attachments || 'Attachments') + '">' + clipCell + '</td>';
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
    if (tableCard) tableCard.hidden = false;
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

/* ── Delete All ── */
function deleteAllEntries() {
    closeMoreActions();
    var count = document.querySelectorAll('#journal-tbody tr').length;
    if (count === 0) return;
    docsightConfirm({
        title: T.delete_all || 'Delete all entries',
        message: T.delete_all_confirm.replace('{n}', count),
        confirmText: T.delete_incident || 'Delete',
        cancelText: T.cancel || 'Cancel',
        danger: true,
        requireText: 'DELETE',
        requireLabel: T.delete_all_type_confirm || 'Type DELETE to confirm'
    }).then(function(confirmed) {
        if (!confirmed) return null;
        return fetch(docsightUrl('/api/journal/batch'), {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({all: true, confirm: 'DELETE_ALL'})
        });
    })
        .then(function(r) { return r ? r.json().then(function(d) { return {status: r.status, data: d}; }) : null; })
        .then(function(res) {
            if (!res) return;
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
    Promise.all([fetch(docsightUrl('/api/incidents')).then(function(r) { return r.json(); }), loadIconKeywords()])
        .then(function(results) {
            _incidentsData = results[0] || [];
            renderIncidentBar(_incidentsData);
            renderCaseCards(_incidentsData);
        })
        .catch(function() { _incidentsData = []; });
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
        th.innerHTML = '<input type="checkbox" id="journal-select-all" data-action="toggleSelectAll" data-action-pass="element" title="' + escapeHtmlAttribute(T.bulk_select_all || 'Select All') + '">';
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
    if (bulkBar) bulkBar.hidden = true;
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
        bar.hidden = true;
        return;
    }
    bar.hidden = false;
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
    fetch(docsightUrl('/api/incidents/' + incidentId + '/assign'), {
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
    fetch(docsightUrl('/api/journal/unassign'), {
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
    var url = docsightUrl('/api/journal/export?format=' + fmt);
    if (_activeIncidentFilter !== null && _activeIncidentFilter > 0) {
        url += '&incident_id=' + _activeIncidentFilter;
    }
    window.location.href = url;
}
/* ── More actions menu (Delete All) ── */
function closeMoreActions() {
    var dd = document.getElementById('journal-more-dropdown');
    var toggle = document.getElementById('journal-more-toggle');
    if (dd) dd.classList.remove('open');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
}
function toggleMoreActions(e) {
    e.stopPropagation();
    var dd = document.getElementById('journal-more-dropdown');
    var open = !dd.classList.contains('open');
    dd.classList.toggle('open', open);
    e.currentTarget.setAttribute('aria-expanded', open ? 'true' : 'false');
}
document.addEventListener('click', function() {
    var dd = document.getElementById('journal-export-dropdown');
    if (dd) dd.classList.remove('open');
    closeMoreActions();
});
document.addEventListener('keydown', function(e) {
    var dd = document.getElementById('journal-more-dropdown');
    if (e.key === 'Escape' && dd && dd.classList.contains('open')) {
        closeMoreActions();
        document.getElementById('journal-more-toggle').focus();
    }
});

/* Controls that need the click event or their own element are bound here;
   the rest use data-action attributes. */
(function() {
    var exportToggle = document.querySelector('.journal-export-wrapper > .btn-new-entry');
    if (exportToggle) exportToggle.addEventListener('click', toggleExportDropdown);
    var moreToggle = document.getElementById('journal-more-toggle');
    if (moreToggle) moreToggle.addEventListener('click', toggleMoreActions);
    var entryFiles = document.getElementById('entry-file-input');
    if (entryFiles) entryFiles.addEventListener('change', function() { handleEntryFileUpload(this); });
})();

/* Expose Journal functions for data-action handlers */
window.openEntryModal = openEntryModal;
window.closeEntryModal = closeEntryModal;
window.saveEntry = saveEntry;
window.deleteEntry = deleteEntry;
window.deleteAttachment = deleteAttachment;
window.handleEntryFileUpload = handleEntryFileUpload;
window.loadJournal = loadJournal;
window.deleteAllEntries = deleteAllEntries;
window.toggleMoreActions = toggleMoreActions;
window.clearJournalSearch = clearJournalSearch;
window.loadIncidents = loadIncidents;
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
    document.getElementById('journal-search-clear').hidden = true;
    document.getElementById('journal-search-count').textContent = '';
    loadJournal();
}

(function() {
    var input = document.getElementById('journal-search-input');
    if (!input) return;
    input.addEventListener('input', function() {
        var val = input.value.trim();
        var clearBtn = document.getElementById('journal-search-clear');
        clearBtn.hidden = !val;
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
