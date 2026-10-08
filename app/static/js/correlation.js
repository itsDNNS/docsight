/* ═══ DOCSight Correlation Analysis Module ═══ */

/* ═══ Correlation Analysis ═══ */
var _correlationData = [];
var _corrVisible = { snr: true, txPower: true, dsPower: true, download: true, upload: true, events: false, errors: true, signalState: true, temperature: true, segmentDs: true, segmentUs: false, reachability: true };
var _corrWeatherData = [];
var _corrSegmentData = [];
var _corrTargetData = [];
var _corrCmState = typeof CORRELATION_CM_AVAILABLE !== 'undefined' && CORRELATION_CM_AVAILABLE ? 'targets_absent' : 'module_absent';
var _corrSelectedRange = null;
var _corrChartState = null; // Stores scales/data for tooltip lookups
var _corrZoom = null; // { tMin, tMax } when zoomed in
// Event type/severity sub-filter: operational events hidden by default
var _corrEventFilter = {};
var _corrEventSeverityFilter = {};
var _OPERATIONAL_EVENTS = { monitoring_started: true, monitoring_stopped: true };
var CorrelationData = window.DOCSightCorrelationData;
var CorrelationChart = window.DOCSightCorrelationChart;
function _corrCloseEventPopover() {
    var pop = document.getElementById('corr-event-popover');
    if (!pop) return;
    if (pop._corrCleanup) pop._corrCleanup();
    pop.remove();
}
function _corrPositionEventPopover(pop, anchor) {
    if (!pop || !anchor) return;
    var margin = 8;
    var anchorRect = anchor.getBoundingClientRect();
    pop.style.maxHeight = Math.max(160, window.innerHeight - (margin * 2)) + 'px';

    // Measure after attaching to the body so positioning is based on the real viewport.
    var popRect = pop.getBoundingClientRect();
    var left = anchorRect.left;
    if (left + popRect.width > window.innerWidth - margin) {
        left = window.innerWidth - margin - popRect.width;
    }
    left = Math.max(margin, left);

    var top = anchorRect.bottom + margin;
    if (top + popRect.height > window.innerHeight - margin) {
        top = anchorRect.top - popRect.height - margin;
    }
    top = Math.max(margin, top);

    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
}
function _corrEscapeAttr(value) {
    return escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
/* Colors computed at runtime reach CSS as --corr-color through the CSSOM,
   never as inline style attributes in built HTML. */
function _corrApplyColors(root) {
    root.querySelectorAll('[data-color]').forEach(function(el) {
        el.style.setProperty('--corr-color', el.getAttribute('data-color'));
    });
}
function _corrEnsureEventSeverityFilter(eventType) {
    if (!(eventType in _corrEventSeverityFilter)) {
        _corrEventSeverityFilter[eventType] = { info: true, warning: true, critical: true };
    }
    return _corrEventSeverityFilter[eventType];
}
function _corrEventTypeAllowed(e) {
    var t = e.event_type || 'unknown';
    if (!(t in _corrEventFilter)) _corrEventFilter[t] = !_OPERATIONAL_EVENTS[t];
    return _corrEventFilter[t];
}
function _corrEventSeverityAllowed(e) {
    var t = e.event_type || 'unknown';
    var severity = CorrelationData.normalizeSeverity(e);
    var severityFilter = _corrEnsureEventSeverityFilter(t);
    if (!(severity in severityFilter)) severityFilter[severity] = true;
    return severityFilter[severity] !== false;
}
function _corrEventAllowed(e) {
    return _corrEventTypeAllowed(e) && _corrEventSeverityAllowed(e);
}
function _corrFilteredEvents(events) {
    if (!_corrVisible.events) return [];
    return events.filter(function(e) {
        return _corrEventAllowed(e);
    });
}

function _corrFormatTimestamp(timestamp) {
    return formatDocsightTime(timestamp, 'datetime', true);
}

function _corrSetOverlayActionable(overlay, actionable) {
    if (!overlay) return;
    overlay.setAttribute('role', actionable ? 'button' : 'img');
    if (actionable) overlay.setAttribute('tabindex', '0');
    else overlay.removeAttribute('tabindex');
}

// Resolves to {state, targets}; the caller keeps it only if it is still the latest load.
function _corrFetchReachability(startEpoch, endEpoch, maxPoints) {
    if (typeof CORRELATION_CM_AVAILABLE === 'undefined' || !CORRELATION_CM_AVAILABLE) {
        return Promise.resolve({state: 'module_absent', targets: []});
    }
    var boundedPoints = Math.min(1000, Math.max(1, Number(maxPoints) || 300));
    return fetch(docsightUrl('/api/connection-monitor/targets'))
        .then(function(response) {
            if (!response.ok) throw new Error('Connection Monitor targets unavailable');
            return response.json();
        })
        .catch(function() { return null; })
        .then(function(targets) {
            if (!targets) return {state: 'fetch_error', targets: []};
            var enabled = targets.filter(function(target) { return !!target.enabled; });
            if (enabled.length === 0) return {state: 'targets_absent', targets: []};
            var requests = enabled.map(function(target) {
                var url = docsightUrl('/api/connection-monitor/samples/' + target.id
                    + '?start=' + encodeURIComponent(startEpoch)
                    + '&end=' + encodeURIComponent(endEpoch)
                    + '&resolution=auto&max_points=' + encodeURIComponent(boundedPoints)
                    + '&limit=0');
                return fetch(url)
                    .then(function(response) {
                        if (!response.ok) throw new Error('Connection Monitor samples unavailable');
                        return response.json();
                    })
                    .then(function(payload) {
                        return { target: target, samples: Array.isArray(payload.samples) ? payload.samples : [], meta: payload.meta || null };
                    })
                    .catch(function() { return null; });
            });
            return Promise.all(requests).then(function(results) {
                if (results.some(function(result) { return result === null; })) return {state: 'fetch_error', targets: []};
                var allSamples = results.reduce(function(total, entry) { return total + entry.samples.length; }, 0);
                if (allSamples === 0) return {state: 'no_samples', targets: results};
                var startMs = startEpoch * 1000;
                var endMs = endEpoch * 1000;
                var intersects = results.some(function(entry) {
                    return entry.samples.some(function(sample) {
                        var interval = CorrelationData.sampleInterval(sample, entry.target);
                        return interval && interval.startMs < endMs && interval.endMs > startMs;
                    });
                });
                return intersects ? {state: 'ready', targets: results} : {state: 'samples_outside_range', targets: []};
            });
        });
}

// Re-render chart when the container gets wider or narrower. The height follows the
// visible lanes and is set by the render itself, so height changes must not re-render
// (that would replace the overlay in the middle of a hover or drag).
(function() {
    var resizeTimer;
    var lastWidth = null;
    var observer = new ResizeObserver(function(entries) {
        var width = entries.length ? Math.round(entries[entries.length - 1].contentRect.width) : null;
        // A hidden container measures 0; the chart is drawn when it is shown, so that
        // first visible width is not a resize either.
        if (!width || width === lastWidth) return;
        var firstMeasurement = lastWidth === null;
        lastWidth = width;
        if (firstMeasurement) return;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function() {
            if ((_correlationData && _correlationData.length > 0) || _corrTargetData.length > 0) {
                renderCorrelationChart(_correlationData);
            }
        }, 150);
    });
    document.addEventListener('DOMContentLoaded', function() {
        var wrap = document.getElementById('correlation-chart');
        if (wrap && wrap.parentElement) observer.observe(wrap.parentElement);
    });
})();

/* The channel status track follows the selected correlation range and its end. */
function _corrLoadStatusTrack(range, startMs, endParam) {
    var section = document.getElementById('correlation-status');
    if (!section || !window.DOCSightStatusTrack) return;
    var query = endParam
        ? 'start=' + encodeURIComponent(DOCSightWindowShift.toParam(startMs) + ':00') + '&end=' + encodeURIComponent(endParam + ':00')
        : 'range=' + encodeURIComponent(range);
    window.DOCSightStatusTrack.load(document.getElementById('correlation-status-track'), query, {
        range: range,
        idPrefix: 'correlation-status',
        timelineRange: function() { return range; }
    }).then(function(shown) { section.hidden = !shown; });
}

// The window ends now unless the arrows (or a swipe) moved it into the past.
var _corrWindow = DOCSightWindowShift.create('correlation', {
    hours: function() { return CorrelationData.rangeHours(getPillValue('correlation-tabs')); },
    onChange: function() {
        _corrWriteViewState();
        loadCorrelationData();
    },
    swipeArea: document.getElementById('correlation-chart-container'),
    swipeTarget: '.correlation-overlay'
});

function _corrWriteViewState() {
    docsightWriteViewState('correlation', {range: getPillValue('correlation-tabs') || '1d', end: _corrWindow.param()});
}

/* A range tab was picked: keep it in the URL, then load. */
function correlationRangeSelected() {
    _corrWriteViewState();
    _corrWindow.sync();
    loadCorrelationData();
}

function applyCorrelationViewState() {
    var state = docsightReadViewState('correlation');
    docsightSelectSegment('correlation-tabs', 'data-value', state.range);
    _corrWindow.restore(state.end);
}

var _corrLoadSeq = 0;

function loadCorrelationData() {
    // Quick steps or range clicks overlap; only the latest request may draw.
    var seq = ++_corrLoadSeq;
    var hours = CorrelationData.rangeHours(getPillValue('correlation-tabs'));
    var endParam = _corrWindow.param();
    var now = new Date(endParam ? DOCSightWindowShift.fromParam(endParam) : Date.now());
    _corrLoadStatusTrack(getPillValue('correlation-tabs') || '1d', now.getTime() - parseInt(hours) * 3600000, endParam);

    var loading = document.getElementById('correlation-loading');
    var noData = document.getElementById('correlation-no-data');
    var chartContainer = document.getElementById('correlation-chart-container');
    var tableCard = document.getElementById('correlation-table-card');
    var overlay = document.getElementById('correlation-overlay');
    _corrSetOverlayActionable(overlay, false);
    if (overlay) overlay.setAttribute('aria-label', T.correlation_chart_aria_label || 'Signal correlation chart');
    loading.hidden = false;
    DOCSightEmptyState.hide(noData);
    chartContainer.hidden = true;
    tableCard.hidden = true;

    /* Calculate time range for weather fetch */
    var wEnd = now.toISOString().substring(0, 19) + 'Z';
    var wStart = new Date(now.getTime() - parseInt(hours) * 3600000).toISOString().substring(0, 19) + 'Z';
    var startEpoch = Math.floor(new Date(wStart).getTime() / 1000);
    var endEpoch = Math.ceil(new Date(wEnd).getTime() / 1000);
    _corrSelectedRange = { startMs: startEpoch * 1000, endMs: endEpoch * 1000 };
    var weatherUrl = docsightUrl('/api/weather/range?start=' + encodeURIComponent(wStart) + '&end=' + encodeURIComponent(wEnd));

    var segmentUrl = docsightUrl('/api/fritzbox/segment-utilization/range?start=' + encodeURIComponent(wStart) + '&end=' + encodeURIComponent(wEnd));

    Promise.all([
        fetch(docsightUrl('/api/correlation?hours=' + hours + '&sources=modem,speedtest,events,capture' + (endParam ? '&end=' + encodeURIComponent(endParam) : ''))).then(function(r) { return r.json(); }),
        fetch(weatherUrl).then(function(r) { return r.json(); }).catch(function() { return []; }),
        fetch(segmentUrl).then(function(r) { return r.json(); }).catch(function() { return []; }),
        _corrFetchReachability(startEpoch, endEpoch, 300).catch(function() {
            return {state: 'fetch_error', targets: []};
        })
    ]).then(function(results) {
            if (seq !== _corrLoadSeq) return;
            var data = Array.isArray(results[0]) ? results[0] : [];
            _corrCmState = results[3].state;
            _corrTargetData = results[3].targets;
            _corrWeatherData = results[1] || [];
            _corrSegmentData = results[2] || [];
            loading.hidden = true;
            _correlationData = data;
            var hasReachability = _corrTargetData.some(function(entry) { return entry.samples && entry.samples.length > 0; });
            if (data.length === 0 && !hasReachability) {
                DOCSightEmptyState.showRange(noData, {tabs: 'correlation-tabs', glossary: 'correlation_analysis'});
                return;
            }
            chartContainer.hidden = false;
            tableCard.hidden = data.length === 0;
            renderCorrelationChart(data);
            if (data.length > 0) renderCorrelationTable(data);
        })
        .catch(function() {
            if (seq !== _corrLoadSeq) return;
            loading.hidden = true;
            DOCSightEmptyState.showError(noData, {retry: loadCorrelationData});
        });
}

function renderCorrelationChart(data) {
    _corrCloseEventPopover();
    // Clear pin state when chart is redrawn (legend toggle, zoom, resize)
    if (_corrPinnedRow) _corrUnpinRow();
    var canvas = document.getElementById('correlation-chart');
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.parentElement.getBoundingClientRect().width;
    var prep = CorrelationChart.prepare({
        data: data, weather: _corrWeatherData, segment: _corrSegmentData, targets: _corrTargetData, visible: _corrVisible
    });
    var H = prep.layout.height;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    // Setup overlay canvas to match main canvas
    var overlay = document.getElementById('correlation-overlay');
    _corrSetOverlayActionable(overlay, false);
    overlay.setAttribute('aria-label', T.correlation_chart_aria_label || 'Signal correlation chart');
    overlay.width = W * dpr;
    overlay.height = H * dpr;
    overlay.style.width = W + 'px';
    overlay.style.height = H + 'px';
    var octx = overlay.getContext('2d');
    octx.scale(dpr, dpr);
    octx.clearRect(0, 0, W, H);

    var rootStyle = getComputedStyle(document.documentElement);
    var colors = CorrelationChart.colors(function(prop, fallback) { return rootStyle.getPropertyValue(prop).trim() || fallback; });
    if (prep.empty) {
        ctx.fillStyle = colors.text;
        ctx.font = '13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(T.correlation_no_data, W / 2, H / 2);
        return;
    }

    ctx.font = '12px system-ui, sans-serif';
    var st = CorrelationChart.scales(prep, {
        width: W, visible: _corrVisible, zoom: _corrZoom, selectedRange: _corrSelectedRange,
        fahrenheit: typeof TEMPERATURE_UNIT !== 'undefined' && TEMPERATURE_UNIT === 'fahrenheit',
        measure: function(text) { return ctx.measureText(text).width; },
        parseTime: docsightParseTime, colors: colors, dpr: dpr
    });
    if (!st) return;
    _corrChartState = st;
    var range = getPillValue('correlation-tabs') || '1d';
    CorrelationChart.draw(ctx, st, {
        visible: _corrVisible,
        events: _corrFilteredEvents(st.events),
        parseTime: docsightParseTime,
        axisLabel: function(t) { return docsightFormatXAxisLabel(t, range); },
        labels: {
            state: T.correlation_lane_state || 'Signal state',
            errors: T.correlation_lane_errors || 'Uncorrectable errors per interval',
            speed: T.correlation_lane_speed || 'Speedtests (Mbps) · single measurements',
            segment: T.correlation_lane_segment || 'Segment load (%)',
            events: T.correlation_lane_events || 'Events · ○ info △ warning ◇ critical',
            reachability: T.correlation_lane_reachability || 'Reachability · gaps unknown'
        }
    });
    var modem = st.modem, speedtest = st.speedtest, events = st.events, weather = st.weather, segment = st.segment;
    var reachabilityBuckets = st.reachabilityBuckets, reachabilityLane = st.reachabilityLane;

    // Interactive Legend
    var legend = document.getElementById('correlation-legend');
    var legendItems = [];
    if (modem.length > 0) {
        if (st.hasPowerData) {
            legendItems.push({ metric: 'dsPower', color: colors.dsPower, label: '&#183;&#183; ' + (T.chart_ds_power || 'DS Power (dBmV)') });
        }
        if (st.hasTxData) {
            legendItems.push({ metric: 'txPower', color: colors.txPower, label: '&#9476; ' + (T.chart_us_power || 'US Power (dBmV)') });
        }
        legendItems.push({ metric: 'snr', color: colors.snr, label: '&#9644; ' + (T.chart_snr || 'SNR (dB)') });
        legendItems.push({ metric: 'signalState', color: colors.health.good, label: '&#9646; ' + (T.correlation_lane_state || 'Signal state') });
        if (st.hasErrorData) {
            legendItems.push({ metric: 'errors', color: 'rgba(239,68,68,0.8)', label: '&#9612; ' + (T.correlation_errors || 'Errors') });
        }
    }
    if (speedtest.length > 0) {
        legendItems.push({ metric: 'download', color: colors.download, label: '&#9474;&#9679; ' + (T.correlation_download || 'Download (Mbps)') });
        legendItems.push({ metric: 'upload', color: colors.upload, label: '&#9474;&#9679; ' + (T.correlation_upload || 'Upload (Mbps)') });
    }
    if (events.length > 0) {
        // Populate filters for all event types/severities in current data
        var eventTypes = {};
        var eventSeverityCounts = {};
        var visibleEventCount = 0;
        for (var i = 0; i < events.length; i++) {
            var et = events[i].event_type || 'unknown';
            var sev = CorrelationData.normalizeSeverity(events[i]);
            eventTypes[et] = (eventTypes[et] || 0) + 1;
            if (!(et in eventSeverityCounts)) eventSeverityCounts[et] = {};
            eventSeverityCounts[et][sev] = (eventSeverityCounts[et][sev] || 0) + 1;
            if (!(et in _corrEventFilter)) _corrEventFilter[et] = !_OPERATIONAL_EVENTS[et];
            _corrEnsureEventSeverityFilter(et);
            if (_corrEventAllowed(events[i])) visibleEventCount++;
        }
        legendItems.push({ metric: 'events', color: colors.warn, label: '&#9650; ' + (T.correlation_events || 'Events'), eventTypes: eventTypes, eventSeverityCounts: eventSeverityCounts, visibleEventCount: visibleEventCount, totalEventCount: events.length });
    }
    if (weather.length > 0) {
        legendItems.push({ metric: 'temperature', color: colors.temperature, label: '- - ' + (T.temperature || 'Temperature') + ' (' + (typeof TEMPERATURE_UNIT !== 'undefined' && TEMPERATURE_UNIT === 'fahrenheit' ? '°F' : '°C') + ')' });
    }
    if (segment.length > 0) {
        legendItems.push({ metric: 'segmentDs', color: colors.segmentDs, label: '&#9644; ' + (T.seg_correlation_ds || 'Segment DS (%)') });
        legendItems.push({ metric: 'segmentUs', color: colors.segmentUs, label: '&#9644; ' + (T.seg_correlation_us || 'Segment US (%)') });
    }
    if (reachabilityBuckets.length > 0) {
        legendItems.push({ metric: 'reachability', color: colors.accent, label: '&#9646; ' + (T.correlation_reachability || 'Reachability') });
    }
    legend.innerHTML = legendItems.map(function(item) {
        var cls = _corrVisible[item.metric] ? '' : 'disabled';
        if (item.metric === 'events') {
            var filterBadge = item.visibleEventCount < item.totalEventCount ? ' <span class="corr-legend-filter-count">(' + item.visibleEventCount + '/' + item.totalEventCount + ')</span>' : '';
            var eventCls = cls ? cls + ' corr-legend-events' : 'corr-legend-events';
            return '<span data-metric="events" tabindex="0" role="button" aria-pressed="' + (cls ? 'false' : 'true') + '" class="' + eventCls + '" title="' + (T.correlation_toggle_hint || 'Click to toggle') + '" data-color="' + _corrEscapeAttr(item.color) + '">' + item.label + filterBadge +
                ' <span class="corr-event-filter-btn" title="' + (T.correlation_event_filter || 'Event Filter') + '">&#9881;</span></span>';
        }
        return '<span data-metric="' + item.metric + '" tabindex="0" role="button" aria-pressed="' + (cls ? 'false' : 'true') + '" class="' + cls + '" title="' + (T.correlation_toggle_hint || 'Click to toggle') + '" data-color="' + _corrEscapeAttr(item.color) + '">' + item.label + '</span>';
    }).join('');
    _corrApplyColors(legend);

    var overlayLabel = T.correlation_chart_aria_label || 'Signal correlation chart';
    if (reachabilityBuckets.length > 0) {
        var reachabilityCounts = { ok: 0, degraded: 0, down: 0, unknown: 0 };
        reachabilityBuckets.forEach(function(bucket) { reachabilityCounts[bucket.state]++; });
        overlayLabel += '. ' + (T.correlation_reachability_aria || 'Reachability summary') + ': '
            + (T.correlation_reachability_ok || 'OK') + ' ' + reachabilityCounts.ok + ', '
            + (T.correlation_reachability_degraded || 'Degraded') + ' ' + reachabilityCounts.degraded + ', '
            + (T.correlation_reachability_down || 'Down') + ' ' + reachabilityCounts.down + ', '
            + (T.correlation_reachability_unknown || 'Unknown') + ' ' + reachabilityCounts.unknown + '.';
    }
    overlay.setAttribute('aria-label', overlayLabel);
    _corrSetOverlayActionable(overlay, !!(reachabilityLane && _corrVisible.reachability));

    // Event filter popover
    var filterBtn = legend.querySelector('.corr-event-filter-btn');
    if (filterBtn) {
        filterBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            var existing = document.getElementById('corr-event-popover');
            if (existing) { _corrCloseEventPopover(); return; }
            var pop = document.createElement('div');
            pop.id = 'corr-event-popover';
            pop.className = 'corr-event-popover';
            var typeLabel = {
                health_change: T.event_type_health_change || 'Health Change',
                power_change: T.event_type_power_change || 'Power Change',
                snr_change: T.event_type_snr_change || 'SNR Change',
                channel_change: T.event_type_channel_change || 'Channel Change',
                modulation_change: T.event_type_modulation_change || 'Modulation Change',
                error_spike: T.event_type_error_spike || 'Error Spike',
                monitoring_started: T.event_type_monitoring_started || 'Monitoring Started',
                monitoring_stopped: T.event_type_monitoring_stopped || 'Monitoring Stopped'
            };
            var severityLabel = {
                info: T.event_severity_info || 'Info',
                warning: T.event_severity_warning || 'Warning',
                critical: T.event_severity_critical || 'Critical'
            };
            var html = '<div class="corr-event-filter-title">' + (T.event_filter_title || 'Event Types') + '</div>';
            var sortedTypes = Object.keys(eventTypes).sort();
            for (var si = 0; si < sortedTypes.length; si++) {
                var et = sortedTypes[si];
                var checked = _corrEventFilter[et] ? ' checked' : '';
                var label = typeLabel[et] || et.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
                var severityFilter = _corrEnsureEventSeverityFilter(et);
                html += '<div class="corr-event-filter-group">' +
                    '<label class="corr-event-filter-type">' +
                    '<input type="checkbox" data-event-type="' + _corrEscapeAttr(et) + '"' + checked + ' data-color="' + _corrEscapeAttr(colors.warn) + '"> ' +
                    '<span class="corr-event-filter-name">' + escapeHtml(label) + '</span> <span class="corr-event-filter-count">(' + eventTypes[et] + ')</span></label>' +
                    '<div class="corr-event-filter-severities">';
                for (var sj = 0; sj < CorrelationData.SEVERITIES.length; sj++) {
                    var sv = CorrelationData.SEVERITIES[sj];
                    var svChecked = severityFilter[sv] !== false ? ' checked' : '';
                    var svCount = (eventSeverityCounts[et] && eventSeverityCounts[et][sv]) || 0;
                    html += '<label class="corr-event-filter-severity">' +
                        '<input type="checkbox" data-event-type="' + _corrEscapeAttr(et) + '" data-event-severity="' + _corrEscapeAttr(sv) + '"' + svChecked + ' data-color="' + _corrEscapeAttr(colors.warn) + '"> ' +
                        escapeHtml(severityLabel[sv] || sv) + ' <span class="corr-event-filter-count">(' + svCount + ')</span></label>';
                }
                html += '</div></div>';
            }
            pop.innerHTML = html;
            _corrApplyColors(pop);
            document.body.appendChild(pop);
            _corrPositionEventPopover(pop, filterBtn);
            var positionPopover = function() { _corrPositionEventPopover(pop, filterBtn); };
            var closePopover = null;
            window.addEventListener('resize', positionPopover);
            window.addEventListener('scroll', positionPopover, true);
            pop._corrCleanup = function() {
                window.removeEventListener('resize', positionPopover);
                window.removeEventListener('scroll', positionPopover, true);
                if (closePopover) document.removeEventListener('click', closePopover);
            };
            // Prevent clicks inside popover from bubbling to legend toggle
            pop.addEventListener('click', function(e) { e.stopPropagation(); });
            pop.querySelectorAll('input[data-event-type]:not([data-event-severity])').forEach(function(cb) {
                cb.addEventListener('change', function() {
                    _corrEventFilter[this.getAttribute('data-event-type')] = this.checked;
                    renderCorrelationChart(data);
                    renderCorrelationTable(data);
                });
            });
            pop.querySelectorAll('input[data-event-severity]').forEach(function(cb) {
                cb.addEventListener('change', function() {
                    var eventType = this.getAttribute('data-event-type') || 'unknown';
                    var severity = this.getAttribute('data-event-severity') || 'info';
                    _corrEnsureEventSeverityFilter(eventType)[severity] = this.checked;
                    renderCorrelationChart(data);
                    renderCorrelationTable(data);
                });
            });
            // Close on outside click
            setTimeout(function() {
                closePopover = function(ev) {
                    if (!pop.contains(ev.target) && ev.target !== filterBtn) {
                        _corrCloseEventPopover();
                    }
                };
                document.addEventListener('click', closePopover);
            }, 0);
        });
    }

    // Legend click handlers
    var legendSpans = legend.querySelectorAll('span[data-metric]');
    for (var li = 0; li < legendSpans.length; li++) {
        legendSpans[li].addEventListener('click', function(e) {
            if (e.target.classList.contains('corr-event-filter-btn')) return;
            var metric = this.getAttribute('data-metric');
            // Prevent disabling all metrics
            var visibleCount = 0;
            for (var k in _corrVisible) { if (_corrVisible[k]) visibleCount++; }
            if (_corrVisible[metric] && visibleCount <= 1) return;
            _corrVisible[metric] = !_corrVisible[metric];
            renderCorrelationChart(data);
        });
        legendSpans[li].addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.click();
            }
        });
    }

    // Show/hide zoom reset button
    var zoomBtn = document.getElementById('correlation-zoom-reset');
    if (zoomBtn) zoomBtn.hidden = !_corrZoom;

    // Setup tooltip interaction on overlay canvas
    _setupCorrelationTooltip(overlay, octx);
}

/* Hands the visible window (the zoomed range if zoomed) to the Evidence Journey. */
function _corrUseRangeAsEvidence() {
    var st = _corrChartState;
    if (!st || !isFinite(st.tMin) || !isFinite(st.tMax)) return;
    var timeZone = typeof DOCSIGHT_TIME_ZONE !== 'undefined' ? DOCSIGHT_TIME_ZONE : undefined;
    var from = DOCSightBrowserContracts.localInputValue(st.tMin, timeZone, false);
    var to = DOCSightBrowserContracts.localInputValue(st.tMax, timeZone, true);
    location.hash = '#evidence?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to);
}
window._corrUseRangeAsEvidence = _corrUseRangeAsEvidence;

/* The shown (or zoomed) range joins a case by its days, like events from the log. */
function _corrSaveRangeAsCase() {
    var st = _corrChartState;
    if (!st || !isFinite(st.tMin) || !isFinite(st.tMax) || typeof DOCSightCasePicker === 'undefined') return;
    var timeZone = typeof DOCSIGHT_TIME_ZONE !== 'undefined' ? DOCSIGHT_TIME_ZONE : undefined;
    var from = DOCSightBrowserContracts.localInputValue(st.tMin, timeZone, false).slice(0, 10);
    var to = DOCSightBrowserContracts.localInputValue(st.tMax, timeZone, true).slice(0, 10);
    var range = formatDocsightTime(from, 'date') + (from === to ? '' : ' – ' + formatDocsightTime(to, 'date'));
    DOCSightCasePicker.open({
        startDate: from,
        endDate: to,
        summary: (T.correlation_case_summary || 'Time range {range}').replace('{range}', range),
        name: (T.correlation_case_name || 'Correlation {range}').replace('{range}', range),
        added: T.correlation_added_to_case || 'Time range added to “{case}”'
    });
}
window._corrSaveRangeAsCase = _corrSaveRangeAsCase;

function _corrResetZoom() {
    _corrZoom = null;
    if ((_correlationData && _correlationData.length > 0) || _corrTargetData.length > 0) {
        renderCorrelationChart(_correlationData);
    }
}

function _setupCorrelationTooltip(overlay, octx) {
    var tooltip = document.getElementById('correlation-tooltip');
    var suppressNextClick = overlay._corrSuppressNextClick === true;

    // Remove old listeners by replacing the overlay node
    var newOverlay = overlay.cloneNode(true);
    overlay.parentNode.replaceChild(newOverlay, overlay);
    var newOctx = newOverlay.getContext('2d');
    var st = _corrChartState;
    if (!st) return;
    newOctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
    if (suppressNextClick) {
        setTimeout(function() { suppressNextClick = false; }, 0);
    }

    // Phones: press and hold reads values like hovering does.
    docsightTouchHold(newOverlay, function(touch) {
        newOverlay.dispatchEvent(new MouseEvent('mousemove', {clientX: touch.clientX, clientY: touch.clientY}));
    });

    // Drag-zoom state
    var dragStart = null; // mouseX where drag started

    newOverlay.addEventListener('mousedown', function(e) {
        if (!_corrChartState) return;
        var st = _corrChartState;
        var rect = newOverlay.getBoundingClientRect();
        var mouseX = e.clientX - rect.left;
        if (mouseX >= st.pad.left && mouseX <= st.pad.left + st.plotW) {
            dragStart = mouseX;
        }
    });

    newOverlay.addEventListener('mouseup', function(e) {
        if (!_corrChartState || dragStart === null) return;
        var st = _corrChartState;
        var rect = newOverlay.getBoundingClientRect();
        var mouseX = e.clientX - rect.left;
        var minDrag = 20; // minimum drag distance in px
        if (Math.abs(mouseX - dragStart) > minDrag) {
            var x1 = Math.max(st.pad.left, Math.min(dragStart, mouseX));
            var x2 = Math.min(st.pad.left + st.plotW, Math.max(dragStart, mouseX));
            var t1 = st.tMin + (x1 - st.pad.left) / st.plotW * (st.tMax - st.tMin);
            var t2 = st.tMin + (x2 - st.pad.left) / st.plotW * (st.tMax - st.tMin);
            _corrZoom = { tMin: t1, tMax: t2 };
            dragStart = null;
            // Carry suppression to the replacement overlay rendered below so
            // the click synthesized for this drag cannot trigger drill-down.
            suppressNextClick = true;
            newOverlay._corrSuppressNextClick = true;
            renderCorrelationChart(st.data);
            return;
        }
        dragStart = null;
    });

    function openReachabilityDetail() {
        if (!st.reachabilityLane || !_corrVisible.reachability) return;
        if (typeof switchView !== 'function') return;
        switchView('connection-monitor');
        var detailView = document.getElementById('view-connection-monitor');
        var detailTitle = document.querySelector('#cm-detail-view .view-page-title');
        if (detailView && detailView.classList.contains('active') && detailTitle) detailTitle.focus();
    }

    newOverlay.addEventListener('click', function(e) {
        if (suppressNextClick) {
            suppressNextClick = false;
            return;
        }
        if (!st.reachabilityLane || !_corrVisible.reachability) return;
        var rect = newOverlay.getBoundingClientRect();
        var mouseX = e.clientX - rect.left;
        var mouseY = e.clientY - rect.top;
        if (mouseX >= st.pad.left && mouseX <= st.pad.left + st.plotW
                && mouseY >= st.reachabilityLane.y && mouseY <= st.reachabilityLane.y + st.reachabilityLane.height) {
            openReachabilityDetail();
        }
    });

    newOverlay.addEventListener('keydown', function(e) {
        if ((e.key === 'Enter' || e.key === ' ') && st.reachabilityLane && _corrVisible.reachability) {
            e.preventDefault();
            openReachabilityDetail();
        }
    });

    newOverlay.addEventListener('mousemove', function(e) {
        // Clear pin when user interacts with chart directly
        if (_corrPinnedRow) _corrUnpinRow();
        if (!_corrChartState) return;
        var st = _corrChartState;
        var rect = newOverlay.getBoundingClientRect();
        var mouseX = e.clientX - rect.left;
        var mouseY = e.clientY - rect.top;

        // Draw drag selection overlay
        if (dragStart !== null) {
            newOctx.clearRect(0, 0, st.W, st.H);
            var x1 = Math.max(st.pad.left, Math.min(dragStart, mouseX));
            var x2 = Math.min(st.pad.left + st.plotW, Math.max(dragStart, mouseX));
            var dragHeight = st.layout.bottom - st.pad.top;
            newOctx.fillStyle = 'rgba(168,85,247,0.15)';
            newOctx.fillRect(x1, st.pad.top, x2 - x1, dragHeight);
            newOctx.strokeStyle = 'rgba(168,85,247,0.5)';
            newOctx.lineWidth = 1;
            newOctx.strokeRect(x1, st.pad.top, x2 - x1, dragHeight);
            tooltip.style.display = 'none';
            return;
        }

        // The main band and every lane share one time axis, so the crosshair covers them all.
        var inChart = mouseY >= st.pad.top && mouseY <= st.layout.bottom;
        if (mouseX < st.pad.left || mouseX > st.pad.left + st.plotW || !inChart) {
            newOctx.clearRect(0, 0, st.W, st.H);
            tooltip.style.display = 'none';
            return;
        }

        // Convert mouseX to timestamp
        var tHover = st.tMin + (mouseX - st.pad.left) / st.plotW * (st.tMax - st.tMin);

        var reachabilityBucket = null;
        if (st.reachabilityBuckets && _corrVisible.reachability) {
            for (var rbi = 0; rbi < st.reachabilityBuckets.length; rbi++) {
                var candidateBucket = st.reachabilityBuckets[rbi];
                if (tHover >= candidateBucket.startMs && (tHover < candidateBucket.endMs || (rbi === st.reachabilityBuckets.length - 1 && tHover === candidateBucket.endMs))) {
                    reachabilityBucket = candidateBucket;
                    break;
                }
            }
        }

        // Find nearest modem point whenever any modem-derived series is visible.
        // Previously gated on SNR alone, which hid TX Power / DS Power / Errors from
        // the tooltip when SNR was toggled off (see issue #331). Keeping a multi-flag
        // guard ensures displayTs and the table highlight do not snap to a modem
        // timestamp when every modem series has been hidden.
        var anyModemVisible = _corrVisible.snr || _corrVisible.txPower || _corrVisible.dsPower || _corrVisible.errors || _corrVisible.signalState;
        var nearestModem = anyModemVisible ? st.modem[CorrelationChart.nearestIndex(st.modem, tHover, docsightParseTime)] || null : null;

        // Nearest speedtest whose mark is drawn
        var speedIdx = _corrVisible.download || _corrVisible.upload
            ? CorrelationChart.nearestIndex(st.speedtest, tHover, docsightParseTime, function(i) { return !st.speedMarks[i] || !st.speedMarks[i].visible; })
            : -1;
        var nearestSpeed = speedIdx >= 0 ? st.speedtest[speedIdx] : null;
        var nearestSpeedMark = speedIdx >= 0 ? st.speedMarks[speedIdx] : null;

        // Nearest event (respecting type filter) and weather point
        var visibleEvents = _corrFilteredEvents(st.events);
        var nearestEvent = visibleEvents[CorrelationChart.nearestIndex(visibleEvents, tHover, docsightParseTime)] || null;
        var nearestWeather = _corrVisible.temperature && st.weather
            ? st.weather[CorrelationChart.nearestIndex(st.weather, tHover, docsightParseTime)] || null
            : null;

        // Draw crosshair on overlay
        newOctx.clearRect(0, 0, st.W, st.H);
        newOctx.strokeStyle = 'rgba(255,255,255,0.25)';
        newOctx.lineWidth = 1;
        newOctx.setLineDash([4, 4]);
        newOctx.beginPath();
        newOctx.moveTo(mouseX, st.pad.top);
        newOctx.lineTo(mouseX, st.layout.bottom);
        newOctx.stroke();
        newOctx.setLineDash([]);

        // Draw highlight dots at nearest data points
        var dot = CorrelationChart.drawDot;
        if (nearestModem) {
            var modemX = st.xScale(docsightParseTime(nearestModem.timestamp).getTime());
            if (_corrVisible.snr) dot(newOctx, modemX, st.ySnr(nearestModem.ds_snr_min || st.snrMin), 5, st.colors.snr);
            if (_corrVisible.txPower && nearestModem.us_power_avg) dot(newOctx, modemX, st.yTx(nearestModem.us_power_avg), 5, st.colors.txPower);
            if (_corrVisible.dsPower && nearestModem.ds_power_avg != null) dot(newOctx, modemX, st.yDsPower(nearestModem.ds_power_avg), 5, st.colors.dsPower);
        }
        if (nearestSpeedMark) {
            if (_corrVisible.download && nearestSpeedMark.hasDownload) dot(newOctx, nearestSpeedMark.downloadX, nearestSpeedMark.downloadY, 5, st.colors.download);
            if (_corrVisible.upload && nearestSpeedMark.hasUpload) dot(newOctx, nearestSpeedMark.uploadX, nearestSpeedMark.uploadY, 5, st.colors.upload);
        }
        if (nearestWeather && nearestWeather.temperature != null) {
            dot(newOctx, st.xScale(docsightParseTime(nearestWeather.timestamp).getTime()), st.yTemp(nearestWeather.temperature), 5, st.colors.temperature);
        }

        // Build tooltip content
        var html = '';
        // Use the closest data point's timestamp as the display time
        var displayTs = tHover;
        if (nearestModem) displayTs = docsightParseTime(nearestModem.timestamp).getTime();
        if (nearestSpeed) {
            var spTs = docsightParseTime(nearestSpeed.timestamp).getTime();
            if (!nearestModem || Math.abs(spTs - tHover) < Math.abs(docsightParseTime(nearestModem.timestamp).getTime() - tHover)) {
                displayTs = spTs;
            }
        }
        html += '<div class="tt-time">' + escapeHtml(_corrFormatTimestamp(displayTs)) + '</div>';

        if (nearestModem && _corrVisible.snr) {
            html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.snr) + '"></span> ' + (T.correlation_tt_snr || 'SNR') + ': ' + (nearestModem.ds_snr_min || 0).toFixed(1) + ' dB</div>';
        }
        if (nearestModem && _corrVisible.txPower && nearestModem.us_power_avg) {
            html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.txPower) + '"></span> ' + (T.correlation_tt_tx_power || 'TX Power') + ': ' + nearestModem.us_power_avg.toFixed(1) + ' dBmV</div>';
        }
        if (nearestModem && _corrVisible.dsPower && nearestModem.ds_power_avg != null) {
            html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.dsPower) + '"></span> ' + (T.correlation_tt_ds_power || 'DS Power') + ': ' + nearestModem.ds_power_avg.toFixed(1) + ' dBmV</div>';
        }
        if (nearestModem && _corrVisible.signalState && st.colors.health[nearestModem.health]) {
            var stateLabels = { good: T.health_good, tolerated: T.health_tolerated, marginal: T.health_marginal, critical: T.health_critical };
            html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.health[nearestModem.health]) + '"></span> '
                + (T.correlation_lane_state || 'Signal state') + ': ' + escapeHtml(stateLabels[nearestModem.health] || nearestModem.health) + '</div>';
        }
        if (nearestModem && _corrVisible.errors) {
            var errorDelta = st.errorDeltas[st.modem.indexOf(nearestModem)];
            if (errorDelta && errorDelta.delta) {
                html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.errors) + '"></span> '
                    + (T.correlation_tt_errors || 'Errors') + ': +' + errorDelta.delta.toLocaleString()
                    + ' (' + (T.correlation_tt_errors_total || 'total') + ' ' + nearestModem.ds_uncorrectable_errors.toLocaleString() + ')</div>';
            }
        }
        if (nearestSpeed) {
            var speedDownload = CorrelationData.measurement(nearestSpeed.download_mbps);
            var speedUpload = CorrelationData.measurement(nearestSpeed.upload_mbps);
            var speedPing = CorrelationData.measurement(nearestSpeed.ping_ms);
            var speedJitter = CorrelationData.measurement(nearestSpeed.jitter_ms);
            var speedPacketLoss = CorrelationData.measurement(nearestSpeed.packet_loss_pct);
            html += '<div class="tt-row tt-speedtest-time">' + (T.timestamp || 'Timestamp') + ': ' + escapeHtml(_corrFormatTimestamp(nearestSpeed.timestamp)) + '</div>';
            if (_corrVisible.download && speedDownload !== null) {
                html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.download) + '"></span> ' + (T.correlation_tt_download || 'Download') + ': ' + speedDownload.toFixed(1) + ' Mbps</div>';
            }
            if (_corrVisible.upload && speedUpload !== null) {
                html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.upload) + '"></span> ' + (T.correlation_tt_upload || 'Upload') + ': ' + speedUpload.toFixed(1) + ' Mbps</div>';
            }
            if (speedPing !== null) {
                html += '<div class="tt-row">' + (T.speedtest_ping || T.ping || 'Ping') + ': ' + speedPing.toFixed(1) + ' ms</div>';
            }
            if (speedJitter !== null) {
                html += '<div class="tt-row">' + (T.jitter || 'Jitter') + ': ' + speedJitter.toFixed(1) + ' ms</div>';
            }
            if (speedPacketLoss !== null) {
                html += '<div class="tt-row">' + (T.packet_loss || 'Packet Loss') + ': ' + speedPacketLoss.toFixed(1) + '%</div>';
            }
        }
        if (nearestEvent && _corrVisible.events) {
            html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.event) + '"></span> ' + (T.correlation_tt_event || 'Event') + ': ' + escapeHtml(typeof _eventTypeLabel === 'function' ? _eventTypeLabel(nearestEvent.event_type) : (nearestEvent.event_type || nearestEvent.severity || '')) + '</div>';
        }
        if (nearestWeather && _corrVisible.temperature && nearestWeather.temperature != null) {
            html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.temperature) + '"></span> ' + (T.temperature || 'Temperature') + ': ' + fmtTemp(nearestWeather.temperature) + '</div>';
        }
        if (reachabilityBucket) {
            var stateLabels = {
                ok: T.correlation_reachability_ok || 'OK',
                degraded: T.correlation_reachability_degraded || 'Degraded',
                down: T.correlation_reachability_down || 'Down',
                unknown: T.correlation_reachability_unknown || 'Unknown'
            };
            html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.reachability[reachabilityBucket.state]) + '"></span> '
                + (T.correlation_reachability || 'Reachability') + ' — '
                + (T.correlation_reachability_state || 'State') + ': ' + stateLabels[reachabilityBucket.state] + '</div>';
            html += '<div class="tt-row">' + (T.correlation_reachability_window || 'Window') + ': '
                + escapeHtml(_corrFormatTimestamp(new Date(reachabilityBucket.startMs).toISOString())) + ' — '
                + escapeHtml(_corrFormatTimestamp(new Date(reachabilityBucket.endMs).toISOString())) + '</div>';
            html += '<div class="tt-row">' + (T.correlation_reachability_loss || 'Observed packet loss') + ': '
                + (reachabilityBucket.lossPct == null ? '—' : reachabilityBucket.lossPct.toFixed(2) + '%') + '</div>';
            html += '<div class="tt-row">' + (T.correlation_reachability_samples || 'Samples') + ': ' + reachabilityBucket.sampleCount + '</div>';
            html += '<div class="tt-row">' + (T.correlation_reachability_targets || 'Observed targets') + ': ' + reachabilityBucket.targetsObserved + '</div>';
            html += '<div class="tt-row">' + (T.correlation_reachability_scope || 'Target scope') + ': '
                + (reachabilityBucket.targetScope ? escapeHtml(reachabilityBucket.targetScope) : '—') + '</div>';
            html += '<div class="tt-row">' + (T.correlation_reachability_drilldown || 'Open Connection Monitor details') + '</div>';
        }
        // Segment utilization tooltip (numeric-only server data, same innerHTML pattern as above)
        var nearestSeg = st.segment && st.segment[CorrelationChart.nearestIndex(st.segment, tHover, docsightParseTime)];
        if (nearestSeg && Math.abs(docsightParseTime(nearestSeg.timestamp).getTime() - tHover) < (st.tMax - st.tMin) * 0.05) {
            if (_corrVisible.segmentDs && nearestSeg.ds_total != null) {
                html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.segmentDs) + '"></span> ' + (T.seg_correlation_ds || 'Segment DS') + ': ' + nearestSeg.ds_total.toFixed(1) + '%</div>';
            }
            if (_corrVisible.segmentUs && nearestSeg.us_total != null) {
                html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.segmentUs) + '"></span> ' + (T.seg_correlation_us || 'Segment US') + ': ' + nearestSeg.us_total.toFixed(1) + '%</div>';
            }
        }

        tooltip.innerHTML = html;
        _corrApplyColors(tooltip);
        tooltip.style.display = 'block';

        // Position tooltip — forced reflow to measure dimensions is intentional here
        var ttW = tooltip.offsetWidth;
        var ttH = tooltip.offsetHeight;
        var ttX = mouseX + 12;
        var ttY = mouseY - ttH / 2;
        if (ttX + ttW > st.W - 10) {
            ttX = mouseX - ttW - 12;
        }
        if (ttY < 0) ttY = 4;
        if (ttY + ttH > st.H) ttY = st.H - ttH - 4;
        tooltip.style.left = ttX + 'px';
        tooltip.style.top = ttY + 'px';

        // Highlight corresponding table rows (skip if a row is pinned)
        if (!_corrPinnedRow) {
            _corrHighlightTableRows(nearestModem, nearestSpeed, nearestEvent);
        }
    });

    newOverlay.addEventListener('mouseleave', function() {
        dragStart = null;
        if (!_corrChartState) return;
        var st = _corrChartState;
        // Don't clear chart highlight if a row is pinned
        if (!_corrPinnedRow) {
            newOctx.clearRect(0, 0, st.W, st.H);
        }
        tooltip.style.display = 'none';
        if (!_corrPinnedRow) {
            _corrClearTableHighlight();
        }
    });
}

// Highlight matching table rows when hovering on chart
function _corrHighlightTableRows(modemPt, speedPt, eventPt) {
    _corrClearTableHighlight();
    var tbody = document.getElementById('correlation-tbody');
    if (!tbody) return;
    var rows = tbody.querySelectorAll('tr[data-ts]');
    var timestamps = [];
    if (modemPt) timestamps.push(modemPt.timestamp);
    if (speedPt) timestamps.push(speedPt.timestamp);
    if (eventPt) timestamps.push(eventPt.timestamp);
    if (timestamps.length === 0) return;
    var wrap = document.getElementById('correlation-table-wrap');
    var firstMatch = null;
    for (var i = 0; i < rows.length; i++) {
        var rowTs = rows[i].getAttribute('data-ts');
        if (timestamps.indexOf(rowTs) !== -1) {
            rows[i].classList.add('corr-highlight');
            if (!firstMatch) firstMatch = rows[i];
        }
    }
    // Scroll first highlighted row into view within the table wrapper
    if (firstMatch && wrap) {
        var wrapRect = wrap.getBoundingClientRect();
        var rowRect = firstMatch.getBoundingClientRect();
        var thead = wrap.querySelector('thead');
        var theadH = thead ? thead.offsetHeight : 0;
        // Check if row is outside visible area of the wrapper
        if (rowRect.top < wrapRect.top + theadH || rowRect.bottom > wrapRect.bottom) {
            var scrollTarget = rowRect.top - wrapRect.top + wrap.scrollTop - theadH - 8;
            wrap.scrollTo({ top: scrollTarget, behavior: 'smooth' });
        }
    }
}

var _corrPinnedRow = null;
function _corrUnpinRow() {
    if (_corrPinnedRow) {
        _corrPinnedRow.classList.remove('corr-pinned');
        _corrPinnedRow.removeAttribute('aria-selected');
        _corrPinnedRow = null;
    }
    _corrClearTableHighlight();
    _corrClearChartHighlight();
}

function _corrClearTableHighlight() {
    var highlighted = document.querySelectorAll('#correlation-tbody tr.corr-highlight');
    for (var i = 0; i < highlighted.length; i++) {
        highlighted[i].classList.remove('corr-highlight');
    }
}

// Draw highlight on chart overlay when hovering a table row
function _corrHighlightFromTable(timestamp, source) {
    var overlay = document.getElementById('correlation-overlay');
    if (!overlay || !_corrChartState) return;
    var octx = overlay.getContext('2d');
    var st = _corrChartState;
    octx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
    octx.clearRect(0, 0, st.W, st.H);

    var ts = docsightParseTime(timestamp).getTime();
    var x = st.xScale(ts);

    // Draw crosshair
    octx.strokeStyle = 'rgba(255,255,255,0.3)';
    octx.lineWidth = 1;
    octx.setLineDash([4, 4]);
    octx.beginPath();
    octx.moveTo(x, st.pad.top);
    octx.lineTo(x, st.pad.top + st.plotH);
    octx.stroke();
    octx.setLineDash([]);

    // Draw highlight dot based on source
    if (source === 'modem') {
        for (var i = 0; i < st.modem.length; i++) {
            if (st.modem[i].timestamp === timestamp) {
                if (_corrVisible.snr) CorrelationChart.drawDot(octx, x, st.ySnr(st.modem[i].ds_snr_min || st.snrMin), 6, st.colors.snr);
                if (_corrVisible.txPower && st.modem[i].us_power_avg) CorrelationChart.drawDot(octx, x, st.yTx(st.modem[i].us_power_avg), 6, st.colors.txPower);
                break;
            }
        }
    } else if (source === 'speedtest') {
        for (var i = 0; i < st.speedtest.length; i++) {
            if (st.speedtest[i].timestamp === timestamp) {
                var speedMark = st.speedMarks[i];
                if (_corrVisible.download && speedMark.hasDownload) CorrelationChart.drawDot(octx, speedMark.downloadX, speedMark.downloadY, 6, st.colors.download);
                if (_corrVisible.upload && speedMark.hasUpload) CorrelationChart.drawDot(octx, speedMark.uploadX, speedMark.uploadY, 6, st.colors.upload);
                break;
            }
        }
    } else if (source === 'event' && _corrVisible.events) {
        octx.strokeStyle = st.colors.event;
        octx.lineWidth = 2;
        octx.setLineDash([3, 3]);
        octx.beginPath();
        octx.moveTo(x, st.pad.top);
        octx.lineTo(x, st.pad.top + st.plotH);
        octx.stroke();
        octx.setLineDash([]);
    }
}

function _corrClearChartHighlight() {
    var overlay = document.getElementById('correlation-overlay');
    if (!overlay || !_corrChartState) return;
    var octx = overlay.getContext('2d');
    var st = _corrChartState;
    octx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
    octx.clearRect(0, 0, st.W, st.H);
}

function _corrExportPNG() {
    var chart = document.getElementById('correlation-chart');
    if (!chart) return;
    var overlay = document.getElementById('correlation-overlay');

    // Collect visible legend items from DOM (extract only direct text, not child elements)
    var legendEl = document.getElementById('correlation-legend');
    var items = [];
    if (legendEl) {
        var spans = legendEl.querySelectorAll('span[data-metric]');
        for (var i = 0; i < spans.length; i++) {
            if (spans[i].classList.contains('disabled')) continue;
            var label = '';
            for (var n = 0; n < spans[i].childNodes.length; n++) {
                if (spans[i].childNodes[n].nodeType === 3) label += spans[i].childNodes[n].textContent;
            }
            label = label.trim();
            if (label) items.push({ label: label, color: spans[i].style.color || getComputedStyle(spans[i]).color });
        }
    }

    // Build composite canvas: chart + overlay + legend row
    var dpr = window.devicePixelRatio || 1;
    var logicalW = chart.width / dpr;
    var legendH = items.length > 0 ? 36 : 0;
    var exp = document.createElement('canvas');
    exp.width = chart.width;
    exp.height = chart.height + legendH * dpr;
    var ctx = exp.getContext('2d');
    ctx.scale(dpr, dpr);

    // Background
    var bg = getComputedStyle(document.documentElement).getPropertyValue('--card').trim() || '#1a1a2e';
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, exp.width / dpr, exp.height / dpr);

    // Draw chart + overlay (both already at physical resolution)
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(chart, 0, 0);
    if (overlay) ctx.drawImage(overlay, 0, 0);

    // Draw legend (scale down font if it overflows)
    if (items.length > 0) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        var chartH = chart.height / dpr;
        var fontSize = 11;
        var gap = 20;
        var maxW = logicalW - 20;
        ctx.font = fontSize + 'px system-ui, sans-serif';
        var totalW = gap * (items.length - 1);
        for (var j = 0; j < items.length; j++) totalW += ctx.measureText(items[j].label).width;
        if (totalW > maxW && totalW > 0) {
            fontSize = Math.max(8, Math.floor(fontSize * maxW / totalW));
            gap = Math.max(8, Math.floor(gap * maxW / totalW));
            ctx.font = fontSize + 'px system-ui, sans-serif';
            totalW = gap * (items.length - 1);
            for (var r = 0; r < items.length; r++) totalW += ctx.measureText(items[r].label).width;
        }
        var startX = (logicalW - totalW) / 2;
        var y = chartH + legendH / 2 + fontSize / 3;
        for (var k = 0; k < items.length; k++) {
            ctx.fillStyle = items[k].color;
            ctx.fillText(items[k].label, startX, y);
            startX += ctx.measureText(items[k].label).width + gap;
        }
    }

    var link = document.createElement('a');
    link.download = 'correlation-chart-' + new Date().toISOString().slice(0, 10) + '.png';
    link.href = exp.toDataURL('image/png');
    link.click();
}

function _corrExportCSV() {
    var reachabilityBuckets = _corrChartState && _corrChartState.reachabilityBuckets ? _corrChartState.reachabilityBuckets : [];
    if ((!_correlationData || _correlationData.length === 0) && reachabilityBuckets.length === 0) return;
    var rows = CorrelationData.csvRows(_correlationData, reachabilityBuckets);
    var blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    var link = document.createElement('a');
    link.download = 'correlation-data-' + new Date().toISOString().slice(0, 10) + '.csv';
    link.href = URL.createObjectURL(blob);
    link.click();
    URL.revokeObjectURL(link.href);
}

function renderCorrelationTable(data) {
    _corrPinnedRow = null;
    var tbody = document.getElementById('correlation-tbody');
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

    var healthLabels = {
        good: T.health_good,
        tolerated: T.health_tolerated,
        marginal: T.health_marginal,
        critical: T.health_critical
    };
    var sevLabels = {
        info: T.event_severity_info,
        warning: T.event_severity_warning,
        critical: T.event_severity_critical
    };
    var typeLabels = {
        health_change: T.event_type_health_change,
        power_change: T.event_type_power_change,
        snr_change: T.event_type_snr_change,
        channel_change: T.event_type_channel_change,
        modulation_change: T.event_type_modulation_change,
        error_spike: T.event_type_error_spike
    };

    // Pre-filter modem entries: only show health transitions (not repeated same-status)
    // Data is chronological, sorted is reversed (newest first)
    var chronological = data.slice().sort(function(a, b) {
        return docsightParseTime(a.timestamp).getTime() - docsightParseTime(b.timestamp).getTime();
    });
    var modemTransitionTs = {};
    var lastModemHealth = null;
    for (var i = 0; i < chronological.length; i++) {
        if (chronological[i].source !== 'modem') continue;
        var h = chronological[i].health || 'unknown';
        if (h !== lastModemHealth) {
            modemTransitionTs[chronological[i].timestamp] = true;
            lastModemHealth = h;
        }
    }

    // Show newest first in table.
    var sorted = chronological.slice().reverse();
    var maxRows = 200;
    var count = 0;
    for (var i = 0; i < sorted.length && count < maxRows; i++) {
        var e = sorted[i];

        // Skip modem entries that are not health transitions
        if (e.source === 'modem' && !modemTransitionTs[e.timestamp]) continue;
        // Keep table rows aligned with the event filters used by chart markers.
        if (e.source === 'event' && !_corrEventAllowed(e)) continue;

        var tr = document.createElement('tr');
        tr.setAttribute('data-ts', e.timestamp);
        tr.setAttribute('data-src', e.source);
        tr.setAttribute('tabindex', '0');
        tr.setAttribute('role', 'row');
        var ts = escapeHtml(_corrFormatTimestamp(e.timestamp));
        var src = e.source;
        var msg = '';
        var details = '';

        if (src === 'modem') {
            var h = e.health || 'unknown';
            var badge = '<span class="st-health-badge health-' + h + '">' + (healthLabels[h] || h) + '</span>';
            src = '<span class="corr-tone-accent">' + escapeHtml(T.correlation_source_modem || 'Modem') + '</span>';
            msg = badge;
            var modemDetails = [
                (T.correlation_tt_snr || 'SNR') + ' ' + (e.ds_snr_min != null ? e.ds_snr_min + ' dB' : ''),
                (T.event_power || 'Power') + ' ' + (e.ds_power_avg != null ? e.ds_power_avg + ' dBmV' : ''),
                'TX ' + (e.us_power_avg != null ? e.us_power_avg + ' dBmV' : '')
            ];
            if (e.ds_uncorrectable_errors != null) {
                modemDetails.push((T.correlation_tt_errors || 'Errors') + ' ' + e.ds_uncorrectable_errors);
            }
            details = modemDetails.join(' | ');
        } else if (src === 'speedtest') {
            src = '<span class="corr-tone-good">' + escapeHtml(T.correlation_source_speedtest || 'Speedtest') + '</span>';
            msg = (e.download_mbps ? e.download_mbps.toFixed(1) + ' / ' + (e.upload_mbps || 0).toFixed(1) + ' Mbps' : '');
            details = (T.speedtest_ping || 'Ping') + ' ' + (e.ping_ms || '') + ' ms | Jitter ' + (e.jitter_ms || '') + ' ms';
        } else if (src === 'capture') {
            var scStatus = e.status || '';
            var scTone = scStatus === 'completed' ? 'good'
                : scStatus === 'suppressed' ? 'muted'
                : scStatus === 'expired' ? 'crit'
                : 'accent';
            src = '<span class="corr-tone-' + scTone + '">' + escapeHtml(T.correlation_source_capture || 'Capture') + '</span>';
            if (scStatus === 'completed' || scStatus === 'fired') {
                msg = escapeHtml(T.sc_action_capture || 'Speedtest triggered');
                details = e.linked_result_id ? 'Result #' + e.linked_result_id : '';
            } else if (scStatus === 'suppressed') {
                msg = escapeHtml(T.sc_status_suppressed || 'Suppressed');
                details = escapeHtml(e.suppression_reason || '');
            } else {
                msg = escapeHtml(scStatus);
                details = escapeHtml(e.last_error || '');
            }
        } else if (src === 'event') {
            var eventSeverity = CorrelationData.normalizeSeverity(e);
            var sevTone = eventSeverity === 'critical' ? 'crit' : eventSeverity === 'warning' ? 'warn' : 'muted';
            src = '<span class="corr-tone-' + sevTone + '">' + escapeHtml(sevLabels[eventSeverity] || eventSeverity) + '</span>';
            msg = typeof formatEventMessage === 'function' ? formatEventMessage(e) : escapeHtml(e.message || '');
            details = escapeHtml(typeLabels[e.event_type] || e.event_type || '');
        }

        tr.innerHTML = '<td data-label="' + escapeHtml(T.timestamp || 'Timestamp') + '" class="correlation-cell-timestamp">' + ts + '</td>'
            + '<td data-label="' + escapeHtml(T.source || 'Source') + '" class="correlation-cell-source">' + src + '</td>'
            + '<td data-label="' + escapeHtml(T.event_message || 'Message') + '" class="correlation-cell-message">' + msg + '</td>'
            + '<td data-label="' + escapeHtml(T.event_details || 'Details') + '" class="correlation-cell-details">' + details + '</td>';
        tr.addEventListener('mouseenter', function() {
            if (_corrPinnedRow) return;
            var rowTs = this.getAttribute('data-ts');
            var rowSrc = this.getAttribute('data-src');
            _corrHighlightFromTable(rowTs, rowSrc);
        });
        tr.addEventListener('mouseleave', function() {
            if (_corrPinnedRow) return;
            _corrClearChartHighlight();
        });
        tr.addEventListener('click', function() {
            var wasPinned = _corrPinnedRow === this;
            _corrUnpinRow();
            if (wasPinned) return;
            _corrPinnedRow = this;
            this.classList.add('corr-pinned');
            this.setAttribute('aria-selected', 'true');
            var rowTs = this.getAttribute('data-ts');
            var rowSrc = this.getAttribute('data-src');
            _corrHighlightFromTable(rowTs, rowSrc);
        });
        tr.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.click();
            }
        });
        tbody.appendChild(tr);
        count++;
    }
    // Event messages carry arrow icons.
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
