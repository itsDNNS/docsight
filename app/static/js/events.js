/* ═══ DOCSight Event Log ═══ */

/* ── State ── */
var _eventsOffset = 0;
var _eventsPageSize = 50;
var _eventsRequestCount = 0;
var _badgeRequestCount = 0;
var _eventTypeLabels = {
    health_change: T.event_type_health_change || 'Health Change',
    power_change: T.event_type_power_change || 'Power Change',
    snr_change: T.event_type_snr_change || 'SNR Change',
    channel_change: T.event_type_channel_change || 'Channel Change',
    modulation_change: T.event_type_modulation_change || 'Modulation Change',
    device_sw_update: T.event_type_device_sw_update || 'Software Update',
    device_reboot: T.event_type_device_reboot || 'Device Reboot',
    device_ip_change: T.event_type_device_ip_change || 'IP Change',
    error_spike: T.event_type_error_spike || 'Error Spike',
    smart_capture_triggered: T.event_type_smart_capture_triggered || 'Smart Capture'
};
var _sevLabels = {
    info: T.event_severity_info || 'Info',
    warning: T.event_severity_warning || 'Warning',
    critical: T.event_severity_critical || 'Critical'
};

/* Phase 4.3: Pill filter toggle function */
var _currentSeverityFilter = '';
var _deviceOnlyFilter = false;
var _hideOperational = true;
var _OPERATIONAL_EVENT_TYPES = { monitoring_started: true, monitoring_stopped: true };

function _eventTypeLabel(eventType) {
    var explicit = _eventTypeLabels[eventType];
    if (explicit) return explicit;
    var i18nKey = 'event_type_' + eventType;
    return T[i18nKey] || eventType;
}

/* ── Rich event message formatter ── */
function _fmtNum(n) {
    if (typeof n !== 'number') return escapeHtml(String(n));
    return n.toLocaleString('en-US', { maximumFractionDigits: 1 });
}

function _healthDot(h) {
    var cls = (h === 'good' || h === 'marginal' || h === 'poor' || h === 'tolerated') ? h : 'unknown';
    var labels = {good: T.health_good || 'Good', tolerated: T.health_tolerated || 'Tolerated', marginal: T.health_marginal || 'Marginal', poor: T.health_critical || 'Critical'};
    return '<span class="health-dot ' + cls + '"></span>' + escapeHtml(labels[h] || h);
}

function formatEventMessage(ev) {
    var d = ev.details;
    if (!d) return escapeHtml(ev.message);

    switch (ev.event_type) {
        case 'health_change':
            return _healthDot(d.prev) +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                _healthDot(d.current);

        case 'power_change': {
            var dir = d.direction === 'downstream' ? (T.event_ds || 'DS') : (T.event_us || 'US');
            var delta = d.current - d.prev;
            var sign = delta >= 0 ? '+' : '';
            return '<span class="ev-label">' + escapeHtml(dir) + ' ' + (T.event_power || 'Power') + '</span>' +
                '<span class="ev-val">' + _fmtNum(d.prev) + '</span>' +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                '<span class="ev-val">' + _fmtNum(d.current) + '</span> dBmV ' +
                '<span class="ev-warn">' + (delta >= 0 ? '\u25B2' : '\u25BC') + ' ' + sign + _fmtNum(delta) + '</span>';
        }

        case 'snr_change': {
            var thr = d.threshold === 'critical' ? 'ev-down' : 'ev-warn';
            var html = '<span class="ev-label">' + (T.event_ds || 'DS') + ' SNR</span>' +
                '<span class="ev-val">' + _fmtNum(d.prev) + '</span>' +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                '<span class="ev-val ' + thr + '">' + _fmtNum(d.current) + '</span> dB ' +
                '<span class="ev-muted">(' + escapeHtml({warning: T.health_marginal || 'Marginal', critical: T.health_critical || 'Critical'}[d.threshold] || d.threshold) + ')</span>';
            var affected = d.affected_channels || [];
            var shown = affected.slice(0, 6);
            shown.forEach(function(c) {
                var delta = typeof c.delta === 'number' ? c.delta : (c.current - c.prev);
                var sign = delta >= 0 ? '+' : '';
                var channelLabel = (T.event_ds || 'DS') + ' Ch ' + escapeHtml(String(c.channel));
                var meta = [];
                if (c.frequency) meta.push(escapeHtml(String(c.frequency)));
                if (c.modulation) meta.push(escapeHtml(String(c.modulation)));
                html += '<span class="ev-sub">' + channelLabel +
                    (meta.length ? ' · ' + meta.join(' · ') : '') + ': ' +
                    '<span class="ev-val">' + _fmtNum(c.prev) + '</span>' +
                    '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                    '<span class="ev-val ' + thr + '">' + _fmtNum(c.current) + '</span> dB ' +
                    '<span class="ev-down">\u25BC ' + sign + _fmtNum(delta) + '</span>' +
                    '</span>';
            });
            if (affected.length > shown.length) {
                html += '<span class="ev-sub ev-muted">+' + (affected.length - shown.length) + ' more affected channel(s)</span>';
            }
            return html;
        }

        case 'channel_change': {
            var chDir = d.direction === 'downstream' ? (T.event_ds || 'DS') : (T.event_us || 'US');
            var chDelta = d.current - d.prev;
            var chCls = chDelta < 0 ? 'ev-down' : 'ev-up';
            var chSign = chDelta >= 0 ? '+' : '';
            return '<span class="ev-label">' + escapeHtml(chDir) + ' ' + (T.event_channels || 'Channels') + '</span>' +
                '<span class="ev-val">' + _fmtNum(d.prev) + '</span>' +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                '<span class="ev-val">' + _fmtNum(d.current) + '</span> ' +
                '<span class="' + chCls + '">' + (chDelta < 0 ? '\u25BC' : '\u25B2') + ' ' + chSign + chDelta + '</span>';
        }

        case 'modulation_change': {
            var changes = d.changes || [];
            var isDown = d.direction === 'downgrade';
            var html = '<span>' + escapeHtml(ev.message) + '</span>';
            changes.forEach(function(c) {
                var arrow = isDown ? '\u25BC' : '\u25B2';
                var cls = isDown ? 'ev-down' : 'ev-up';
                var ranks = Math.abs(c.rank_drop || 0);
                html += '<span class="ev-sub">' +
                    escapeHtml(c.direction) + ' Ch ' + escapeHtml(String(c.channel)) + ': ' +
                    '<span class="ev-val">' + escapeHtml(c.prev) + '</span>' +
                    '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                    '<span class="ev-val">' + escapeHtml(c.current) + '</span> ' +
                    '<span class="' + cls + '">' + arrow + ' ' + ranks + ' rank' + (ranks !== 1 ? 's' : '') + '</span>' +
                    '</span>';
            });
            return html;
        }

        case 'error_spike': {
            var spikeDelta = d.delta || (d.current - d.prev);
            return '<span class="ev-val ev-warn">+' + _fmtNum(spikeDelta) + '</span> ' + (T.event_uncorrectable_errors || 'uncorrectable errors') + ' ' +
                '<span class="ev-muted">(' + _fmtNum(d.prev) + ' \u2192 ' + _fmtNum(d.current) + ')</span>';
        }

        case 'monitoring_started':
            return escapeHtml(T.event_monitoring_started_msg || 'Monitoring started') + ' ' + _healthDot(d.health || 'unknown');

        case 'smart_capture_triggered': {
            var scHtml = '<span>' + escapeHtml(ev.message) + '</span>';
            if (d && d.source_event) {
                scHtml += '<span class="ev-sub">' + escapeHtml(d.source_event) + '</span>';
            }
            return scHtml;
        }

        default:
            return escapeHtml(ev.message);
    }
}

function toggleHideOperational() {
    _hideOperational = !_hideOperational;
    var btn = document.getElementById('hide-operational-btn');
    if (btn) {
        btn.classList.toggle('active', _hideOperational);
        btn.setAttribute('aria-pressed', String(_hideOperational));
    }
    loadEvents();
    refreshEventBadge();
}

function filterEventsBySeverity(severity) {
    _currentSeverityFilter = severity;
    _deviceOnlyFilter = false;
    var pills = document.querySelectorAll('.severity-pill:not(#hide-operational-btn)');
    pills.forEach(function(pill) {
        var isActive = pill.getAttribute('data-severity') === severity;
        pill.classList.toggle('active', isActive);
        if (pill.hasAttribute('aria-pressed')) {
            pill.setAttribute('aria-pressed', String(isActive));
        }
    });
    loadEvents();
    refreshEventBadge();
}

function filterEventsByDevice() {
    _deviceOnlyFilter = !_deviceOnlyFilter;
    _currentSeverityFilter = '';

    var pills = document.querySelectorAll('.severity-pill:not(#hide-operational-btn)');
    pills.forEach(function(pill) {
        if (pill.id === 'device-filter-pill') {
            pill.classList.toggle('active', _deviceOnlyFilter);
            pill.setAttribute('aria-pressed', String(_deviceOnlyFilter));
        } else {
            pill.classList.remove('active');
            if (pill.hasAttribute('aria-pressed')) {
                pill.setAttribute('aria-pressed', 'false');
            }
        }
    });
    loadEvents();
    refreshEventBadge();
}

function loadEvents(append) {
    if (!append) _eventsOffset = 0;
    var tableRequestId = ++_eventsRequestCount;
    var badgeRequestId = ++_badgeRequestCount;
    var severity = _currentSeverityFilter;
    var params = '?limit=' + _eventsPageSize + '&offset=' + _eventsOffset;
    if (severity) params += '&severity=' + severity;
    if (_hideOperational) params += '&exclude_operational=true';
    if (_deviceOnlyFilter) params += '&event_prefix=device_';

    var tbody = document.getElementById('events-tbody');
    var tableCard = document.getElementById('events-table-card');
    var table = document.getElementById('events-table');
    var empty = document.getElementById('events-empty');
    var loading = document.getElementById('events-loading');
    var moreBtn = document.getElementById('events-show-more');
    var ackAllBtn = document.getElementById('btn-ack-all');

    if (!append) {
        loading.style.display = '';
        tbody.innerHTML = '';
        tableCard.style.display = 'none';
        empty.style.display = 'none';
        moreBtn.style.display = 'none';
    }

    fetch('/api/events' + params)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            loading.style.display = 'none';
            var events = data.events || [];
            var unack = data.unacknowledged_count || 0;

            // Events and unack count are now natively filtered by the backend!
            // Events and unack count are now natively filtered by the backend!
            var eventsViewEl = document.getElementById('view-events');
            if (badgeRequestId === _badgeRequestCount && eventsViewEl && eventsViewEl.classList.contains('active')) {
                updateEventBadge(unack);
                ackAllBtn.style.display = unack > 0 ? '' : 'none';
            }

            if (tableRequestId === _eventsRequestCount) {
                if (events.length === 0 && !append) {
                    empty.textContent = T.event_no_events || 'No events detected yet.';
                    empty.style.display = '';
                    return;
                }
                events.forEach(function(ev) {
                    var tr = document.createElement('tr');
                    if (ev.acknowledged) tr.className = 'event-acked';
                    tr.setAttribute('data-event-id', ev.id);
                    var sevClass = 'sev-badge-' + ev.severity;
                    var sevLabel = _sevLabels[ev.severity] || ev.severity;
                    var sevIcons = { info: 'info', warning: 'triangle-alert', critical: 'octagon-alert' };
                    var sevIcon = sevIcons[ev.severity] || 'info';
                    var typeLabel = _eventTypeLabel(ev.event_type);
                    var ackBtn = ev.acknowledged
                        ? '<span class="ev-ack-mark">&#10003;</span>'
                        : '<button class="btn-ack" onclick="acknowledgeEvent(' + ev.id + ', event)">&#10003;</button>';
                    tr.innerHTML =
                        '<td style="white-space:nowrap;">' + escapeHtml(ev.timestamp.replace('T', ' ')) + '</td>' +
                        '<td><span class="' + sevClass + '"><span class="sev-text">' + sevLabel + '</span><i data-lucide="' + sevIcon + '" class="sev-icon"></i></span></td>' +
                        '<td>' + escapeHtml(typeLabel) + '</td>' +
                        '<td class="event-msg">' + formatEventMessage(ev) + '</td>' +
                        '<td class="event-actions">' + ackBtn + '</td>';
                    tbody.appendChild(tr);
                });
                tableCard.style.display = '';
                moreBtn.style.display = events.length >= _eventsPageSize ? '' : 'none';
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        })
        .catch(function() {
            loading.style.display = 'none';
            empty.textContent = T.network_error || 'Error';
            empty.style.display = '';
        });
}

function loadMoreEvents() {
    _eventsOffset += _eventsPageSize;
    loadEvents(true);
}

function acknowledgeEvent(eventId, e) {
    if (e) e.stopPropagation();
    fetch('/api/events/' + eventId + '/acknowledge', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) loadEvents();
        });
}

function acknowledgeAllEvents() {
    fetch('/api/events/acknowledge-all', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) loadEvents();
        });
}

function updateEventBadge(count) {
    var badges = [];
    var sidebarBadge = document.getElementById('event-badge');
    if (sidebarBadge) badges.push(sidebarBadge);
    document.querySelectorAll('.bottom-nav-badge[data-view="events"]').forEach(function(badge) {
        badges.push(badge);
    });
    if (!badges.length) return;
    badges.forEach(function(badge) {
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : count;
            badge.style.display = '';
        } else {
            badge.style.display = 'none';
        }
    });
}

window.refreshEventBadge = function() {
    var params = '';
    var eventsViewEl = document.getElementById('view-events');
    var isEventsView = eventsViewEl && eventsViewEl.classList.contains('active');
    var requestId = ++_badgeRequestCount;

    if (typeof _hideOperational !== 'undefined' && _hideOperational) {
        params += (params ? '&' : '?') + 'exclude_operational=true';
    }

    // Only apply severity/device filters if we are actually looking at the events view
    if (isEventsView) {
        if (typeof _deviceOnlyFilter !== 'undefined' && _deviceOnlyFilter) {
            params += (params ? '&' : '?') + 'event_prefix=device_';
        }
        if (typeof _currentSeverityFilter !== 'undefined' && _currentSeverityFilter) {
            params += (params ? '&' : '?') + 'severity=' + _currentSeverityFilter;
        }
    }
    
    params += (params ? '&' : '?') + 't=' + Date.now();

    fetch('/api/events/count' + params)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (requestId === _badgeRequestCount) {
                updateEventBadge(data.count || 0);
            }
        })
        .catch(function() {});
};

// Fetch badge count on page load
refreshEventBadge();

// Periodically refresh badge count
setInterval(refreshEventBadge, 60000);
