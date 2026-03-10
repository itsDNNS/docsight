/* ═══ DOCSight Event Log ═══ */

/* ── State ── */
var _eventsOffset = 0;
var _eventsPageSize = 50;
var _eventTypeLabels = {
    health_change: T.event_type_health_change || 'Health Change',
    power_change: T.event_type_power_change || 'Power Change',
    snr_change: T.event_type_snr_change || 'SNR Change',
    channel_change: T.event_type_channel_change || 'Channel Change',
    modulation_change: T.event_type_modulation_change || 'Modulation Change',
    error_spike: T.event_type_error_spike || 'Error Spike'
};
var _sevLabels = {
    info: T.event_severity_info || 'Info',
    warning: T.event_severity_warning || 'Warning',
    critical: T.event_severity_critical || 'Critical'
};

/* Phase 4.3: Pill filter toggle function */
var _currentSeverityFilter = '';
var _hideOperational = true;
var _OPERATIONAL_EVENT_TYPES = { monitoring_started: true, monitoring_stopped: true };

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
            return '<span class="ev-label">' + (T.event_ds || 'DS') + ' SNR</span>' +
                '<span class="ev-val">' + _fmtNum(d.prev) + '</span>' +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                '<span class="ev-val ' + thr + '">' + _fmtNum(d.current) + '</span> dB ' +
                '<span class="ev-muted">(' + escapeHtml({warning: T.health_marginal || 'Marginal', critical: T.health_critical || 'Critical'}[d.threshold] || d.threshold) + ')</span>';
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

        default:
            return escapeHtml(ev.message);
    }
}

function toggleHideOperational() {
    _hideOperational = !_hideOperational;
    var btn = document.getElementById('hide-operational-btn');
    if (btn) btn.classList.toggle('active', _hideOperational);
    loadEvents();
}

function filterEventsBySeverity(severity) {
    _currentSeverityFilter = severity;
    var pills = document.querySelectorAll('.severity-pill');
    pills.forEach(function(pill) {
        if (pill.getAttribute('data-severity') === severity) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
    });
    loadEvents();
}

function loadEvents(append) {
    if (!append) _eventsOffset = 0;
    var severity = _currentSeverityFilter;
    var params = '?limit=' + _eventsPageSize + '&offset=' + _eventsOffset;
    if (severity) params += '&severity=' + severity;

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

            // Filter operational events client-side
            if (_hideOperational) {
                var opCount = 0;
                events = events.filter(function(ev) {
                    if (_OPERATIONAL_EVENT_TYPES[ev.event_type]) {
                        if (!ev.acknowledged) opCount++;
                        return false;
                    }
                    return true;
                });
                unack = Math.max(0, unack - opCount);
            }

            updateEventBadge(unack);
            ackAllBtn.style.display = unack > 0 ? '' : 'none';

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
                var typeLabel = _eventTypeLabels[ev.event_type] || ev.event_type;
                // Note: escapeHtml is used on all user-facing content to prevent XSS.
                // The ack button uses a hardcoded event ID (integer) which is safe.
                var ackBtn = ev.acknowledged
                    ? '<span style="color:var(--muted);font-size:0.8em;">&#10003;</span>'
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

// Fetch badge count on page load (exclude operational if hidden)
fetch('/api/events?limit=200&offset=0')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var unack = data.unacknowledged_count || 0;
        if (_hideOperational) {
            var events = data.events || [];
            var opCount = 0;
            events.forEach(function(ev) {
                if (_OPERATIONAL_EVENT_TYPES[ev.event_type] && !ev.acknowledged) opCount++;
            });
            unack = Math.max(0, unack - opCount);
        }
        updateEventBadge(unack);
    })
    .catch(function() {});
