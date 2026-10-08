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

function _corrDrawSpeedMarks(ctx, marks, baselineY, colors, visibleMetrics) {
    if (visibleMetrics.download) {
        for (var di = 0; di < marks.length; di++) {
            var mark = marks[di];
            if (!mark.visible || !mark.hasDownload) continue;
            ctx.beginPath();
            ctx.moveTo(mark.downloadX, baselineY);
            ctx.lineTo(mark.downloadX, mark.downloadY);
            ctx.strokeStyle = colors.download;
            ctx.lineWidth = mark.stemWidth;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(mark.downloadX, mark.downloadY, mark.headRadius, 0, Math.PI * 2);
            ctx.fillStyle = colors.download;
            ctx.fill();
        }
    }
    if (visibleMetrics.upload) {
        for (var ui = 0; ui < marks.length; ui++) {
            var mark = marks[ui];
            if (!mark.visible || !mark.hasUpload) continue;
            ctx.beginPath();
            ctx.moveTo(mark.uploadX, baselineY);
            ctx.lineTo(mark.uploadX, mark.uploadY);
            ctx.strokeStyle = colors.upload;
            ctx.lineWidth = mark.stemWidth;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(mark.uploadX, mark.uploadY, mark.headRadius, 0, Math.PI * 2);
            ctx.fillStyle = colors.upload;
            ctx.fill();
        }
    }
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

/* Lane heights below the main signal band, in display order. */
var CORR_LANES = [
    { key: 'state', height: 10 },
    { key: 'errors', height: 30 },
    { key: 'speed', height: 48 },
    { key: 'segment', height: 34 },
    { key: 'events', height: 14 },
    { key: 'reachability', height: 18 }
];

function renderCorrelationChart(data) {
    _corrCloseEventPopover();
    // Clear pin state when chart is redrawn (legend toggle, zoom, resize)
    if (_corrPinnedRow) _corrUnpinRow();
    var canvas = document.getElementById('correlation-chart');
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    var W = rect.width;
    var hasLoadedReachability = _corrTargetData.some(function(entry) {
        var target = CorrelationData.target(entry);
        return (entry.samples || []).some(function(sample) { return !!CorrelationData.sampleInterval(sample, target); });
    });

    var modem = data.filter(function(d) { return d.source === 'modem'; });
    var speedtest = data.filter(function(d) { return d.source === 'speedtest'; });
    var events = data.filter(function(d) { return d.source === 'event'; });
    var weather = _corrWeatherData || [];
    var segment = _corrSegmentData || [];
    var errorDeltas = CorrelationData.errorDeltas(modem);
    var hasErrorData = errorDeltas.some(function(d) { return d.delta !== null; });
    var errorMax = errorDeltas.reduce(function(max, d) { return d.delta !== null && d.delta > max ? d.delta : max; }, 0);

    // Every source gets its own lane and scale; hidden sources take no space.
    var laneVisible = {
        state: modem.length > 0 && _corrVisible.signalState,
        errors: hasErrorData && _corrVisible.errors,
        speed: speedtest.length > 0 && (_corrVisible.download || _corrVisible.upload),
        segment: segment.length > 0 && (_corrVisible.segmentDs || _corrVisible.segmentUs),
        events: events.length > 0 && _corrVisible.events,
        reachability: hasLoadedReachability && _corrVisible.reachability
    };
    var layout = CorrelationData.laneLayout({
        top: 26, mainHeight: 200, labelHeight: 16, gap: 8, axisGap: 4, axisHeight: 22,
        lanes: CORR_LANES.filter(function(lane) { return laneVisible[lane.key]; })
    });
    var H = layout.height;
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

    if (modem.length === 0 && speedtest.length === 0 && !hasLoadedReachability) {
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
        ctx.font = '13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(T.correlation_no_data, W / 2, H / 2);
        return;
    }

    // Time range (with zoom support)
    var allTs = data.map(function(d) { return docsightParseTime(d.timestamp).getTime(); }).filter(function(ts) { return isFinite(ts); });
    _corrTargetData.forEach(function(entry) {
        var target = CorrelationData.target(entry);
        (entry.samples || []).forEach(function(sample) {
            var interval = CorrelationData.sampleInterval(sample, target);
            if (!interval) return;
            allTs.push(interval.startMs, interval.endMs);
        });
    });
    var hasValidSelectedRange = _corrSelectedRange
        && typeof _corrSelectedRange.startMs === 'number' && isFinite(_corrSelectedRange.startMs)
        && typeof _corrSelectedRange.endMs === 'number' && isFinite(_corrSelectedRange.endMs)
        && _corrSelectedRange.endMs > _corrSelectedRange.startMs;
    if (!hasValidSelectedRange && allTs.length === 0) return;
    var tMinFull = hasValidSelectedRange ? _corrSelectedRange.startMs : Math.min.apply(null, allTs);
    var tMaxFull = hasValidSelectedRange ? _corrSelectedRange.endMs : Math.max.apply(null, allTs);
    if (tMinFull === tMaxFull) { tMaxFull = tMinFull + 3600000; }
    var tMin = _corrZoom ? _corrZoom.tMin : tMinFull;
    var tMax = _corrZoom ? _corrZoom.tMax : tMaxFull;

    // ── Main band: power (dBmV, left), SNR (dB, right), temperature (°C/°F, outer right) ──
    var mainTop = layout.main.y;
    var mainH = layout.main.height;
    function bandY(v, min, max) { return mainTop + mainH - (v - min) / (max - min) * mainH; }

    var dsPowerValues = modem.map(function(d) { return d.ds_power_avg; }).filter(function(v) { return typeof v === 'number' && isFinite(v); });
    var txValues = modem.map(function(d) { return d.us_power_avg; }).filter(function(v) { return typeof v === 'number' && isFinite(v) && v > 0; });
    var showDsPower = _corrVisible.dsPower && dsPowerValues.length > 0;
    var showTxPower = _corrVisible.txPower && txValues.length > 0;
    // DS and US power share one dBmV axis so their levels stay directly comparable.
    var powerValues = (showDsPower ? dsPowerValues : []).concat(showTxPower ? txValues : []);
    if (!powerValues.length) powerValues = dsPowerValues.concat(txValues);
    var powerMin = powerValues.length ? Math.floor(Math.min.apply(null, powerValues) - 2) : -10;
    var powerMax = powerValues.length ? Math.ceil(Math.max.apply(null, powerValues) + 2) : 55;
    function yPower(v) { return bandY(v, powerMin, powerMax); }
    var yTx = yPower;
    var yDsPower = yPower;

    var snrValues = modem.map(function(d) { return d.ds_snr_min || 0; }).filter(function(v) { return v > 0; });
    var showSnr = _corrVisible.snr && snrValues.length > 0;
    var snrMin = snrValues.length ? Math.floor(Math.min.apply(null, snrValues) - 2) : 20;
    var snrMax = snrValues.length ? Math.ceil(Math.max.apply(null, snrValues) + 2) : 45;
    function ySnr(v) { return bandY(v, snrMin, snrMax); }

    var _isFahrenheit = typeof TEMPERATURE_UNIT !== 'undefined' && TEMPERATURE_UNIT === 'fahrenheit';
    function _toDisplayTemp(c) { return _isFahrenheit ? c * 9 / 5 + 32 : c; }
    var tempValues = weather.map(function(d) { return _toDisplayTemp(d.temperature); }).filter(function(v) { return v != null && !isNaN(v); });
    var showTemp = _corrVisible.temperature && tempValues.length > 1;
    var tempMin = tempValues.length ? Math.floor(Math.min.apply(null, tempValues) - 2) : (_isFahrenheit ? 14 : -10);
    var tempMax = tempValues.length ? Math.ceil(Math.max.apply(null, tempValues) + 2) : (_isFahrenheit ? 104 : 40);
    function yTemp(v) { return bandY(_toDisplayTemp(v), tempMin, tempMax); }
    var tempUnit = _isFahrenheit ? '°F' : '°C';

    // Axis widths: dBmV on the left; dB and temperature each get their own right axis.
    ctx.font = '12px system-ui, sans-serif';
    var axisWidth = function(values) {
        return Math.ceil(Math.max.apply(null, values.map(function(v) { return ctx.measureText(String(v)).width; }))) + 10;
    };
    var snrAxisWidth = showSnr ? Math.max(30, axisWidth([snrMin, snrMax])) : 0;
    var tempAxisWidth = showTemp ? Math.max(30, axisWidth([tempMin, tempMax])) : 0;
    var laneAxisWidth = laneVisible.speed ? axisWidth([CorrelationData.niceCeil(1000) + ' Mbps']) : 0;
    var pad = {
        top: mainTop,
        left: Math.max(44, axisWidth([powerMin, powerMax]) + 4),
        right: Math.max(16, snrAxisWidth + tempAxisWidth, laneAxisWidth) + 8,
        bottom: H - mainTop - mainH
    };
    var plotW = W - pad.left - pad.right;
    var plotH = mainH;
    function xScale(ts) { return pad.left + (ts - tMin) / (tMax - tMin) * plotW; }

    // ── Lanes ──
    var lanes = layout.lanes;
    var speedValues = speedtest.map(function(d) { return CorrelationData.measurement(d.download_mbps); })
        .concat(speedtest.map(function(d) { return CorrelationData.measurement(d.upload_mbps); }))
        .filter(function(v) { return v !== null; });
    var dlMin = 0;
    var dlMax = CorrelationData.niceCeil(speedValues.length ? Math.max.apply(null, speedValues) : 500);
    var speedLane = lanes.speed || { y: mainTop, height: mainH };
    function yDl(v) { return speedLane.y + speedLane.height - (v - dlMin) / (dlMax - dlMin) * speedLane.height; }
    var segmentLane = lanes.segment || { y: mainTop, height: mainH };
    function ySegment(v) { return segmentLane.y + segmentLane.height - (v / 100) * segmentLane.height; }
    var errorScaleMax = CorrelationData.niceCeil(errorMax);

    function _cssColor(prop, fallback) {
        var s = getComputedStyle(document.documentElement);
        return s.getPropertyValue(prop).trim() || fallback;
    }
    var segDsColor = _cssColor('--corr-color-seg-ds', '#0ea5e9');
    var segUsColor = _cssColor('--corr-color-seg-us', '#6366f1');
    var downloadColor = _cssColor('--corr-color-download', '#0ea5e9');
    var uploadColor = _cssColor('--corr-color-upload', '#06b6d4');
    var snrColor = _cssColor('--corr-color-snr', '#3b82f6');
    var txColor = _cssColor('--corr-color-tx-power', '#f59e0b');
    var dsPowerColor = _cssColor('--corr-color-ds-power', '#a855f7');
    var errorColor = _cssColor('--corr-color-errors', 'rgba(239,68,68,0.6)');
    var tempColor = _cssColor('--corr-color-temperature', '#f97316');
    var textColor = _cssColor('--muted', '#888');
    var gridColor = _cssColor('--input-border', '#333');
    var goodColor = _cssColor('--good', '#4caf50');
    var toleratedColor = _cssColor('--tolerated', '#84cc16');
    var warnColor = _cssColor('--warn', '#ff9800');
    var critColor = _cssColor('--crit', '#f44336');
    var accentColor = _cssColor('--accent', '#2196f3');
    var laneTint = _cssColor('--tint-emphasis', 'rgba(127,127,127,0.08)');
    var healthColors = { good: goodColor, tolerated: toleratedColor, marginal: warnColor, critical: critColor };
    var reachabilityColors = { ok: goodColor, degraded: warnColor, down: critColor, unknown: textColor };
    var reachabilityBucketCount = Math.min(300, Math.max(1, Math.floor(plotW / 3)));
    var reachabilityBuckets = hasLoadedReachability
        ? CorrelationData.bucketReachability(_corrTargetData, tMin, tMax, reachabilityBucketCount)
        : [];
    var reachabilityLane = lanes.reachability && reachabilityBuckets.length > 0
        ? { y: lanes.reachability.y, height: lanes.reachability.height }
        : null;

    // Store chart state for tooltip lookups
    var sortedSpeedtest = speedtest.slice().sort(function(a, b) {
        return docsightParseTime(a.timestamp).getTime() - docsightParseTime(b.timestamp).getTime();
    });
    var speedMarks = CorrelationData.buildSpeedMarks(sortedSpeedtest, xScale, yDl, tMin, tMax, {
        download: _corrVisible.download,
        upload: _corrVisible.upload
    }, docsightParseTime);
    _corrChartState = {
        pad: pad, plotW: plotW, plotH: plotH, W: W, H: H, layout: layout,
        tMin: tMin, tMax: tMax, tMinFull: tMinFull, tMaxFull: tMaxFull,
        snrMin: snrMin, snrMax: snrMax, txMin: powerMin, txMax: powerMax,
        dsPowerMin: powerMin, dsPowerMax: powerMax, errorMax: errorMax, errorDeltas: errorDeltas,
        tempMin: tempMin, tempMax: tempMax,
        dlMin: dlMin, dlMax: dlMax,
        modem: modem, speedtest: sortedSpeedtest, speedMarks: speedMarks, events: events, data: data,
        weather: weather, segment: segment, reachabilityBuckets: reachabilityBuckets, reachabilityLane: reachabilityLane,
        xScale: xScale, ySnr: ySnr, yTx: yTx, yDsPower: yDsPower, yDl: yDl, yTemp: yTemp, ySegment: ySegment,
        colors: { snr: snrColor, txPower: txColor, dsPower: dsPowerColor, download: downloadColor, upload: uploadColor, event: warnColor, errors: errorColor, temperature: tempColor, segmentDs: segDsColor, segmentUs: segUsColor, reachability: reachabilityColors, health: healthColors, text: textColor, grid: gridColor },
        dpr: dpr
    };

    function axisCaption(text, x, align) {
        ctx.fillStyle = textColor;
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = align;
        ctx.fillText(text, x, mainTop - 10);
    }
    function niceStep(min, max) { return CorrelationData.niceCeil((max - min) / 5); }

    // Power grid and left axis (falls back to the SNR scale when no power is shown).
    ctx.font = '12px system-ui, sans-serif';
    var powerShown = showDsPower || showTxPower;
    var gridMin = powerShown ? powerMin : snrMin;
    var gridMax = powerShown ? powerMax : snrMax;
    var gridStep = niceStep(gridMin, gridMax);
    for (var gv = Math.ceil(gridMin / gridStep) * gridStep; gv <= gridMax; gv += gridStep) {
        var gy = bandY(gv, gridMin, gridMax);
        ctx.strokeStyle = gridColor;
        ctx.lineWidth = 0.5;
        ctx.setLineDash([2, 4]);
        ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(pad.left + plotW, gy); ctx.stroke();
        ctx.setLineDash([]);
        if (powerShown) {
            ctx.fillStyle = textColor;
            ctx.textAlign = 'right';
            ctx.fillText(String(gv), pad.left - 6, gy + 4);
        }
    }
    if (powerShown) axisCaption('dBmV', pad.left - 6, 'right');

    // SNR axis on the right.
    if (showSnr) {
        var snrX = pad.left + plotW + 6;
        var snrStep = niceStep(snrMin, snrMax);
        ctx.fillStyle = snrColor;
        ctx.textAlign = 'left';
        ctx.font = '12px system-ui, sans-serif';
        for (var sv = Math.ceil(snrMin / snrStep) * snrStep; sv <= snrMax; sv += snrStep) {
            ctx.fillText(String(sv), snrX, ySnr(sv) + 4);
        }
        axisCaption('dB', snrX, 'left');
    }
    // Temperature axis to the right of the SNR axis.
    if (showTemp) {
        var tempX = pad.left + plotW + 6 + snrAxisWidth;
        var tempStep = niceStep(tempMin, tempMax);
        ctx.fillStyle = tempColor;
        ctx.textAlign = 'left';
        ctx.font = '12px system-ui, sans-serif';
        for (var tv = Math.ceil(tempMin / tempStep) * tempStep; tv <= tempMax; tv += tempStep) {
            ctx.fillText(String(tv), tempX, bandY(tv, tempMin, tempMax) + 4);
        }
        axisCaption(tempUnit, tempX, 'left');
    }

    // Connect observations directly; smoothed curves imply unmeasured trends.
    function drawSeries(points, color, width, dash) {
        ctx.beginPath();
        var started = false;
        points.forEach(function(point) {
            if (point === null) return;
            if (started) ctx.lineTo(point[0], point[1]);
            else { ctx.moveTo(point[0], point[1]); started = true; }
        });
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.setLineDash(dash);
        ctx.stroke();
        ctx.setLineDash([]);
    }
    function modemX(entry) { return xScale(docsightParseTime(entry.timestamp).getTime()); }
    if (showSnr && modem.length > 1) {
        drawSeries(modem.map(function(d) { return [modemX(d), ySnr(d.ds_snr_min || snrMin)]; }), snrColor, 2, []);
    }
    if (showTxPower && modem.length > 1) {
        drawSeries(modem.map(function(d) { return d.us_power_avg ? [modemX(d), yTx(d.us_power_avg)] : null; }), txColor, 2, [6, 3]);
    }
    if (showDsPower && modem.length > 1) {
        drawSeries(modem.map(function(d) { return d.ds_power_avg != null ? [modemX(d), yDsPower(d.ds_power_avg)] : null; }), dsPowerColor, 1.5, [2, 3]);
    }
    if (showTemp) {
        drawSeries(weather.map(function(d) {
            return d.temperature == null ? null : [xScale(docsightParseTime(d.timestamp).getTime()), yTemp(d.temperature)];
        }), tempColor, 1.5, [5, 3]);
    }

    // Lane labels and backgrounds share one style; each lane draws its own values.
    var laneLabels = {
        state: T.correlation_lane_state || 'Signal state',
        errors: (T.correlation_lane_errors || 'Uncorrectable errors per interval'),
        speed: (T.correlation_lane_speed || 'Speedtests (Mbps) · single measurements'),
        segment: (T.correlation_lane_segment || 'Segment load (%)'),
        events: (T.correlation_lane_events || 'Events · ○ info △ warning ◇ critical'),
        reachability: (T.correlation_lane_reachability || 'Reachability · gaps unknown')
    };
    layout.order.forEach(function(key) {
        var lane = lanes[key];
        ctx.fillStyle = textColor;
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(laneLabels[key], pad.left, lane.labelY + 11);
        ctx.fillStyle = laneTint;
        ctx.fillRect(pad.left, lane.y, plotW, lane.height);
    });
    function laneTick(text, lane, y) {
        ctx.fillStyle = textColor;
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(text, pad.left + plotW + 6, y);
    }

    if (lanes.state) {
        for (var si = 0; si < modem.length; si++) {
            var sx1 = modemX(modem[si]);
            var sx2 = si < modem.length - 1 ? modemX(modem[si + 1]) : Math.min(pad.left + plotW, sx1 + 3);
            if (sx2 < pad.left || sx1 > pad.left + plotW) continue;
            ctx.fillStyle = healthColors[modem[si].health] || laneTint;
            ctx.fillRect(Math.max(pad.left, sx1), lanes.state.y, Math.max(1, Math.min(pad.left + plotW, sx2) - Math.max(pad.left, sx1)), lanes.state.height);
        }
    }

    if (lanes.errors) {
        var errorLane = lanes.errors;
        for (var ei = 0; ei < errorDeltas.length; ei++) {
            var delta = errorDeltas[ei].delta;
            if (!delta) continue;
            var ex = modemX(modem[ei]);
            if (ex < pad.left || ex > pad.left + plotW) continue;
            var eh = Math.max(2, delta / errorScaleMax * errorLane.height);
            ctx.fillStyle = errorColor;
            ctx.fillRect(ex - 1.5, errorLane.y + errorLane.height - eh, 3, eh);
        }
        laneTick(String(errorScaleMax), errorLane, errorLane.y + 9);
        laneTick('0', errorLane, errorLane.y + errorLane.height);
    }

    // Speedtests are point-in-time measurements: stems and heads, never a line.
    if (lanes.speed) {
        _corrDrawSpeedMarks(ctx, speedMarks, yDl(0), {
            download: downloadColor,
            upload: uploadColor
        }, {
            download: _corrVisible.download,
            upload: _corrVisible.upload
        });
        laneTick(dlMax + ' Mbps', lanes.speed, lanes.speed.y + 9);
        laneTick('0', lanes.speed, lanes.speed.y + lanes.speed.height);
    }

    if (lanes.segment) {
        if (_corrVisible.segmentDs) {
            drawSeries(segment.map(function(d) {
                return d.ds_total == null ? null : [xScale(docsightParseTime(d.timestamp).getTime()), ySegment(d.ds_total)];
            }), segDsColor, 1.5, []);
        }
        if (_corrVisible.segmentUs) {
            drawSeries(segment.map(function(d) {
                return d.us_total == null ? null : [xScale(docsightParseTime(d.timestamp).getTime()), ySegment(d.us_total)];
            }), segUsColor, 1.5, []);
        }
        laneTick('100 %', lanes.segment, lanes.segment.y + 9);
        laneTick('0', lanes.segment, lanes.segment.y + lanes.segment.height);
    }

    // Events: shape carries the severity (circle info, triangle warning, diamond critical).
    var filteredEvents = _corrFilteredEvents(events);
    if (lanes.events) {
        var eventMid = lanes.events.y + lanes.events.height / 2;
        for (var vi = 0; vi < filteredEvents.length; vi++) {
            var vx = xScale(docsightParseTime(filteredEvents[vi].timestamp).getTime());
            if (vx < pad.left || vx > pad.left + plotW) continue;
            var sev = CorrelationData.normalizeSeverity(filteredEvents[vi]);
            ctx.strokeStyle = sev === 'critical' ? critColor : sev === 'warning' ? warnColor : textColor;
            ctx.fillStyle = ctx.strokeStyle;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            if (sev === 'critical') {
                ctx.moveTo(vx, eventMid - 6); ctx.lineTo(vx + 6, eventMid); ctx.lineTo(vx, eventMid + 6); ctx.lineTo(vx - 6, eventMid); ctx.closePath();
                ctx.fill();
            } else if (sev === 'warning') {
                ctx.moveTo(vx, eventMid - 6); ctx.lineTo(vx + 6, eventMid + 5); ctx.lineTo(vx - 6, eventMid + 5); ctx.closePath();
                ctx.stroke();
            } else {
                ctx.arc(vx, eventMid, 4, 0, Math.PI * 2);
                ctx.stroke();
            }
        }
    }

    if (reachabilityLane) {
        ctx.save();
        for (var rb = 0; rb < reachabilityBuckets.length; rb++) {
            var reachBucket = reachabilityBuckets[rb];
            var reachX1 = Math.max(pad.left, xScale(reachBucket.startMs));
            var reachX2 = Math.min(pad.left + plotW, xScale(reachBucket.endMs));
            if (reachX2 <= reachX1) continue;
            ctx.globalAlpha = reachBucket.state === 'unknown' ? 0.35 : 0.82;
            ctx.fillStyle = reachabilityColors[reachBucket.state];
            ctx.fillRect(reachX1, reachabilityLane.y, Math.max(1, reachX2 - reachX1), reachabilityLane.height);
            ctx.globalAlpha = 0.7;
            ctx.strokeStyle = gridColor;
            ctx.lineWidth = 0.5;
            ctx.strokeRect(reachX1, reachabilityLane.y, Math.max(1, reachX2 - reachX1), reachabilityLane.height);
            if (reachX2 - reachX1 >= 18) {
                ctx.globalAlpha = 0.95;
                ctx.fillStyle = reachBucket.state === 'unknown' ? textColor : '#fff';
                ctx.font = 'bold 12px system-ui, sans-serif';
                ctx.textAlign = 'center';
                var stateMark = reachBucket.state === 'ok' ? '✓' : reachBucket.state === 'degraded' ? '!' : reachBucket.state === 'down' ? '×' : '?';
                ctx.fillText(stateMark, (reachX1 + reachX2) / 2, reachabilityLane.y + 13);
            }
        }
        ctx.restore();
    }

    // Shared time axis below the last lane.
    ctx.fillStyle = textColor;
    ctx.font = '12px system-ui, sans-serif';
    ctx.textAlign = 'center';
    var labelCount = Math.min(8, Math.floor(plotW / 80));
    var range = getPillValue('correlation-tabs') || '1d';
    for (var li = 0; li <= labelCount; li++) {
        var t = tMin + (tMax - tMin) * li / labelCount;
        ctx.fillText(docsightFormatXAxisLabel(t, range), xScale(t), layout.axisY + 14);
    }

    // Interactive Legend
    var legend = document.getElementById('correlation-legend');
    var legendItems = [];
    if (modem.length > 0) {
        if (dsPowerValues.length > 0) {
            legendItems.push({ metric: 'dsPower', color: dsPowerColor, label: '&#183;&#183; ' + (T.chart_ds_power || 'DS Power (dBmV)') });
        }
        if (txValues.length > 0) {
            legendItems.push({ metric: 'txPower', color: txColor, label: '&#9476; ' + (T.chart_us_power || 'US Power (dBmV)') });
        }
        legendItems.push({ metric: 'snr', color: snrColor, label: '&#9644; ' + (T.chart_snr || 'SNR (dB)') });
        legendItems.push({ metric: 'signalState', color: goodColor, label: '&#9646; ' + (T.correlation_lane_state || 'Signal state') });
        if (hasErrorData) {
            legendItems.push({ metric: 'errors', color: 'rgba(239,68,68,0.8)', label: '&#9612; ' + (T.correlation_errors || 'Errors') });
        }
    }
    if (speedtest.length > 0) {
        legendItems.push({ metric: 'download', color: downloadColor, label: '&#9474;&#9679; ' + (T.correlation_download || 'Download (Mbps)') });
        legendItems.push({ metric: 'upload', color: uploadColor, label: '&#9474;&#9679; ' + (T.correlation_upload || 'Upload (Mbps)') });
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
        legendItems.push({ metric: 'events', color: warnColor, label: '&#9650; ' + (T.correlation_events || 'Events'), eventTypes: eventTypes, eventSeverityCounts: eventSeverityCounts, visibleEventCount: visibleEventCount, totalEventCount: events.length });
    }
    if (weather.length > 0) {
        legendItems.push({ metric: 'temperature', color: tempColor, label: '- - ' + (T.temperature || 'Temperature') + ' (' + (typeof TEMPERATURE_UNIT !== 'undefined' && TEMPERATURE_UNIT === 'fahrenheit' ? '°F' : '°C') + ')' });
    }
    if (segment.length > 0) {
        legendItems.push({ metric: 'segmentDs', color: segDsColor, label: '&#9644; ' + (T.seg_correlation_ds || 'Segment DS (%)') });
        legendItems.push({ metric: 'segmentUs', color: segUsColor, label: '&#9644; ' + (T.seg_correlation_us || 'Segment US (%)') });
    }
    if (reachabilityBuckets.length > 0) {
        legendItems.push({ metric: 'reachability', color: accentColor, label: '&#9646; ' + (T.correlation_reachability || 'Reachability') });
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
                    '<input type="checkbox" data-event-type="' + _corrEscapeAttr(et) + '"' + checked + ' data-color="' + _corrEscapeAttr(warnColor) + '"> ' +
                    '<span class="corr-event-filter-name">' + escapeHtml(label) + '</span> <span class="corr-event-filter-count">(' + eventTypes[et] + ')</span></label>' +
                    '<div class="corr-event-filter-severities">';
                for (var sj = 0; sj < CorrelationData.SEVERITIES.length; sj++) {
                    var sv = CorrelationData.SEVERITIES[sj];
                    var svChecked = severityFilter[sv] !== false ? ' checked' : '';
                    var svCount = (eventSeverityCounts[et] && eventSeverityCounts[et][sv]) || 0;
                    html += '<label class="corr-event-filter-severity">' +
                        '<input type="checkbox" data-event-type="' + _corrEscapeAttr(et) + '" data-event-severity="' + _corrEscapeAttr(sv) + '"' + svChecked + ' data-color="' + _corrEscapeAttr(warnColor) + '"> ' +
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
        var nearestModem = null;
        if (st.modem.length > 0 && anyModemVisible) {
            var bestDist = Infinity;
            for (var i = 0; i < st.modem.length; i++) {
                var ts = docsightParseTime(st.modem[i].timestamp).getTime();
                var dist = Math.abs(ts - tHover);
                if (dist < bestDist) { bestDist = dist; nearestModem = st.modem[i]; }
            }
        }

        // Find nearest speedtest point
        var nearestSpeed = null;
        var nearestSpeedMark = null;
        if (st.speedtest.length > 0 && (_corrVisible.download || _corrVisible.upload)) {
            var bestDist = Infinity;
            for (var i = 0; i < st.speedtest.length; i++) {
                if (!st.speedMarks[i] || !st.speedMarks[i].visible) continue;
                var ts = docsightParseTime(st.speedtest[i].timestamp).getTime();
                var dist = Math.abs(ts - tHover);
                if (dist < bestDist) {
                    bestDist = dist;
                    nearestSpeed = st.speedtest[i];
                    nearestSpeedMark = st.speedMarks[i];
                }
            }
        }

        // Find nearest event (respecting type filter)
        var nearestEvent = null;
        var visibleEvents = _corrFilteredEvents(st.events);
        if (visibleEvents.length > 0) {
            var bestDist = Infinity;
            for (var i = 0; i < visibleEvents.length; i++) {
                var ts = docsightParseTime(visibleEvents[i].timestamp).getTime();
                var dist = Math.abs(ts - tHover);
                if (dist < bestDist) { bestDist = dist; nearestEvent = visibleEvents[i]; }
            }
        }

        // Find nearest weather point
        var nearestWeather = null;
        if (st.weather && st.weather.length > 0 && _corrVisible.temperature) {
            var bestDist = Infinity;
            for (var i = 0; i < st.weather.length; i++) {
                var ts = docsightParseTime(st.weather[i].timestamp).getTime();
                var dist = Math.abs(ts - tHover);
                if (dist < bestDist) { bestDist = dist; nearestWeather = st.weather[i]; }
            }
        }

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
        if (nearestModem && _corrVisible.snr) {
            var dx = st.xScale(docsightParseTime(nearestModem.timestamp).getTime());
            var dy = st.ySnr(nearestModem.ds_snr_min || st.snrMin);
            newOctx.beginPath();
            newOctx.arc(dx, dy, 5, 0, Math.PI * 2);
            newOctx.fillStyle = st.colors.snr;
            newOctx.fill();
            newOctx.strokeStyle = '#fff';
            newOctx.lineWidth = 2;
            newOctx.stroke();
        }
        if (nearestModem && _corrVisible.txPower && nearestModem.us_power_avg) {
            var dx = st.xScale(docsightParseTime(nearestModem.timestamp).getTime());
            var dy = st.yTx(nearestModem.us_power_avg);
            newOctx.beginPath();
            newOctx.arc(dx, dy, 5, 0, Math.PI * 2);
            newOctx.fillStyle = st.colors.txPower;
            newOctx.fill();
            newOctx.strokeStyle = '#fff';
            newOctx.lineWidth = 2;
            newOctx.stroke();
        }
        if (nearestModem && _corrVisible.dsPower && nearestModem.ds_power_avg != null) {
            var dx = st.xScale(docsightParseTime(nearestModem.timestamp).getTime());
            var dy = st.yDsPower(nearestModem.ds_power_avg);
            newOctx.beginPath();
            newOctx.arc(dx, dy, 5, 0, Math.PI * 2);
            newOctx.fillStyle = st.colors.dsPower;
            newOctx.fill();
            newOctx.strokeStyle = '#fff';
            newOctx.lineWidth = 2;
            newOctx.stroke();
        }
        if (nearestSpeed && nearestSpeedMark) {
            if (_corrVisible.download && nearestSpeedMark.hasDownload) {
                var dx = nearestSpeedMark.downloadX;
                var dy = nearestSpeedMark.downloadY;
                newOctx.beginPath();
                newOctx.arc(dx, dy, 5, 0, Math.PI * 2);
                newOctx.fillStyle = st.colors.download;
                newOctx.fill();
                newOctx.strokeStyle = '#fff';
                newOctx.lineWidth = 2;
                newOctx.stroke();
            }
            if (_corrVisible.upload && nearestSpeedMark.hasUpload) {
                var dx = nearestSpeedMark.uploadX;
                var dy = nearestSpeedMark.uploadY;
                newOctx.beginPath();
                newOctx.arc(dx, dy, 5, 0, Math.PI * 2);
                newOctx.fillStyle = st.colors.upload;
                newOctx.fill();
                newOctx.strokeStyle = '#fff';
                newOctx.lineWidth = 2;
                newOctx.stroke();
            }
        }

        // Draw temperature highlight dot
        if (nearestWeather && _corrVisible.temperature && nearestWeather.temperature != null) {
            var dx = st.xScale(docsightParseTime(nearestWeather.timestamp).getTime());
            var dy = st.yTemp(nearestWeather.temperature);
            newOctx.beginPath();
            newOctx.arc(dx, dy, 5, 0, Math.PI * 2);
            newOctx.fillStyle = st.colors.temperature;
            newOctx.fill();
            newOctx.strokeStyle = '#fff';
            newOctx.lineWidth = 2;
            newOctx.stroke();
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
        if (st.segment && st.segment.length > 0) {
            var nearestSeg = null, segDist = Infinity;
            for (var si = 0; si < st.segment.length; si++) {
                var sd = Math.abs(docsightParseTime(st.segment[si].timestamp).getTime() - tHover);
                if (sd < segDist) { segDist = sd; nearestSeg = st.segment[si]; }
            }
            if (nearestSeg && segDist < (st.tMax - st.tMin) * 0.05) {
                if (_corrVisible.segmentDs && nearestSeg.ds_total != null) {
                    html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.segmentDs) + '"></span> ' + (T.seg_correlation_ds || 'Segment DS') + ': ' + nearestSeg.ds_total.toFixed(1) + '%</div>';
                }
                if (_corrVisible.segmentUs && nearestSeg.us_total != null) {
                    html += '<div class="tt-row"><span class="tt-dot" data-color="' + _corrEscapeAttr(st.colors.segmentUs) + '"></span> ' + (T.seg_correlation_us || 'Segment US') + ': ' + nearestSeg.us_total.toFixed(1) + '%</div>';
                }
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
                if (_corrVisible.snr) {
                    var dy = st.ySnr(st.modem[i].ds_snr_min || st.snrMin);
                    octx.beginPath();
                    octx.arc(x, dy, 6, 0, Math.PI * 2);
                    octx.fillStyle = st.colors.snr;
                    octx.fill();
                    octx.strokeStyle = '#fff';
                    octx.lineWidth = 2;
                    octx.stroke();
                }
                if (_corrVisible.txPower && st.modem[i].us_power_avg) {
                    var dy = st.yTx(st.modem[i].us_power_avg);
                    octx.beginPath();
                    octx.arc(x, dy, 6, 0, Math.PI * 2);
                    octx.fillStyle = st.colors.txPower;
                    octx.fill();
                    octx.strokeStyle = '#fff';
                    octx.lineWidth = 2;
                    octx.stroke();
                }
                break;
            }
        }
    } else if (source === 'speedtest') {
        for (var i = 0; i < st.speedtest.length; i++) {
            if (st.speedtest[i].timestamp === timestamp) {
                var speedMark = st.speedMarks[i];
                if (_corrVisible.download && speedMark.hasDownload) {
                    octx.beginPath();
                    octx.arc(speedMark.downloadX, speedMark.downloadY, 6, 0, Math.PI * 2);
                    octx.fillStyle = st.colors.download;
                    octx.fill();
                    octx.strokeStyle = '#fff';
                    octx.lineWidth = 2;
                    octx.stroke();
                }
                if (_corrVisible.upload && speedMark.hasUpload) {
                    octx.beginPath();
                    octx.arc(speedMark.uploadX, speedMark.uploadY, 6, 0, Math.PI * 2);
                    octx.fillStyle = st.colors.upload;
                    octx.fill();
                    octx.strokeStyle = '#fff';
                    octx.lineWidth = 2;
                    octx.stroke();
                }
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
