/* -- Guided Evidence Journey Module -- */

var _evidenceInitialized = false;
var _evidenceLastPayload = null;
var _evidenceCopyResetTimer = null;
var _evidenceRequestSeq = 0;

function _evidenceT(key, fallback) {
    return (window.T && window.T[key]) || fallback;
}

function _evidenceEscape(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(ch) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[ch];
    });
}

function _evidenceSafeStatus(status) {
    return {
        present: 'present',
        stale: 'stale',
        missing: 'missing',
        optional: 'optional',
        not_applicable: 'not_applicable',
        unavailable: 'unavailable'
    }[status] || 'missing';
}

function _evidenceToIso(value) {
    if (!value) return '';
    return value.length === 16 ? value + ':00' : value;
}

function _evidenceTimeZone() {
    return typeof DOCSIGHT_TIME_ZONE !== 'undefined' ? DOCSIGHT_TIME_ZONE : undefined;
}

/* Wall-clock value for the datetime-local inputs, in the configured time zone. */
function _evidenceLocal(ms, roundUp) {
    return DOCSightBrowserContracts.localInputValue(ms, _evidenceTimeZone(), roundUp);
}

/* Quick ranges in the configured time zone; returns [from, to] input values. */
function _evidenceQuickRange(kind, nowMs) {
    var hour = 3600000;
    if (kind === 'last7d') return [_evidenceLocal(nowMs - 7 * 24 * hour, false), _evidenceLocal(nowMs, true)];
    if (kind === 'yesterday_evening') {
        var yesterday = _evidenceLocal(nowMs - 24 * hour, false).slice(0, 10);
        return [yesterday + 'T18:00', yesterday + 'T23:00'];
    }
    return [_evidenceLocal(nowMs - 24 * hour, false), _evidenceLocal(nowMs, true)];
}

function _evidenceSetWindow(from, to, rangeKind) {
    var caseSelect = document.getElementById('evidence-incident-id');
    if (caseSelect) caseSelect.value = '';
    document.getElementById('evidence-from').value = from;
    document.getElementById('evidence-to').value = to;
    _evidenceMarkRange(rangeKind || null);
}

function _evidenceMarkRange(kind) {
    document.querySelectorAll('.evidence-chip[data-evidence-range]').forEach(function(chip) {
        chip.setAttribute('aria-pressed', chip.dataset.evidenceRange === kind ? 'true' : 'false');
    });
}

function _evidenceCaseLabel(incident) {
    var status = _evidenceT('incident_status_' + incident.status, incident.status || '');
    var start = incident.start_date ? formatDocsightTime(incident.start_date, 'date') : '';
    var end = incident.end_date ? formatDocsightTime(incident.end_date, 'date') : _evidenceT('incident_duration_ongoing', 'ongoing');
    return incident.name + ' \u00b7 ' + status + (start ? ' \u00b7 ' + start + ' \u2013 ' + end : '');
}

/* Fills the case picker: open cases first, then the most recent ones. */
function _evidenceLoadCases() {
    var caseSelect = document.getElementById('evidence-incident-id');
    if (!caseSelect) return Promise.resolve();
    return fetch(docsightUrl('/api/incidents'))
        .then(function(response) { return response.ok ? response.json() : []; })
        .catch(function() { return []; })
        .then(function(incidents) {
            var list = (Array.isArray(incidents) ? incidents : []).filter(function(incident) { return incident.start_date; });
            list.sort(function(a, b) {
                var openA = a.status === 'open' ? 0 : 1;
                var openB = b.status === 'open' ? 0 : 1;
                return openA - openB || String(b.start_date).localeCompare(String(a.start_date));
            });
            var selected = caseSelect.value;
            while (caseSelect.options.length > 1) caseSelect.remove(1);
            list.forEach(function(incident) {
                var option = document.createElement('option');
                option.value = String(incident.id);
                option.textContent = _evidenceCaseLabel(incident);
                caseSelect.appendChild(option);
            });
            caseSelect.value = selected;
        });
}

function _evidenceStatusLabel(status) {
    var safeStatus = _evidenceSafeStatus(status);
    return _evidenceT('docsight.evidence.status.' + safeStatus, safeStatus.replace('_', ' '));
}

function _evidenceStatusIcon(status) {
    var safeStatus = _evidenceSafeStatus(status);
    return {
        present: 'check-circle-2',
        stale: 'clock-3',
        missing: 'circle-alert',
        optional: 'circle-dot',
        not_applicable: 'ban',
        unavailable: 'circle-off'
    }[safeStatus] || 'circle-help';
}

function _evidenceActionLabel(item) {
    var view = item.action && item.action.view;
    var action = item.action && item.action.action;
    return _evidenceT('docsight.evidence.action.' + (action || view || 'review'), 'Open related view');
}

function _evidenceReportScope(payload) {
    if (!payload || !payload.window) return null;
    return {
        window: payload.window,
        items: payload.items,
        summary: payload.summary,
        incident_id: payload.window.incident_id,
        changeWindow: function() {
            if (typeof switchView === 'function') switchView('evidence');
            window.requestAnimationFrame(function() {
                var focusId = payload.window.kind === 'incident' ? 'evidence-incident-id' : 'evidence-from';
                var target = document.getElementById(focusId);
                if (target) target.focus({preventScroll: false});
            });
        }
    };
}

function _evidenceSourceLabel(source) {
    return _evidenceT('docsight.evidence.source.' + source.key, String(source.key || '').replace(/_/g, ' '));
}

function _evidenceRenderSourceBreakdown(item) {
    if (!item.sources || !item.sources.length) return '';
    return '<div class="evidence-source-list">' + item.sources.map(function(source) {
        var status = _evidenceSafeStatus(source.status);
        var count = typeof source.count === 'number' && source.count > 0
            ? '<span class="evidence-source-count">' + _evidenceEscape(source.count) + '</span>'
            : '';
        return '<div class="evidence-source-row evidence-status-' + status + '">' +
            '<span>' + _evidenceEscape(_evidenceSourceLabel(source)) + '</span>' +
            '<span class="evidence-source-status">' + _evidenceEscape(_evidenceStatusLabel(status)) + '</span>' +
            count +
        '</div>';
    }).join('') + '</div>';
}

function _evidenceRunAction(event) {
    var trigger = event.target.closest('[data-evidence-view], [data-evidence-action]');
    if (!trigger) return;
    var action = trigger.getAttribute('data-evidence-action');
    var view = trigger.getAttribute('data-evidence-view');
    if (action === 'report' && typeof openReportModal === 'function') {
        openReportModal(_evidenceReportScope(_evidenceLastPayload));
    } else if (view && typeof switchView === 'function') {
        switchView(view);
    }
}

function _evidenceBuildUrl() {
    var caseSelect = document.getElementById('evidence-incident-id');
    var incidentId = caseSelect ? (caseSelect.value || '').trim() : '';
    if (incidentId) {
        return docsightUrl('/api/evidence/checklist?incident_id=' + encodeURIComponent(incidentId));
    }
    var from = _evidenceToIso(document.getElementById('evidence-from').value);
    var to = _evidenceToIso(document.getElementById('evidence-to').value);
    if (!from || !to) return null;
    return docsightUrl('/api/evidence/checklist?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to));
}

function _evidenceRenderCounts(summary) {
    var root = document.getElementById('evidence-status-counts');
    if (!root) return;
    var statuses = ['present', 'stale', 'missing', 'optional', 'not_applicable'];
    root.innerHTML = statuses.map(function(status) {
        var count = summary && summary[status] || 0;
        return '<div class="evidence-count evidence-status-' + status + '">' +
            '<span>' + _evidenceEscape(_evidenceStatusLabel(status)) + '</span>' +
            '<strong>' + count + '</strong>' +
            '</div>';
    }).join('');
}

function _evidenceRenderItems(items) {
    var root = document.getElementById('evidence-items');
    if (!root) return;
    root.innerHTML = (items || []).map(function(item) {
        var status = _evidenceSafeStatus(item.status);
        var label = _evidenceEscape(_evidenceT(item.label_key, item.key));
        var hint = _evidenceEscape(_evidenceT(item.hint_key, 'Review this evidence source.'));
        var count = typeof item.count === 'number' && item.count > 0
            ? '<span class="evidence-count-pill">' + _evidenceEscape(item.count) + '</span>'
            : '';
        var sources = _evidenceRenderSourceBreakdown(item);
        var last = item.last_ts ? '<span class="evidence-muted">' + _evidenceEscape(item.last_ts) + '</span>' : '';
        var action = '';
        if (item.action && item.action.view && document.getElementById(
            item.action.view === 'live' ? 'view-dashboard' : 'view-' + item.action.view
        )) {
            action = '<button class="evidence-action" type="button" data-evidence-view="' + _evidenceEscape(item.action.view) + '">' + _evidenceEscape(_evidenceActionLabel(item)) + '</button>';
        } else if (item.action && item.action.action === 'report') {
            action = '<button class="evidence-action" type="button" data-evidence-action="' + _evidenceEscape(item.action.action) + '">' + _evidenceEscape(_evidenceActionLabel(item)) + '</button>';
        }
        return '<article class="evidence-item evidence-status-' + status + '">' +
            '<i class="evidence-item-icon" data-lucide="' + _evidenceStatusIcon(status) + '"></i>' +
            '<div class="evidence-item-body">' +
                '<div class="evidence-item-title-row">' +
                    '<h4>' + label + '</h4>' + count +
                    '<span class="evidence-badge">' + _evidenceEscape(_evidenceStatusLabel(status)) + '</span>' +
                '</div>' +
                '<p>' + hint + '</p>' + sources +
                '<div class="evidence-item-meta">' + last + action + '</div>' +
            '</div>' +
        '</article>';
    }).join('');
    root.removeEventListener('click', _evidenceRunAction);
    root.addEventListener('click', _evidenceRunAction);
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

function _evidenceSupportSummary(payload) {
    if (!payload) return '';
    var lines = [];
    lines.push(_evidenceT('docsight.evidence.copy_heading', 'DOCSight evidence summary'));
    lines.push((_evidenceT('docsight.evidence.copy_window', 'Window') + ': ' + payload.window.label + ' (' + payload.window.from + ' – ' + payload.window.to + ')'));
    (payload.items || []).forEach(function(item) {
        lines.push('- ' + _evidenceT(item.label_key, item.key) + ': ' + _evidenceStatusLabel(item.status) + (item.count ? ' (' + item.count + ')' : ''));
    });
    lines.push(_evidenceT('docsight.evidence.copy_review_note', 'Review the details before sharing; this summary lists available evidence only.'));
    return lines.join('\n');
}

function _evidenceSetCopyState(state) {
    var copy = document.getElementById('evidence-copy');
    if (!copy) return;
    var defaultLabel = copy.getAttribute('data-default-label') || copy.textContent.trim();
    copy.setAttribute('data-default-label', defaultLabel);
    if (_evidenceCopyResetTimer) {
        window.clearTimeout(_evidenceCopyResetTimer);
        _evidenceCopyResetTimer = null;
    }
    copy.textContent = state === 'success'
        ? _evidenceT('docsight.evidence.copy_success', 'Copied')
        : state === 'failed'
            ? _evidenceT('docsight.evidence.copy_failed', 'Copy failed')
            : defaultLabel;
    if (state) {
        _evidenceCopyResetTimer = window.setTimeout(function() { _evidenceSetCopyState(''); }, 2000);
    }
}

function _evidenceCopySummary() {
    var text = _evidenceSupportSummary(_evidenceLastPayload);
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            _evidenceSetCopyState('success');
        }).catch(function() {
            _evidenceSetCopyState('failed');
        });
    } else {
        _evidenceSetCopyState('failed');
    }
}

function _evidenceRender(payload) {
    _evidenceLastPayload = payload;
    document.getElementById('evidence-results').hidden = false;
    document.getElementById('evidence-placeholder').style.display = 'none';
    document.getElementById('evidence-window-label').textContent = payload.window.label;
    document.getElementById('evidence-window-range').textContent = payload.window.from + ' – ' + payload.window.to;
    document.getElementById('evidence-demo-banner').hidden = !(payload.capabilities && payload.capabilities.demo_mode);
    _evidenceRenderCounts(payload.summary);
    _evidenceRenderItems(payload.items);
}

function _evidenceLoad() {
    var url = _evidenceBuildUrl();
    var placeholder = document.getElementById('evidence-placeholder');
    if (!url) {
        placeholder.style.display = 'block';
        placeholder.textContent = _evidenceT('docsight.evidence.choose_window', 'Choose an incident or complete time range first.');
        return;
    }
    // Only the latest request may render: a slow earlier window must not replace a newer choice.
    var seq = ++_evidenceRequestSeq;
    document.getElementById('evidence-loading').hidden = false;
    document.getElementById('evidence-results').hidden = true;
    fetch(url)
        .then(function(response) { return response.json(); })
        .then(function(payload) {
            if (seq !== _evidenceRequestSeq) return;
            document.getElementById('evidence-loading').hidden = true;
            if (payload.error) {
                placeholder.style.display = 'block';
                placeholder.textContent = payload.error;
                return;
            }
            _evidenceRender(payload);
        })
        .catch(function(error) {
            if (seq !== _evidenceRequestSeq) return;
            document.getElementById('evidence-loading').hidden = true;
            placeholder.style.display = 'block';
            placeholder.textContent = error.message;
        });
}

/* #evidence?from=YYYY-MM-DDTHH:MM&to=… (local time) opens the journey for that window. */
function _evidenceApplyHashWindow() {
    var hash = location.hash || '';
    var query = hash.indexOf('?') === -1 ? '' : hash.slice(hash.indexOf('?') + 1);
    var params = new URLSearchParams(query);
    var pattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;
    var from = params.get('from');
    var to = params.get('to');
    if (!from || !to || !pattern.test(from) || !pattern.test(to) || from >= to) return false;
    _evidenceSetWindow(from, to, null);
    _evidenceLoad();
    return true;
}

function initEvidence() {
    var firstOpen = !_evidenceInitialized;
    if (firstOpen) {
        _evidenceInitialized = true;
        var run = document.getElementById('evidence-run');
        var copy = document.getElementById('evidence-copy');
        var caseSelect = document.getElementById('evidence-incident-id');
        if (run) run.addEventListener('click', _evidenceLoad);
        if (copy) copy.addEventListener('click', _evidenceCopySummary);
        if (caseSelect) {
            caseSelect.addEventListener('change', function() {
                _evidenceMarkRange(null);
                if (caseSelect.value) _evidenceLoad();
            });
        }
        ['evidence-from', 'evidence-to'].forEach(function(id) {
            document.getElementById(id).addEventListener('input', function() {
                if (caseSelect) caseSelect.value = '';
                _evidenceMarkRange(null);
            });
        });
        document.querySelectorAll('.evidence-chip[data-evidence-range]').forEach(function(chip) {
            chip.addEventListener('click', function() {
                var range = _evidenceQuickRange(chip.dataset.evidenceRange, Date.now());
                _evidenceSetWindow(range[0], range[1], chip.dataset.evidenceRange);
                _evidenceLoad();
            });
        });
    }
    _evidenceLoadCases();
    // A handed-over window wins; otherwise the first visit evaluates the last 24 hours right away.
    if (!_evidenceApplyHashWindow() && firstOpen) {
        var range = _evidenceQuickRange('last24h', Date.now());
        _evidenceSetWindow(range[0], range[1], 'last24h');
        _evidenceLoad();
    }
}
