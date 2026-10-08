/* ── Journal cases ──
   The case overview (cards, filter bar, summary), the guided case steps, and
   the dialog that creates or edits a case. Loaded with the journal tab; the
   timeline a case opens into lives in journal-timeline.js. */

/* ── Case overview ──
   One card per case (open ones first, at most six): status, window, notes, the
   evidence state as ready / stale / missing and the next useful step. Continue
   opens the case's evidence checklist; Open shows its timeline. */
var CASE_CARD_LIMIT = 6;
var CASE_BADGE = {open: 'badge-warn', resolved: 'badge-good', escalated: 'badge-crit'};

function _caseText(key, fallback, values) {
    var text = T[key] || fallback;
    Object.keys(values || {}).forEach(function(name) { text = text.replace('{' + name + '}', values[name]); });
    return text;
}

/* Cases for the overview: open ones first, then the newest start, at most CASE_CARD_LIMIT. */
function journalCaseOrder(incidents) {
    return (incidents || []).slice().sort(function(a, b) {
        return (a.status === 'open' ? 0 : 1) - (b.status === 'open' ? 0 : 1) ||
            String(b.start_date || '').localeCompare(String(a.start_date || ''));
    }).slice(0, CASE_CARD_LIMIT);
}

/* Evidence state of a case from its checklist. The report item is left out:
   exporting is the case's last step, not a piece of evidence. */
function journalCaseEvidence(payload) {
    var items = (payload.items || []).filter(function(item) { return item.key !== 'report'; });
    var first = function(status) { return items.filter(function(item) { return item.status === status; })[0] || null; };
    var count = function(status) { return items.filter(function(item) { return item.status === status; }).length; };
    return {items: items, ready: count('present'), stale: count('stale'), missing: count('missing'),
        firstMissing: first('missing'), firstStale: first('stale')};
}

function _caseEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = text;
    return el;
}

function _caseWindow(inc) {
    if (!inc.start_date) return T.event_case_no_window || 'No window yet';
    return formatDocsightTime(inc.start_date, 'date') + ' – ' +
        (inc.end_date ? formatDocsightTime(inc.end_date, 'date') : (T.event_case_running || 'ongoing'));
}

function renderCaseCards(incidents) {
    var root = document.getElementById('case-cards');
    if (!root) return;
    root.textContent = '';
    var cases = journalCaseOrder(incidents);
    root.hidden = !cases.length || _timelineActive;
    var withEvidence = !!document.getElementById('view-evidence');
    cases.forEach(function(inc) {
        var card = _caseEl('article', 'card case-card');
        card.setAttribute('data-case-id', inc.id);
        var head = _caseEl('div', 'case-card-head');
        head.appendChild(_caseEl('h3', 'case-card-name', inc.name));
        head.appendChild(_caseEl('span', 'badge ' + (CASE_BADGE[inc.status] || ''), T['incident_status_' + inc.status] || inc.status));
        card.appendChild(head);
        var notes = inc.entry_count === 1
            ? (T.case_notes_one || '1 note')
            : _caseText('case_notes_many', '{count} notes', {count: inc.entry_count || 0});
        card.appendChild(_caseEl('p', 'case-card-meta', _caseWindow(inc) + ' · ' + notes));
        var lights = _caseEl('p', 'case-card-lights');
        lights.hidden = true;
        card.appendChild(lights);
        var foot = _caseEl('div', 'case-card-foot');
        var next = _caseEl('span', 'case-card-next');
        foot.appendChild(next);
        var open = inc.status === 'open';
        var button = _caseEl('button', 'btn btn-sm ' + (open ? 'btn-primary' : 'btn-secondary'),
            open ? (T.case_continue || 'Continue') : (T.case_open || 'Open'));
        button.type = 'button';
        button.addEventListener('click', function() { openIncidentTimeline(inc.id); });
        foot.appendChild(button);
        card.appendChild(foot);
        root.appendChild(card);
        if (withEvidence && inc.start_date) _loadCaseEvidence(inc, lights, next);
    });
}

function _loadCaseEvidence(inc, lights, next) {
    fetch(docsightUrl('/api/evidence/checklist?incident_id=' + encodeURIComponent(inc.id)))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(payload) {
            if (!payload) return;
            var evidence = journalCaseEvidence(payload);
            var counts = [
                ['ready', evidence.ready, 'case_lights_ready', '{count} ready'],
                ['stale', evidence.stale, 'case_lights_stale', '{count} stale'],
                ['missing', evidence.missing, 'case_lights_missing', '{count} missing']
            ];
            counts.forEach(function(entry) {
                if (!entry[1]) return;
                var light = _caseEl('span', 'case-light case-light-' + entry[0]);
                light.appendChild(_caseEl('span', 'case-light-dot'));
                light.appendChild(document.createTextNode(_caseText(entry[2], entry[3], {count: entry[1]})));
                lights.appendChild(light);
            });
            lights.hidden = !lights.childNodes.length;
            var missing = evidence.firstMissing;
            var stale = evidence.firstStale;
            var label = function(item) { return T[item.label_key] || item.key; };
            next.textContent = missing ? _caseText('case_next_missing', 'Missing: {item}', {item: label(missing)})
                : stale ? _caseText('case_next_stale', 'Outdated: {item}', {item: label(stale)})
                : (T.case_next_ready || 'Evidence ready');
        })
        .catch(function() {});
}

function renderIncidentBar(incidents) {
    var bar = document.getElementById('incident-filter-bar');
    if (!bar) return;
    bar.innerHTML = '';
    bar.hidden = false;

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
        el.hidden = true;
        el.innerHTML = '';
        return;
    }
    var inc = null;
    for (var i = 0; i < _incidentsData.length; i++) {
        if (_incidentsData[i].id === incidentId) { inc = _incidentsData[i]; break; }
    }
    if (!inc) { el.hidden = true; return; }

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
    html += '<span class="incident-summary-evidence">' + (T.incident_linked_evidence || 'Linked evidence') + '</span>';
    var incidentArgs = ' data-action-args="[' + inc.id + ']"';
    html += '<button type="button" class="incident-summary-edit" data-action="openIncidentModal"' + incidentArgs + ' title="' + escapeHtmlAttribute(T.incident_edit || 'Edit') + '">&#9998;</button>';
    html += '<button type="button" class="incident-summary-timeline-btn" data-action="openIncidentTimeline"' + incidentArgs + '>' + escapeHtml(T.incident_view_timeline || 'View Timeline') + '</button>';
    html += '<button type="button" class="incident-summary-report-btn" data-action="openIncidentTimeline"' + incidentArgs + '>' + escapeHtml(T.incident_build_report || 'Build report') + '</button>';
    html += '</div>';
    if (inc.description) {
        var desc = inc.description.length > 200 ? inc.description.substring(0, 200) + '\u2026' : inc.description;
        html += '<div class="incident-summary-desc">' + escapeHtml(desc) + '</div>';
    }
    el.innerHTML = html;
    el.hidden = false;
}

/* ── Case steps: window → evidence → export ──
   The step that needs attention is marked; missing or stale evidence offers
   the action that fills it in, right in the case. */
function _caseStep(number, state, text) {
    var step = _caseEl('li', 'case-step case-step-' + state);
    var mark = _caseEl('span', 'case-step-mark', state === 'done' ? '\u2713' : String(number));
    mark.setAttribute('aria-hidden', 'true');
    step.appendChild(mark);
    step.appendChild(_caseEl('span', 'case-step-text', text));
    if (state === 'now') step.setAttribute('aria-current', 'step');
    var sr = _caseEl('span', 'sr-only', ' (' + (state === 'done' ? (T.case_step_done || 'done') : state === 'now' ? (T.case_step_now || 'current step') : (T.case_step_later || 'later')) + ')');
    step.appendChild(sr);
    return step;
}

function _caseEvidenceAction(item, inc) {
    var action = item.action || {};
    var key = action.action || action.view;
    if (!key) return null;
    var button = _caseEl('button', 'btn btn-ghost btn-sm', T['docsight.evidence.action.' + key] || T['docsight.evidence.action.review'] || 'Open related view');
    button.type = 'button';
    button.addEventListener('click', function() {
        if (action.action === 'add_note') openEntryModal(null, inc.id);
        else if (action.view && typeof switchView === 'function') switchView(action.view);
    });
    return button;
}

function renderCaseSteps(inc) {
    var root = document.getElementById('incident-timeline-steps');
    if (!root) return;
    root.textContent = '';
    // A checklist that arrives after another case was opened is dropped.
    var token = {};
    root._caseStepsToken = token;
    // Without the evidence module there is nothing to collect: window, then export.
    var withEvidence = !!document.getElementById('view-evidence');
    var exportNumber = withEvidence ? 3 : 2;
    var list = _caseEl('ol', 'case-steps');
    root.appendChild(list);
    root.hidden = false;
    if (!inc.start_date) {
        list.appendChild(_caseStep(1, 'now', T.case_step_window_missing || 'Window · not set yet'));
        if (withEvidence) list.appendChild(_caseStep(2, 'later', T.case_step_evidence_plain || 'Evidence'));
        list.appendChild(_caseStep(exportNumber, 'later', T.case_step_export || 'Export · report or PDF'));
        var setWindow = _caseEl('button', 'btn btn-primary btn-sm case-steps-action', T.case_step_set_window || 'Set window');
        setWindow.type = 'button';
        setWindow.addEventListener('click', function() { openIncidentModal(inc.id); });
        root.appendChild(setWindow);
        return;
    }
    list.appendChild(_caseStep(1, 'done', _caseText('case_step_window', 'Window · {range}', {range: _caseWindow(inc)})));
    if (!withEvidence) {
        list.appendChild(_caseStep(exportNumber, 'now', T.case_step_export || 'Export · report or PDF'));
        return;
    }
    var evidenceStep = _caseStep(2, 'now', T.case_step_evidence_plain || 'Evidence');
    var exportStep = _caseStep(3, 'later', T.case_step_export || 'Export · report or PDF');
    list.appendChild(evidenceStep);
    list.appendChild(exportStep);
    fetch(docsightUrl('/api/evidence/checklist?incident_id=' + encodeURIComponent(inc.id)))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(payload) {
            if (!payload || !_timelineActive || root._caseStepsToken !== token) return;
            var evidence = journalCaseEvidence(payload);
            var items = evidence.items;
            var ready = evidence.ready;
            var open = evidence.stale + evidence.missing;
            var total = ready + open;
            evidenceStep.replaceWith(_caseStep(2, open ? 'now' : 'done',
                _caseText('case_step_evidence', 'Evidence · {ready} of {total} ready', {ready: ready, total: total})));
            exportStep.replaceWith(_caseStep(3, open ? 'later' : 'now', T.case_step_export || 'Export · report or PDF'));
            var details = _caseEl('details', 'case-evidence-details');
            details.open = open > 0;
            details.appendChild(_caseEl('summary', 'case-evidence-toggle', T.case_evidence_details || 'Evidence sources'));
            var grid = _caseEl('ul', 'case-evidence');
            items.forEach(function(item) {
                if (item.status === 'not_applicable' || item.status === 'unavailable') return;
                var row = _caseEl('li', 'case-evidence-item');
                row.appendChild(_caseEl('span', 'case-evidence-name', T[item.label_key] || item.key));
                var actionButton = item.status === 'present' ? null : _caseEvidenceAction(item, inc);
                var badge = _caseEl('span', 'badge ' + ({present: 'badge-good', stale: 'badge-warn', missing: 'badge-crit'}[item.status] || 'badge-muted'),
                    T['docsight.evidence.status.' + item.status] || item.status);
                row.appendChild(badge);
                if (actionButton) row.appendChild(actionButton);
                grid.appendChild(row);
            });
            details.appendChild(grid);
            var checklist = _caseEl('a', 'case-evidence-checklist', T.case_open_checklist || 'Open the full evidence checklist');
            checklist.href = '#evidence?case=' + encodeURIComponent(inc.id);
            details.appendChild(checklist);
            root.appendChild(details);
        })
        .catch(function() {});
}

function renderContainerIconPicker(selectedLabel) {
    var picker = document.getElementById('incident-container-icon-picker');
    var hiddenInput = document.getElementById('incident-container-icon-value');
    picker.innerHTML = '';
    function markSelected(selectedButton) {
        picker.querySelectorAll('.icon-pick').forEach(function(b) {
            b.classList.remove('active');
            b.setAttribute('aria-pressed', 'false');
        });
        selectedButton.classList.add('active');
        selectedButton.setAttribute('aria-pressed', 'true');
    }
    var noneBtn = document.createElement('button');
    noneBtn.type = 'button';
    noneBtn.className = 'icon-pick' + (!selectedLabel ? ' active' : '');
    noneBtn.title = T.icon_auto || 'Auto';
    noneBtn.setAttribute('aria-pressed', !selectedLabel ? 'true' : 'false');
    noneBtn.innerHTML = '<span class="icon-pick-symbol">' + AUTO_ICON + '</span><span class="icon-pick-label">' + (T.icon_auto || 'Auto') + '</span>';
    noneBtn.onclick = function() {
        hiddenInput.value = '';
        markSelected(noneBtn);
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
    var emptyEvidenceSection = document.getElementById('incident-container-empty-evidence-section');
    var countEl = document.getElementById('incident-container-entry-count');
    var saveBtn = document.getElementById('incident-container-save-btn');

    if (incidentId) {
        titleEl.textContent = T.incident_edit || 'Edit Incident';
        if (saveBtn) saveBtn.textContent = T.incident_update_action || 'Update incident';
        deleteBtn.hidden = false;
        fetch(docsightUrl('/api/incidents/' + incidentId))
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
                    countSection.hidden = false;
                    if (emptyEvidenceSection) emptyEvidenceSection.hidden = true;
                } else {
                    countSection.hidden = true;
                    if (emptyEvidenceSection) emptyEvidenceSection.hidden = false;
                }
                window.DOCSightModal.open(modal);
            });
    } else {
        titleEl.textContent = T.incident_new || 'New Incident';
        if (saveBtn) saveBtn.textContent = T.incident_create_action || 'Create incident';
        idEl.value = '';
        nameEl.value = '';
        statusEl.value = 'open';
        startEl.value = todayStr();
        endEl.value = '';
        descEl.value = '';
        iconVal.value = '';
        renderContainerIconPicker('');
        deleteBtn.hidden = true;
        countSection.hidden = true;
        if (emptyEvidenceSection) emptyEvidenceSection.hidden = false;
        window.DOCSightModal.open(modal);
    }
}

function openIncidentReportFromModal() {
    var incidentId = document.getElementById('incident-container-id').value;
    if (!incidentId) return;
    closeIncidentModal();
    openIncidentTimeline(parseInt(incidentId, 10));
}

function closeIncidentModal() {
    window.DOCSightModal.close('incident-container-modal');
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
    var url = docsightUrl(incidentId ? '/api/incidents/' + incidentId : '/api/incidents');
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
            if (_timelineActive && _timelineIncidentId) openIncidentTimeline(_timelineIncidentId);
            else loadJournal();
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

function deleteIncident() {
    var incidentId = document.getElementById('incident-container-id').value;
    if (!incidentId) return;
    docsightConfirm({
        title: T.delete_incident || 'Delete',
        message: T.incident_delete_confirm || 'Delete this incident? Entries will become unassigned.',
        confirmText: T.delete_incident || 'Delete',
        cancelText: T.cancel || 'Cancel',
        danger: true
    }).then(function(confirmed) {
        if (!confirmed) return null;
        return fetch(docsightUrl('/api/incidents/' + incidentId), {method: 'DELETE'});
    })
        .then(function(r) { return r ? r.json() : null; })
        .then(function(res) {
            if (!res) return;
            closeIncidentModal();
            _activeIncidentFilter = null;
            loadIncidents();
            loadJournal();
        })
        .catch(function() { showToast(T.network_error || 'Error', 'error'); });
}

/* Expose case functions for data-action handlers */
window.openIncidentModal = openIncidentModal;
window.closeIncidentModal = closeIncidentModal;
window.saveIncident = saveIncident;
window.deleteIncident = deleteIncident;
window.filterByIncident = filterByIncident;
