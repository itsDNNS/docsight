/* ═══ DOCSight Event Log ═══ */

/* ── State ── */
var _eventsPageSize = 50;
var _eventsRequestCount = 0;
var _badgeRequestCount = 0;
var _eventsLoaded = [];
var _eventsExpanded = {};
var _eventsSelected = {};
var _eventsAckChunk = 500;
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

var _currentSeverityFilter = '';
var _deviceOnlyFilter = false;
var _hideOperational = true;

function _eventTypeLabel(eventType) {
    var explicit = _eventTypeLabels[eventType];
    if (explicit) return explicit;
    var i18nKey = 'event_type_' + eventType;
    return T[i18nKey] || eventType;
}

function _eventSeverityMeta(ev) {
    var severity = DOCSightEventLogData.severity(ev);
    var sevIcons = { info: 'info', warning: 'triangle-alert', critical: 'octagon-alert' };
    return { severity: severity, label: _sevLabels[severity], icon: sevIcons[severity] };
}

function updateEventsExportLink() {
    var exportLink = document.getElementById('events-export-csv');
    if (!exportLink) return;
    var params = new URLSearchParams();
    if (_currentSeverityFilter) params.set('severity', _currentSeverityFilter);
    if (_hideOperational) params.set('exclude_operational', 'true');
    if (_deviceOnlyFilter) params.set('event_prefix', 'device_');
    var qs = params.toString();
    exportLink.href = docsightUrl('/api/events/export.csv' + (qs ? '?' + qs : ''));
}

/* ── Rich event message formatter ── */
function _fmtNum(n) {
    if (typeof n !== 'number') return escapeHtml(String(n));
    return escapeHtml(n.toLocaleString(_eventLocale(), { maximumFractionDigits: 1 }));
}

function _fmtNumText(n) {
    return typeof n === 'number' ? n.toLocaleString(_eventLocale(), { maximumFractionDigits: 1 }) : String(n == null ? '' : n);
}

/* Uptime in days, hours and minutes, e.g. "112 d 14 h 7 min". */
function _fmtUptime(seconds) {
    var days = Math.floor(seconds / 86400);
    var hours = Math.floor((seconds % 86400) / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    var parts = [];
    if (days) parts.push(days + ' d');
    if (days || hours) parts.push(hours + ' h');
    parts.push(minutes + ' min');
    return parts.join(' ');
}

function _healthDot(h) {
    var cls = (h === 'good' || h === 'marginal' || h === 'poor' || h === 'tolerated') ? h : 'unknown';
    var labels = {good: T.health_good || 'Good', tolerated: T.health_tolerated || 'Tolerated', marginal: T.health_marginal || 'Marginal', poor: T.health_critical || 'Critical'};
    return '<span class="health-dot ' + cls + '"></span>' + escapeHtml(labels[h] || h);
}

function _eventChannelMeta(c) {
    var meta = [];
    if (c.frequency) meta.push(escapeHtml(String(c.frequency)));
    if (c.channel_type) meta.push(escapeHtml(String(c.channel_type)));
    if (c.docsis_version) meta.push('DOCSIS ' + escapeHtml(String(c.docsis_version)));
    if (c.modulation) meta.push(escapeHtml(String(c.modulation)));
    return meta;
}

/* Rendered next to the event type, so the message names only the direction
   and the values, never the measurement again. */
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
            return '<span class="ev-label">' + escapeHtml(dir) + '</span>' +
                '<span class="ev-val">' + _fmtNum(d.prev) + '</span>' +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                '<span class="ev-val">' + _fmtNum(d.current) + '</span> dBmV ' +
                '<span class="ev-warn">' + (delta >= 0 ? '\u25B2' : '\u25BC') + ' ' + sign + _fmtNum(delta) + '</span>';
        }

        case 'snr_change': {
            var thr = d.threshold === 'critical' ? 'ev-down' : 'ev-warn';
            var html = '<span class="ev-label">' + escapeHtml(T.event_ds || 'DS') + '</span>' +
                '<span class="ev-val">' + _fmtNum(d.prev) + '</span>' +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                '<span class="ev-val ' + thr + '">' + _fmtNum(d.current) + '</span> dB ' +
                '<span class="ev-muted">(' + escapeHtml({warning: T.health_marginal || 'Marginal', critical: T.health_critical || 'Critical'}[d.threshold] || d.threshold) + ')</span>';
            var affectedRaw = Array.isArray(d.affected_channels) ? d.affected_channels : [];
            var affected = affectedRaw.filter(function(c) { return c && typeof c === 'object'; });
            var shown = affected.slice(0, 6);
            shown.forEach(function(c) {
                var delta = typeof c.delta === 'number' ? c.delta : (c.current - c.prev);
                var sign = delta >= 0 ? '+' : '';
                var channelLabel = escapeHtml((T.event_ds || 'DS') + ' ' + (T.event_channel_short || 'Ch') + ' ' + c.channel);
                var meta = _eventChannelMeta(c);
                // The summary already shows these values; the line only names the channel.
                if (c.prev === d.prev && c.current === d.current) {
                    html += '<span class="ev-sub">' + channelLabel + (meta.length ? ' · ' + meta.join(' · ') : '') + '</span>';
                    return;
                }
                html += '<span class="ev-sub">' + channelLabel +
                    (meta.length ? ' · ' + meta.join(' · ') : '') + ': ' +
                    '<span class="ev-val">' + _fmtNum(c.prev) + '</span>' +
                    '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                    '<span class="ev-val ' + thr + '">' + _fmtNum(c.current) + '</span> dB ' +
                    '<span class="ev-down">\u25BC ' + sign + _fmtNum(delta) + '</span>' +
                    '</span>';
            });
            if (affected.length > shown.length) {
                html += '<span class="ev-sub ev-muted">+' + escapeHtml((T.channel_status_more || '{count} more channels').replace('{count}', affected.length - shown.length)) + '</span>';
            }
            return html;
        }

        case 'channel_change': {
            var chDir = d.direction === 'downstream' ? (T.event_ds || 'DS') : (T.event_us || 'US');
            var chDelta = d.current - d.prev;
            var chCls = chDelta < 0 ? 'ev-down' : 'ev-up';
            var chSign = chDelta >= 0 ? '+' : '';
            return '<span class="ev-label">' + escapeHtml(chDir) + '</span>' +
                '<span class="ev-val">' + _fmtNum(d.prev) + '</span>' +
                '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                '<span class="ev-val">' + _fmtNum(d.current) + '</span> ' +
                '<span class="' + chCls + '">' + (chDelta < 0 ? '\u25BC' : '\u25B2') + ' ' + chSign + chDelta + '</span>';
        }

        case 'modulation_change': {
            var changes = d.changes || [];
            var isDown = d.direction === 'downgrade';
            var summary = isDown ? (T.event_modulation_lower || 'Channels with lower modulation: {count}')
                                 : (T.event_modulation_higher || 'Channels with higher modulation: {count}');
            var html = '<span>' + escapeHtml(summary.replace('{count}', changes.length)) + '</span>';
            changes.forEach(function(c) {
                var arrow = isDown ? '\u25BC' : '\u25B2';
                var cls = isDown ? 'ev-down' : 'ev-up';
                var ranks = Math.abs(c.rank_drop || 0);
                var channelMeta = _eventChannelMeta(c);
                html += '<span class="ev-sub">' +
                    escapeHtml(c.direction) + ' ' + escapeHtml(T.event_channel_short || 'Ch') + ' ' + escapeHtml(String(c.channel)) +
                    (channelMeta.length ? ' · ' + channelMeta.join(' · ') : '') + ': ' +
                    '<span class="ev-val">' + escapeHtml(c.prev) + '</span>' +
                    '<i data-lucide="arrow-right" class="ev-arrow-icon"></i>' +
                    '<span class="ev-val">' + escapeHtml(c.current) + '</span> ' +
                    '<span class="' + cls + '">' + arrow + ' ' + escapeHtml((T.event_qam_levels || '{count} QAM level(s)').replace('{count}', ranks)) + '</span>' +
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

        case 'smart_capture_triggered':
            return escapeHtml((T.event_sc_speedtest || 'Speedtest triggered by {event}')
                .replace('{event}', _eventTypeLabel(d.trigger_type || 'unknown')));

        case 'modem_restart_detected': {
            var restart = escapeHtml(T.event_modem_restart_msg || 'Modem restart or counter reset detected');
            if (Array.isArray(d.affected_channels) && d.total_channels) {
                restart += ' <span class="ev-muted">(' + escapeHtml((T.event_channels_of || '{count} of {total} channels')
                    .replace('{count}', d.affected_channels.length).replace('{total}', d.total_channels)) + ')</span>';
            }
            return restart;
        }

        case 'device_sw_update':
        case 'device_reboot': {
            var parts = [];
            if (ev.event_type === 'device_sw_update') {
                parts.push(escapeHtml((T.event_firmware || 'Firmware') + ' ') + '<span class="ev-val">' + escapeHtml(d.old_sw || '?') + '</span>' +
                    '<i data-lucide="arrow-right" class="ev-arrow-icon"></i><span class="ev-val">' + escapeHtml(d.new_sw || '?') + '</span>');
            }
            if (typeof d.prior_uptime === 'number') {
                parts.push(escapeHtml((T.event_prior_uptime || 'Prior uptime') + ' ' + _fmtUptime(d.prior_uptime)));
            }
            if (d.ip_changed) parts.push(escapeHtml(T.event_ip_changed || 'WAN IP changed'));
            if (d.reboot_reason) parts.push(escapeHtml((T.event_reboot_reason || 'Reason') + ': ' + d.reboot_reason));
            return parts.length ? parts.join(' · ') : escapeHtml(_eventTypeLabel(ev.event_type));
        }

        case 'device_ip_change': {
            var ipParts = [];
            if (d.old_ipv4 || d.new_ipv4) ipParts.push('WAN IPv4 ' + escapeHtml(d.old_ipv4 || '?') + ' \u2192 ' + escapeHtml(d.new_ipv4 || '?'));
            if (d.old_ipv6 || d.new_ipv6) ipParts.push('WAN IPv6 ' + escapeHtml(d.old_ipv6 || '?') + ' \u2192 ' + escapeHtml(d.new_ipv6 || '?'));
            return ipParts.length ? ipParts.join(' · ') : escapeHtml(_eventTypeLabel(ev.event_type));
        }

        case 'cm_packet_loss_warning':
            return escapeHtml((T.event_target || 'Target') + ' ' + (d.target_id != null ? d.target_id : '') + ': ' +
                (T.event_cm_packet_loss || '{loss} packet loss over {window}')
                    .replace('{loss}', _fmtNumText(d.packet_loss_pct) + ' %')
                    .replace('{window}', _fmtNumText(d.window_seconds) + ' s'));

        default:
            return escapeHtml(ev.message);
    }
}

/* ── Filters ── */
function _setEventFilterPressed(el, pressed) {
    el.classList.toggle('active', pressed);
    el.setAttribute('aria-pressed', String(pressed));
}

function _writeEventsViewState() {
    docsightWriteViewState('events', {
        severity: _currentSeverityFilter,
        device: _deviceOnlyFilter ? '1' : '',
        operational: _hideOperational ? '' : 'shown'
    });
}

/* "#events?severity=warning&device=1&operational=shown" reopens the log with these filters. */
function applyEventsViewState() {
    var state = docsightReadViewState('events');
    if (['info', 'warning', 'critical'].indexOf(state.severity) !== -1) {
        _currentSeverityFilter = state.severity;
        document.querySelectorAll('#events-severity-tabs [data-severity]').forEach(function(tab) {
            _setEventFilterPressed(tab, tab.getAttribute('data-severity') === state.severity);
        });
    }
    if (state.device === '1') {
        _deviceOnlyFilter = true;
        var pill = document.getElementById('device-filter-pill');
        if (pill) _setEventFilterPressed(pill, true);
    }
    if (state.operational === 'shown') {
        _hideOperational = false;
        var input = document.getElementById('hide-operational-toggle');
        if (input) input.checked = false;
    }
}

function toggleHideOperational() {
    var input = document.getElementById('hide-operational-toggle');
    _hideOperational = input ? !!input.checked : !_hideOperational;
    _writeEventsViewState();
    loadEvents();
}

function filterEventsBySeverity(severity) {
    _currentSeverityFilter = severity;
    document.querySelectorAll('#events-severity-tabs [data-severity]').forEach(function(tab) {
        _setEventFilterPressed(tab, tab.getAttribute('data-severity') === severity);
    });
    _writeEventsViewState();
    loadEvents();
}

function filterEventsByDevice() {
    _deviceOnlyFilter = !_deviceOnlyFilter;
    var pill = document.getElementById('device-filter-pill');
    if (pill) _setEventFilterPressed(pill, _deviceOnlyFilter);
    _writeEventsViewState();
    loadEvents();
}

/* ── Timeline: one row per event, grouped by day, repeated events collapsed ── */
function _eventFmt(key, fallback, count) {
    return String(T[key] || fallback).replace('{count}', String(count));
}

function _eventLocale() {
    if (typeof currentLang !== 'undefined' && currentLang) return currentLang;
    return (document.documentElement && document.documentElement.lang) || undefined;
}

function _eventTodayKey() {
    var now = Date.now();
    if (typeof DOCSightBrowserContracts !== 'undefined') {
        var zone = typeof DOCSIGHT_TIME_ZONE !== 'undefined' ? DOCSIGHT_TIME_ZONE : undefined;
        return DOCSightBrowserContracts.localInputValue(now, zone).slice(0, 10);
    }
    return new Date(now).toISOString().slice(0, 10);
}

/* Day header parts: "Today"/"Yesterday" or the weekday, plus the date. */
function _eventDayParts(day) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day || '');
    if (!match) return {name: day || '', date: ''};
    var date = new Date(Date.UTC(+match[1], +match[2] - 1, +match[3]));
    function format(parts) {
        parts.timeZone = 'UTC';
        try {
            return new Intl.DateTimeFormat(_eventLocale(), parts).format(date);
        } catch (e) {
            return new Intl.DateTimeFormat(undefined, parts).format(date);
        }
    }
    var today = _eventTodayKey();
    var yesterday = new Date(Date.parse(today + 'T00:00:00Z') - 86400000).toISOString().slice(0, 10);
    var name = day === today ? (T.event_today || 'Today')
        : day === yesterday ? (T.event_yesterday || 'Yesterday')
        : format({weekday: 'short'});
    return {name: name, date: format({day: '2-digit', month: '2-digit', year: 'numeric'})};
}

function _eventSevIcon(meta) {
    return '<span class="ev-sev" title="' + escapeHtml(meta.label) + '">' +
        '<i data-lucide="' + meta.icon + '" aria-hidden="true"></i>' +
        '<span class="sr-only">' + escapeHtml(meta.label) + '</span></span>';
}

function _eventSelectBox(ids, label) {
    if (!ids.length) return '<span class="ev-select" aria-hidden="true"></span>';
    return '<label class="ev-select"><input type="checkbox" data-ids="' + ids.join(',') + '" aria-label="' +
        escapeHtml((T.event_select || 'Select') + ': ' + label) + '"></label>';
}

function _eventAckButton(ids, label) {
    if (!ids.length) {
        var done = escapeHtml(T.event_acknowledged || 'Acknowledged');
        return '<span class="ev-ack-done" title="' + done + '"><i data-lucide="check-check" aria-hidden="true"></i>' +
            '<span class="sr-only">' + done + '</span></span>';
    }
    var text = T.event_acknowledge || 'Acknowledge';
    return '<button type="button" class="ev-ack" data-ack="' + ids.join(',') + '" title="' + escapeHtml(text) +
        '" aria-label="' + escapeHtml(text + ': ' + label) + '"><i data-lucide="check" aria-hidden="true"></i></button>';
}

/* One row per event. Inside a run the type is the run's, so member rows omit it.
   Rows with extra lines (e.g. affected channels) expand in place; nothing is repeated. */
function _eventRowHtml(ev, inRun) {
    var meta = _eventSeverityMeta(ev);
    var type = _eventTypeLabel(ev.event_type);
    var clock = formatDocsightTime(ev.timestamp, 'time');
    var label = type + ', ' + clock;
    var key = 'e' + ev.id;
    var message = formatEventMessage(ev);
    var unacked = ev.acknowledged ? [] : [ev.id];
    var content =
        '<time class="ev-time" datetime="' + escapeHtml(String(ev.timestamp)) + '">' + escapeHtml(clock) + '</time>' +
        _eventSevIcon(meta) +
        (inRun ? '' : '<span class="ev-type">' + escapeHtml(type) + '</span>') +
        '<span class="ev-msg">' + message + '</span>';
    var main = message.indexOf('class="ev-sub') !== -1
        ? '<button type="button" class="ev-main" data-toggle="' + key + '" aria-expanded="' + !!_eventsExpanded[key] + '">' + content + '</button>'
        : '<div class="ev-main" data-key="' + key + '">' + content + '</div>';
    return '<li class="ev-row ev-sev-' + DOCSightEventLogData.severity(ev) + (ev.acknowledged ? ' ev-acked' : '') +
            '" data-event-id="' + ev.id + '" data-key="' + key + '">' +
        _eventSelectBox(unacked, label) +
        main +
        _eventAckButton(unacked, label) +
    '</li>';
}

/* A message cut off by the row width can be opened too; whether it is cut off
   is only known after layout. */
function _markTruncatedEventRows(feed) {
    if (!feed.querySelectorAll) return;
    feed.querySelectorAll('div.ev-main[data-key]').forEach(function(main) {
        var msg = main.querySelector('.ev-msg');
        if (!msg || msg.scrollWidth <= msg.clientWidth + 1) return;
        var key = main.getAttribute('data-key');
        main.setAttribute('role', 'button');
        main.setAttribute('tabindex', '0');
        main.setAttribute('data-toggle', key);
        main.setAttribute('aria-expanded', String(!!_eventsExpanded[key]));
    });
}

function _eventGroupHtml(group) {
    var meta = _eventSeverityMeta({severity: group.severity});
    var type = _eventTypeLabel(group.eventType);
    var newest = formatDocsightTime(group.newest.timestamp, 'time');
    var oldest = formatDocsightTime(group.oldest.timestamp, 'time');
    var span = oldest + '–' + newest;
    var run = _eventFmt('event_run_count', '{count} in a row', group.events.length);
    var label = type + ', ' + run + ', ' + span;
    var open = !!_eventsExpanded[group.key];
    var listId = 'event-group-' + group.key;
    var unacked = DOCSightEventLogData.unacknowledgedIds(group.events);
    return '<li class="ev-row ev-group ev-sev-' + group.severity + (unacked.length ? '' : ' ev-acked') + '" data-key="' + group.key + '">' +
        _eventSelectBox(unacked, label) +
        '<button type="button" class="ev-main" data-toggle="' + group.key + '" aria-expanded="' + open + '" aria-controls="' + listId + '">' +
            '<time class="ev-time" datetime="' + escapeHtml(String(group.newest.timestamp)) + '">' + escapeHtml(newest) + '</time>' +
            _eventSevIcon(meta) +
            '<span class="ev-type">' + escapeHtml(type) + '</span>' +
            '<span class="ev-run"><span aria-hidden="true">' + group.events.length + '×</span><span class="sr-only">' + escapeHtml(run) + '</span></span>' +
            '<span class="ev-msg">' + formatEventMessage(group.newest) + '</span>' +
            '<i data-lucide="chevron-down" class="ev-chevron" aria-hidden="true"></i>' +
        '</button>' +
        _eventAckButton(unacked, label) +
        '<ol class="ev-group-members" id="' + listId + '"' + (open ? '' : ' hidden') + '>' +
            group.events.map(function(ev) { return _eventRowHtml(ev, true); }).join('') +
        '</ol>' +
    '</li>';
}

function _renderEventTimeline() {
    var feed = document.getElementById('events-feed');
    if (!feed) return;
    feed.innerHTML = DOCSightEventLogData.buildTimeline(_eventsLoaded).map(function(day) {
        var headId = 'events-day-' + (day.day || 'unknown');
        var parts = _eventDayParts(day.day);
        return '<section class="ev-day" aria-labelledby="' + headId + '">' +
            '<h3 class="ev-day-head" id="' + headId + '"><span class="ev-day-name">' + escapeHtml(parts.name) + '</span>' +
                '<span class="ev-day-date">' + escapeHtml(parts.date) + '</span></h3>' +
            '<ol class="ev-rows">' + day.items.map(function(item) {
                return item.kind === 'group' ? _eventGroupHtml(item) : _eventRowHtml(item.event);
            }).join('') + '</ol>' +
        '</section>';
    }).join('');
    _syncEventSelection();
    if (typeof lucide !== 'undefined') lucide.createIcons();
    _markTruncatedEventRows(feed);
}

/* ── Selection and acknowledgement ── */
function _eventIds(value) {
    return String(value || '').split(',').map(Number).filter(function(id) { return id > 0; });
}

function _selectedEventIds() {
    return _eventsLoaded.filter(function(ev) {
        return _eventsSelected[ev.id] && !ev.acknowledged;
    }).map(function(ev) { return ev.id; });
}

function _syncEventSelection() {
    var feed = document.getElementById('events-feed');
    if (feed && feed.querySelectorAll) {
        feed.querySelectorAll('.ev-select input').forEach(function(input) {
            var ids = _eventIds(input.getAttribute('data-ids'));
            var picked = ids.filter(function(id) { return _eventsSelected[id]; }).length;
            input.checked = picked > 0 && picked === ids.length;
            input.indeterminate = picked > 0 && picked < ids.length;
        });
    }
    var selected = _selectedEventIds().length;
    var selectedBtn = document.getElementById('btn-ack-selected');
    var visibleBtn = document.getElementById('btn-ack-visible');
    var summary = document.getElementById('events-summary');
    if (selectedBtn) {
        selectedBtn.hidden = !selected;
        selectedBtn.textContent = _eventFmt('event_acknowledge_selected', 'Acknowledge selected ({count})', selected);
    }
    if (visibleBtn) visibleBtn.hidden = !DOCSightEventLogData.unacknowledgedIds(_eventsLoaded).length;
    if (summary) summary.textContent = _eventsLoaded.length ? _eventFmt('event_count_shown', '{count} events shown', _eventsLoaded.length) : '';
}

function _postEventAcknowledgements(ids, undo) {
    var chunks = [];
    for (var i = 0; i < ids.length; i += _eventsAckChunk) chunks.push(ids.slice(i, i + _eventsAckChunk));
    var url = docsightUrl(undo ? '/api/events/unacknowledge' : '/api/events/acknowledge');
    return Promise.all(chunks.map(function(chunk) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ids: chunk})
        }).then(function(r) {
            if (!r.ok) throw new Error('Acknowledge request failed');
            return r.json();
        });
    }));
}

function _focusEventRow(key) {
    var feed = document.getElementById('events-feed');
    if (!feed || !feed.querySelector) return;
    var target = (key && feed.querySelector('[data-toggle="' + key + '"]')) || feed.querySelector('.ev-main');
    if (target) target.focus();
}

/* Acknowledges the given ids, then updates the loaded rows in place so the
   scroll position, open details and pagination survive. */
function acknowledgeEvents(ids, focusKey) {
    if (!ids.length) return Promise.resolve();
    return _postEventAcknowledgements(ids).then(function() {
        DOCSightEventLogData.markAcknowledged(_eventsLoaded, ids);
        ids.forEach(function(id) { delete _eventsSelected[id]; });
        _renderEventTimeline();
        _focusEventRow(focusKey);
        refreshEventBadge();
        // Acknowledging applies at once; the toast offers to take it back instead of asking first.
        if (typeof showToast === 'function') {
            showToast(ids.length === 1
                ? (T.event_ack_done_one || 'Event acknowledged')
                : _eventFmt('event_ack_done_many', '{count} events acknowledged', ids.length), 'info', {
                action: {label: T.undo || 'Undo', onClick: function() { undoEventAcknowledgements(ids, focusKey); }}
            });
        }
    }).catch(function() {
        if (typeof showToast === 'function') showToast(T.network_error || 'Error', 'error');
    });
}

function undoEventAcknowledgements(ids, focusKey) {
    return _postEventAcknowledgements(ids, true).then(function() {
        DOCSightEventLogData.markUnacknowledged(_eventsLoaded, ids);
        _renderEventTimeline();
        _focusEventRow(focusKey);
        refreshEventBadge();
    }).catch(function() {
        if (typeof showToast === 'function') showToast(T.network_error || 'Error', 'error');
    });
}

function acknowledgeSelectedEvents() {
    return acknowledgeEvents(_selectedEventIds());
}

function acknowledgeVisibleEvents() {
    return acknowledgeEvents(DOCSightEventLogData.unacknowledgedIds(_eventsLoaded));
}

document.addEventListener('click', function(event) {
    var target = event.target;
    if (!target || !target.closest || !target.closest('#events-feed')) return;
    var ack = target.closest('[data-ack]');
    if (ack) {
        var row = ack.closest('[data-key]');
        acknowledgeEvents(_eventIds(ack.getAttribute('data-ack')), row && row.getAttribute('data-key'));
        return;
    }
    var toggle = target.closest('[data-toggle]');
    if (toggle) _toggleEventRow(toggle);
});

document.addEventListener('keydown', function(event) {
    var target = event.target;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    if (!target || !target.matches || !target.matches('#events-feed div[data-toggle]')) return;
    event.preventDefault();
    _toggleEventRow(target);
});

function _toggleEventRow(toggle) {
    var key = toggle.getAttribute('data-toggle');
    var open = toggle.getAttribute('aria-expanded') !== 'true';
    var controls = toggle.getAttribute('aria-controls');
    var panel = controls ? document.getElementById(controls) : null;
    if (open) _eventsExpanded[key] = true;
    else delete _eventsExpanded[key];
    toggle.setAttribute('aria-expanded', String(open));
    if (panel) panel.hidden = !open;
}

document.addEventListener('change', function(event) {
    var input = event.target;
    if (!input || !input.matches || !input.matches('#events-feed .ev-select input')) return;
    _eventIds(input.getAttribute('data-ids')).forEach(function(id) {
        if (input.checked) _eventsSelected[id] = true;
        else delete _eventsSelected[id];
    });
    _syncEventSelection();
});

function loadEvents(append) {
    var offset = append ? _eventsLoaded.length : 0;
    var feedRequestId = ++_eventsRequestCount;
    var params = '?limit=' + _eventsPageSize + '&offset=' + offset;
    if (_currentSeverityFilter) params += '&severity=' + _currentSeverityFilter;
    if (_hideOperational) params += '&exclude_operational=true';
    if (_deviceOnlyFilter) params += '&event_prefix=device_';

    updateEventsExportLink();

    var feedCard = document.getElementById('events-feed-card');
    var empty = document.getElementById('events-empty');
    var loading = document.getElementById('events-loading');
    var moreBtn = document.getElementById('events-show-more');

    moreBtn.hidden = true;
    if (!append) {
        loading.hidden = false;
        feedCard.hidden = true;
        DOCSightEmptyState.hide(empty);
        _eventsLoaded = [];
        _eventsExpanded = {};
        _eventsSelected = {};
        _renderEventTimeline();
    }

    fetch(docsightUrl('/api/events' + params))
        .then(function(r) {
            if (!r.ok) throw new Error('Event request failed');
            return r.json();
        })
        .then(function(data) {
            if (feedRequestId !== _eventsRequestCount) return;
            loading.hidden = true;
            DOCSightEmptyState.hide(empty);
            var events = data.events || [];
            if (events.length === 0 && !append) {
                feedCard.hidden = false;
                _showEventsEmpty(empty);
                return;
            }
            // New events shift later pages; skip rows that are already shown.
            var known = {};
            _eventsLoaded.forEach(function(ev) { known[ev.id] = true; });
            events.forEach(function(ev) {
                if (known[ev.id]) return;
                known[ev.id] = true;
                _eventsLoaded.push(ev);
            });
            _renderEventTimeline();
            feedCard.hidden = false;
            moreBtn.hidden = events.length < _eventsPageSize;
        })
        .catch(function() {
            if (feedRequestId !== _eventsRequestCount) return;
            moreBtn.hidden = !append;
            loading.hidden = true;
            DOCSightEmptyState.showError(empty, {retry: append ? loadMoreEvents : function() { loadEvents(); }});
        });
}

/* With a severity or device filter the log may only look empty; without one
   nothing has happened yet, so the useful next step is getting notified. */
function _showEventsEmpty(empty) {
    if (_currentSeverityFilter || _deviceOnlyFilter) {
        DOCSightEmptyState.show(empty, {
            icon: 'sliders-horizontal',
            title: T.event_empty_filtered_title || 'No events match these filters',
            text: T.event_empty_filtered_text,
            action: {label: T.event_empty_reset || 'Show all events', onClick: resetEventFilters},
            glossary: 'event_log'
        });
        return;
    }
    DOCSightEmptyState.show(empty, {
        icon: 'bell',
        title: T.event_empty_title || 'No events yet',
        text: T.event_no_events,
        action: {label: T.event_empty_action || 'Set up notifications', href: docsightUrl('/settings#notifications')},
        glossary: 'event_log'
    });
}

function resetEventFilters() {
    if (_deviceOnlyFilter) {
        _deviceOnlyFilter = false;
        var pill = document.getElementById('device-filter-pill');
        if (pill) _setEventFilterPressed(pill, false);
    }
    filterEventsBySeverity('');
}

function loadMoreEvents() {
    loadEvents(true);
}

function updateEventBadge(count) {
    var badge = document.getElementById('event-badge');
    if (!badge) return;
    if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.hidden = false;
    } else {
        badge.hidden = true;
    }
}

/* The badge counts unacknowledged warnings and critical events of the last
   24 hours, independent of the log filters. */
window.refreshEventBadge = function() {
    var requestId = ++_badgeRequestCount;
    fetch(docsightUrl('/api/events/count?scope=attention&t=' + Date.now()))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (requestId === _badgeRequestCount) updateEventBadge(data.count || 0);
        })
        .catch(function() {});
};

// Fetch badge count on page load
refreshEventBadge();

// Periodically refresh badge count
setInterval(refreshEventBadge, 60000);

/* ── Home: three most recent events ── */
var _homeEventsRequestCount = 0;

function _homeEventTime(timestamp) {
    var when = docsightParseTime(timestamp).getTime();
    var recent = isFinite(when) && Date.now() - when < 20 * 3600 * 1000;
    return formatDocsightTime(timestamp, recent ? 'time' : 'monthday-time');
}

function loadHomeEvents() {
    var list = document.getElementById('home-events-list');
    if (!list) return;
    var requestId = ++_homeEventsRequestCount;
    fetch(docsightUrl('/api/events?limit=3&exclude_operational=true'))
        .then(function(r) {
            if (!r.ok) throw new Error('Event request failed');
            return r.json();
        })
        .then(function(data) {
            if (requestId !== _homeEventsRequestCount) return;
            var current = document.getElementById('home-events-list');
            if (!current) return;
            var events = (data && data.events) || [];
            current.textContent = '';
            if (!events.length) {
                var empty = document.createElement('li');
                empty.className = 'home-events-empty';
                empty.textContent = current.dataset.empty || T.event_no_events || 'No events yet.';
                current.appendChild(empty);
                return;
            }
            events.forEach(function(ev) {
                var meta = _eventSeverityMeta(ev);
                var severity = meta.severity;
                var item = document.createElement('li');
                item.innerHTML =
                    '<a class="home-event home-event-' + severity + '" href="#events">' +
                        '<span class="home-event-time">' + escapeHtml(_homeEventTime(ev.timestamp)) + '</span>' +
                        '<i data-lucide="' + meta.icon + '" class="home-event-icon" aria-label="' + escapeHtml(meta.label) + '"></i>' +
                        '<span class="home-event-text"><b>' + escapeHtml(_eventTypeLabel(ev.event_type)) + '</b>' + formatEventMessage(ev) + '</span>' +
                    '</a>';
                current.appendChild(item);
            });
            if (typeof lucide !== 'undefined') lucide.createIcons();
        })
        .catch(function() {});
}
window.loadHomeEvents = loadHomeEvents;

loadHomeEvents();
