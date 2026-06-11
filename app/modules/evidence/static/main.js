/* -- Guided Evidence Journey Module -- */

var _evidenceInitialized = false;
var _evidenceLastPayload = null;

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
        not_applicable: 'not_applicable'
    }[status] || 'missing';
}

function _evidenceToIso(value) {
    if (!value) return '';
    return value.length === 16 ? value + ':00' : value;
}

function _evidenceDefaultWindow() {
    var now = new Date();
    var from = new Date(now.getTime() - 6 * 3600000);
    function fmt(d) {
        function pad(n) { return String(n).padStart(2, '0'); }
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
            'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    var fromEl = document.getElementById('evidence-from');
    var toEl = document.getElementById('evidence-to');
    if (fromEl && !fromEl.value) fromEl.value = fmt(from);
    if (toEl && !toEl.value) toEl.value = fmt(now);
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
        not_applicable: 'ban'
    }[safeStatus] || 'circle-help';
}

function _evidenceActionLabel(item) {
    var view = item.action && item.action.view;
    var action = item.action && item.action.action;
    return _evidenceT('docsight.evidence.action.' + (action || view || 'review'), 'Open related view');
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
        openReportModal();
    } else if (view && typeof switchView === 'function') {
        switchView(view);
    }
}

function _evidenceBuildUrl() {
    var incidentId = (document.getElementById('evidence-incident-id').value || '').trim();
    if (incidentId) {
        return '/api/evidence/checklist?incident_id=' + encodeURIComponent(incidentId);
    }
    var from = _evidenceToIso(document.getElementById('evidence-from').value);
    var to = _evidenceToIso(document.getElementById('evidence-to').value);
    if (!from || !to) return null;
    return '/api/evidence/checklist?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to);
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
        if (item.action && item.action.view) {
            action = '<button class="evidence-action" type="button" data-evidence-view="' + _evidenceEscape(item.action.view) + '">' + _evidenceEscape(_evidenceActionLabel(item)) + '</button>';
        } else if (item.action && item.action.action) {
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

function _evidenceCopySummary() {
    var text = _evidenceSupportSummary(_evidenceLastPayload);
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
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
    document.getElementById('evidence-loading').hidden = false;
    document.getElementById('evidence-results').hidden = true;
    fetch(url)
        .then(function(response) { return response.json(); })
        .then(function(payload) {
            document.getElementById('evidence-loading').hidden = true;
            if (payload.error) {
                placeholder.style.display = 'block';
                placeholder.textContent = payload.error;
                return;
            }
            _evidenceRender(payload);
        })
        .catch(function(error) {
            document.getElementById('evidence-loading').hidden = true;
            placeholder.style.display = 'block';
            placeholder.textContent = error.message;
        });
}

function initEvidence() {
    if (_evidenceInitialized) return;
    _evidenceInitialized = true;
    _evidenceDefaultWindow();
    var run = document.getElementById('evidence-run');
    var copy = document.getElementById('evidence-copy');
    if (run) run.addEventListener('click', _evidenceLoad);
    if (copy) copy.addEventListener('click', _evidenceCopySummary);
}
