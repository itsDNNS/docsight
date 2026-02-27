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
                var typeLabel = _eventTypeLabels[ev.event_type] || ev.event_type;
                // Note: escapeHtml is used on all user-facing content to prevent XSS.
                // The ack button uses a hardcoded event ID (integer) which is safe.
                var ackBtn = ev.acknowledged
                    ? '<span style="color:var(--muted);font-size:0.8em;">&#10003;</span>'
                    : '<button class="btn-ack" onclick="acknowledgeEvent(' + ev.id + ', event)">&#10003;</button>';
                tr.innerHTML =
                    '<td style="white-space:nowrap;">' + escapeHtml(ev.timestamp.replace('T', ' ')) + '</td>' +
                    '<td><span class="' + sevClass + '">' + sevLabel + '</span></td>' +
                    '<td>' + escapeHtml(typeLabel) + '</td>' +
                    '<td class="event-msg">' + escapeHtml(ev.message) + '</td>' +
                    '<td class="event-actions">' + ackBtn + '</td>';
                if (ev.details) {
                    tr.style.cursor = 'pointer';
                    tr.onclick = function(e) {
                        if (e.target.tagName === 'BUTTON') return;
                        toggleEventDetail(ev.id, ev.details);
                    };
                }
                tbody.appendChild(tr);
            });
            tableCard.style.display = '';
            moreBtn.style.display = events.length >= _eventsPageSize ? '' : 'none';
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

function toggleEventDetail(eventId, details) {
    var existing = document.getElementById('event-detail-' + eventId);
    if (existing) {
        existing.remove();
        return;
    }
    var eventRow = document.querySelector('tr[data-event-id="' + eventId + '"]');
    if (!eventRow) return;
    var detailRow = document.createElement('tr');
    detailRow.id = 'event-detail-' + eventId;
    detailRow.className = 'event-detail-row';
    var td = document.createElement('td');
    td.colSpan = 5;
    var pre = document.createElement('pre');
    pre.textContent = JSON.stringify(details, null, 2);
    td.appendChild(pre);
    detailRow.appendChild(td);
    eventRow.parentNode.insertBefore(detailRow, eventRow.nextSibling);
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
    var badge = document.getElementById('event-badge');
    if (!badge) return;
    if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.style.display = '';
    } else {
        badge.style.display = 'none';
    }
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
