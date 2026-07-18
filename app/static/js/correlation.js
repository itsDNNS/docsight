/* ═══ DOCSight Correlation Analysis Module ═══ */

/* ═══ Correlation Analysis ═══ */
var _correlationData = [];
var _correlationChart = null;
var _corrVisible = { snr: true, txPower: true, dsPower: true, download: true, upload: true, events: false, errors: true, poorSignal: false, temperature: true, segmentDs: true, segmentUs: false, reachability: true };
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
var _CORR_SEVERITIES = ['info', 'warning', 'critical'];
function _corrRangeHours(range) {
    var raw = String(range || '1d');
    if (/^\d+$/.test(raw)) return parseInt(raw, 10);
    var match = raw.match(/^(\d+)(h|d)$/);
    if (!match) return 24;
    var value = parseInt(match[1], 10);
    return match[2] === 'h' ? value : value * 24;
}
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
function _corrNormalizeSeverity(e) {
    var severity = String((e && e.severity) || 'info').toLowerCase();
    return _CORR_SEVERITIES.indexOf(severity) !== -1 ? severity : 'info';
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
    var severity = _corrNormalizeSeverity(e);
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

function _corrMeasurement(value) {
    return typeof value === 'number' && isFinite(value) && value >= 0 ? value : null;
}

function _corrFormatTimestamp(timestamp) {
    var date = new Date(timestamp);
    if (isNaN(date.getTime())) return String(timestamp || '');
    return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0') +
        ' ' + String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0') + ':' + String(date.getSeconds()).padStart(2, '0');
}

function _corrTarget(entry) {
    return entry && entry.target ? entry.target : (entry || {});
}

function _corrSampleInterval(sample, target) {
    if (!sample || typeof sample.timestamp !== 'number' || !isFinite(sample.timestamp)) return null;
    var coverageSeconds = typeof sample.bucket_seconds === 'number' && isFinite(sample.bucket_seconds) && sample.bucket_seconds > 0
        ? sample.bucket_seconds
        : Number(target && target.poll_interval_ms) / 1000;
    if (!isFinite(coverageSeconds) || coverageSeconds <= 0) return null;
    var startMs = sample.timestamp * 1000;
    return { startMs: startMs, endMs: startMs + coverageSeconds * 1000 };
}

function _corrSetOverlayActionable(overlay, actionable) {
    if (!overlay) return;
    overlay.setAttribute('role', actionable ? 'button' : 'img');
    if (actionable) overlay.setAttribute('tabindex', '0');
    else overlay.removeAttribute('tabindex');
}

/**
 * Re-bucket loaded Connection Monitor samples into time-proportional display buckets.
 * CM timestamps are epoch seconds; this helper normalizes them to milliseconds.
 */
function _corrBucketReachability(targetData, tMinMs, tMaxMs, bucketCount) {
    var requestedCount = Math.floor(Number(bucketCount));
    var count = Math.min(300, Math.max(1, isFinite(requestedCount) ? requestedCount : 1));
    if (!isFinite(tMinMs) || !isFinite(tMaxMs) || tMaxMs <= tMinMs) return [];
    var widthMs = (tMaxMs - tMinMs) / count;
    var buckets = [];
    for (var bi = 0; bi < count; bi++) {
        var bucketStart = tMinMs + bi * widthMs;
        var bucketEnd = bi === count - 1 ? tMaxMs : tMinMs + (bi + 1) * widthMs;
        var sampleCount = 0;
        var weightedLoss = 0;
        var allDown = true;
        var targetKeys = {};
        var targetLabels = [];

        (targetData || []).forEach(function(entry, targetIndex) {
            var target = _corrTarget(entry);
            var key = target.id != null ? 'id:' + target.id : 'index:' + targetIndex;
            var label = target.label || target.host || String(target.id != null ? target.id : targetIndex + 1);
            var targetObserved = false;
            (entry.samples || []).forEach(function(sample) {
                var interval = _corrSampleInterval(sample, target);
                if (!interval || interval.startMs >= bucketEnd || interval.endMs <= bucketStart) return;
                var loss = Number(sample.packet_loss_pct);
                if (!isFinite(loss) || loss < 0 || loss > 100) return;
                var weight = Number(sample.sample_count);
                if (!isFinite(weight) || weight <= 0) weight = 1;
                sampleCount += weight;
                weightedLoss += loss * weight;
                if (loss !== 100) allDown = false;
                targetObserved = true;
            });
            if (targetObserved && !targetKeys[key]) {
                targetKeys[key] = true;
                targetLabels.push(label);
            }
        });

        var lossPct = sampleCount > 0 ? weightedLoss / sampleCount : null;
        var state = 'unknown';
        if (sampleCount > 0) {
            if (allDown && lossPct === 100) state = 'down';
            else if (lossPct === 0) state = 'ok';
            else state = 'degraded';
        }
        buckets.push({
            startMs: bucketStart,
            endMs: bucketEnd,
            state: state,
            lossPct: lossPct,
            sampleCount: sampleCount,
            targetsObserved: targetLabels.length,
            targetScope: targetLabels.join(' | ')
        });
    }
    return buckets;
}

function _corrFetchReachability(startEpoch, endEpoch, maxPoints) {
    if (typeof CORRELATION_CM_AVAILABLE === 'undefined' || !CORRELATION_CM_AVAILABLE) {
        _corrCmState = 'module_absent';
        _corrTargetData = [];
        return Promise.resolve(null);
    }
    var boundedPoints = Math.min(1000, Math.max(1, Number(maxPoints) || 300));
    return fetch('/api/connection-monitor/targets')
        .then(function(response) {
            if (!response.ok) throw new Error('Connection Monitor targets unavailable');
            return response.json();
        })
        .catch(function() { return null; })
        .then(function(targets) {
            if (!targets) {
                _corrCmState = 'fetch_error';
                _corrTargetData = [];
                return null;
            }
            var enabled = targets.filter(function(target) { return !!target.enabled; });
            if (enabled.length === 0) {
                _corrCmState = 'targets_absent';
                _corrTargetData = [];
                return [];
            }
            var requests = enabled.map(function(target) {
                var url = '/api/connection-monitor/samples/' + target.id
                    + '?start=' + encodeURIComponent(startEpoch)
                    + '&end=' + encodeURIComponent(endEpoch)
                    + '&resolution=auto&max_points=' + encodeURIComponent(boundedPoints)
                    + '&limit=0';
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
                if (results.some(function(result) { return result === null; })) {
                    _corrCmState = 'fetch_error';
                    _corrTargetData = [];
                    return null;
                }
                _corrTargetData = results;
                var allSamples = results.reduce(function(total, entry) { return total + entry.samples.length; }, 0);
                if (allSamples === 0) {
                    _corrCmState = 'no_samples';
                    return results;
                }
                var startMs = startEpoch * 1000;
                var endMs = endEpoch * 1000;
                var intersects = results.some(function(entry) {
                    return entry.samples.some(function(sample) {
                        var interval = _corrSampleInterval(sample, entry.target);
                        return interval && interval.startMs < endMs && interval.endMs > startMs;
                    });
                });
                _corrCmState = intersects ? 'ready' : 'samples_outside_range';
                if (!intersects) _corrTargetData = [];
                return results;
            });
        });
}

function _corrBuildSpeedMarks(speedtests, xScale, yScale, tMin, tMax, visibleMetrics) {
    var visiblePoints = [];
    for (var i = 0; i < speedtests.length; i++) {
        var timestampMs = new Date(speedtests[i].timestamp).getTime();
        if (isFinite(timestampMs) && timestampMs >= tMin && timestampMs <= tMax) {
            visiblePoints.push({ index: i, x: xScale(timestampMs) });
        }
    }

    var nearestVisibleDistances = [];
    for (var vi = 0; vi < visiblePoints.length; vi++) {
        var previousDistance = vi > 0 ? Math.abs(visiblePoints[vi].x - visiblePoints[vi - 1].x) : Infinity;
        var nextDistance = vi < visiblePoints.length - 1 ? Math.abs(visiblePoints[vi + 1].x - visiblePoints[vi].x) : Infinity;
        nearestVisibleDistances[visiblePoints[vi].index] = Math.min(previousDistance, nextDistance);
    }

    var singleVisibleSample = visiblePoints.length === 1;
    return speedtests.map(function(sample, index) {
        var timestampMs = new Date(sample.timestamp).getTime();
        var timestampX = xScale(timestampMs);
        var visible = isFinite(timestampMs) && timestampMs >= tMin && timestampMs <= tMax;
        var nearestVisibleDistance = visible ? nearestVisibleDistances[index] : Infinity;

        var download = _corrMeasurement(sample.download_mbps);
        var upload = _corrMeasurement(sample.upload_mbps);
        var canSeparatePair = visibleMetrics.download && visibleMetrics.upload && download !== null && upload !== null && nearestVisibleDistance >= 8;
        var offset = canSeparatePair ? Math.min(2, nearestVisibleDistance / 4) : 0;
        return {
            timestamp: sample.timestamp,
            timestampMs: timestampMs,
            timestampX: timestampX,
            visible: visible,
            nearestVisibleDistance: nearestVisibleDistance,
            offset: offset,
            stemWidth: nearestVisibleDistance < 8 ? 1 : 1.5,
            headRadius: singleVisibleSample ? 4.5 : 3.5,
            hasDownload: download !== null,
            hasUpload: upload !== null,
            downloadX: timestampX - offset,
            uploadX: timestampX + offset,
            downloadY: download !== null ? yScale(download) : null,
            uploadY: upload !== null ? yScale(upload) : null
        };
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

// Re-render chart on container resize
(function() {
    var resizeTimer;
    var observer = new ResizeObserver(function() {
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

function loadCorrelationData() {
    var hours = _corrRangeHours(getPillValue('correlation-tabs'));

    var loading = document.getElementById('correlation-loading');
    var noData = document.getElementById('correlation-no-data');
    var chartContainer = document.getElementById('correlation-chart-container');
    var tableCard = document.getElementById('correlation-table-card');
    var overlay = document.getElementById('correlation-overlay');
    _corrSetOverlayActionable(overlay, false);
    if (overlay) overlay.setAttribute('aria-label', T.correlation_chart_aria_label || 'Signal correlation chart');
    loading.style.display = 'flex';
    noData.style.display = 'none';
    chartContainer.style.display = 'none';
    tableCard.style.display = 'none';

    /* Calculate time range for weather fetch */
    var now = new Date();
    var wEnd = now.toISOString().substring(0, 19) + 'Z';
    var wStart = new Date(now.getTime() - parseInt(hours) * 3600000).toISOString().substring(0, 19) + 'Z';
    var startEpoch = Math.floor(new Date(wStart).getTime() / 1000);
    var endEpoch = Math.ceil(new Date(wEnd).getTime() / 1000);
    _corrSelectedRange = { startMs: startEpoch * 1000, endMs: endEpoch * 1000 };
    var weatherUrl = '/api/weather/range?start=' + encodeURIComponent(wStart) + '&end=' + encodeURIComponent(wEnd);

    var segmentUrl = '/api/fritzbox/segment-utilization/range?start=' + encodeURIComponent(wStart) + '&end=' + encodeURIComponent(wEnd);

    Promise.all([
        fetch('/api/correlation?hours=' + hours + '&sources=modem,speedtest,events,capture').then(function(r) { return r.json(); }),
        fetch(weatherUrl).then(function(r) { return r.json(); }).catch(function() { return []; }),
        fetch(segmentUrl).then(function(r) { return r.json(); }).catch(function() { return []; }),
        _corrFetchReachability(startEpoch, endEpoch, 300).catch(function() {
            _corrCmState = 'fetch_error';
            _corrTargetData = [];
            return null;
        })
    ]).then(function(results) {
            var data = Array.isArray(results[0]) ? results[0] : [];
            _corrWeatherData = results[1] || [];
            _corrSegmentData = results[2] || [];
            loading.style.display = 'none';
            _correlationData = data;
            var hasReachability = _corrTargetData.some(function(entry) { return entry.samples && entry.samples.length > 0; });
            if (data.length === 0 && !hasReachability) {
                noData.textContent = T.correlation_no_data;
                noData.style.display = 'block';
                return;
            }
            chartContainer.style.display = 'block';
            tableCard.style.display = data.length > 0 ? 'block' : 'none';
            renderCorrelationChart(data);
            if (data.length > 0) renderCorrelationTable(data);
        })
        .catch(function() {
            loading.style.display = 'none';
            noData.textContent = T.correlation_no_data;
            noData.style.display = 'block';
        });
}

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
        var target = _corrTarget(entry);
        return (entry.samples || []).some(function(sample) { return !!_corrSampleInterval(sample, target); });
    });
    var reachabilityLaneHeight = hasLoadedReachability ? 26 : 0;
    var H = 280 + reachabilityLaneHeight;
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

    var pad = { top: 20, right: 60, bottom: 40 + reachabilityLaneHeight, left: 60 };
    var plotW = W - pad.left - pad.right;
    var plotH = H - pad.top - pad.bottom;

    var modem = data.filter(function(d) { return d.source === 'modem'; });
    var speedtest = data.filter(function(d) { return d.source === 'speedtest'; });
    var events = data.filter(function(d) { return d.source === 'event'; });

    if (modem.length === 0 && speedtest.length === 0 && !hasLoadedReachability) {
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
        ctx.font = '13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(T.correlation_no_data, W / 2, H / 2);
        return;
    }

    // Time range (with zoom support)
    var allTs = data.map(function(d) { return new Date(d.timestamp).getTime(); }).filter(function(ts) { return isFinite(ts); });
    _corrTargetData.forEach(function(entry) {
        var target = _corrTarget(entry);
        (entry.samples || []).forEach(function(sample) {
            var interval = _corrSampleInterval(sample, target);
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

    function xScale(ts) { return pad.left + (ts - tMin) / (tMax - tMin) * plotW; }

    // SNR axis (left, for modem SNR)
    var snrValues = modem.map(function(d) { return d.ds_snr_min || 0; }).filter(function(v) { return v > 0; });
    var snrMin = snrValues.length ? Math.floor(Math.min.apply(null, snrValues) - 2) : 20;
    var snrMax = snrValues.length ? Math.ceil(Math.max.apply(null, snrValues) + 2) : 45;
    function ySnr(v) { return pad.top + plotH - (v - snrMin) / (snrMax - snrMin) * plotH; }

    // Speed axis (right, for speedtest download/upload)
    var dlValues = speedtest.map(function(d) { return _corrMeasurement(d.download_mbps); }).filter(function(v) { return v !== null; });
    var ulValues = speedtest.map(function(d) { return _corrMeasurement(d.upload_mbps); }).filter(function(v) { return v !== null; });
    var speedValues = dlValues.concat(ulValues);
    var speedMax = speedValues.length ? Math.max(1, Math.ceil(Math.max.apply(null, speedValues) * 1.1)) : 500;
    var dlMax = speedMax;
    var dlMin = 0;
    function yDl(v) { return pad.top + plotH - (v - dlMin) / (dlMax - dlMin) * plotH; }
    // TX Power axis (shares left side, separate scale)
    var txValues = modem.map(function(d) { return d.us_power_avg || 0; }).filter(function(v) { return v > 0; });
    var txMin = txValues.length ? Math.floor(Math.min.apply(null, txValues) - 2) : 30;
    var txMax = txValues.length ? Math.ceil(Math.max.apply(null, txValues) + 2) : 55;
    function yTx(v) { return pad.top + plotH - (v - txMin) / (txMax - txMin) * plotH; }

    // DS Power axis (separate scale)
    var dsPowerValues = modem.map(function(d) { return d.ds_power_avg || 0; }).filter(function(v) { return v !== 0; });
    var dsPowerMin = dsPowerValues.length ? Math.floor(Math.min.apply(null, dsPowerValues) - 2) : -10;
    var dsPowerMax = dsPowerValues.length ? Math.ceil(Math.max.apply(null, dsPowerValues) + 2) : 15;
    function yDsPower(v) { return pad.top + plotH - (v - dsPowerMin) / (dsPowerMax - dsPowerMin) * plotH; }

    // Uncorrectable errors (spike height relative to plotH)
    var errorValues = modem.map(function(d) { return d.ds_uncorrectable_errors || 0; });
    var errorMax = errorValues.length ? Math.max.apply(null, errorValues) : 0;

    // Temperature axis (separate scale, dashed line)
    var weather = _corrWeatherData || [];
    var _isFahrenheit = typeof TEMPERATURE_UNIT !== 'undefined' && TEMPERATURE_UNIT === 'fahrenheit';
    function _toDisplayTemp(c) { return _isFahrenheit ? c * 9 / 5 + 32 : c; }
    var tempValues = weather.map(function(d) { return _toDisplayTemp(d.temperature); }).filter(function(v) { return v != null && !isNaN(v); });
    var tempMin = tempValues.length ? Math.floor(Math.min.apply(null, tempValues) - 2) : (_isFahrenheit ? 14 : -10);
    var tempMax = tempValues.length ? Math.ceil(Math.max.apply(null, tempValues) + 2) : (_isFahrenheit ? 104 : 40);
    function yTemp(v) { var dv = _toDisplayTemp(v); return pad.top + plotH - (dv - tempMin) / (tempMax - tempMin) * plotH; }

    // Segment utilization axis (0-100% scale)
    var segment = _corrSegmentData || [];
    function _cssColor(prop, fallback) {
        var s = getComputedStyle(document.documentElement);
        return s.getPropertyValue(prop).trim() || fallback;
    }

    var segDsColor = _cssColor('--corr-color-seg-ds', '#0ea5e9');
    var segUsColor = _cssColor('--corr-color-seg-us', '#6366f1');
    function ySegment(v) { return pad.top + plotH - (v / 100) * plotH; }

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
    var warnColor = _cssColor('--warn', '#ff9800');
    var critColor = _cssColor('--crit', '#f44336');
    var accentColor = _cssColor('--accent', '#2196f3');
    var reachabilityColors = { ok: goodColor, degraded: warnColor, down: critColor, unknown: textColor };
    var reachabilityBucketCount = Math.min(300, Math.max(1, Math.floor(plotW / 3)));
    var reachabilityBuckets = hasLoadedReachability
        ? _corrBucketReachability(_corrTargetData, tMin, tMax, reachabilityBucketCount)
        : [];
    var reachabilityLane = reachabilityBuckets.length > 0 ? { y: H - 22, height: 18 } : null;

    // Store chart state for tooltip lookups
    var sortedSpeedtest = speedtest.slice().sort(function(a, b) {
        return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
    });
    var speedMarks = _corrBuildSpeedMarks(sortedSpeedtest, xScale, yDl, tMin, tMax, {
        download: _corrVisible.download,
        upload: _corrVisible.upload
    });
    _corrChartState = {
        pad: pad, plotW: plotW, plotH: plotH, W: W, H: H,
        tMin: tMin, tMax: tMax, tMinFull: tMinFull, tMaxFull: tMaxFull,
        snrMin: snrMin, snrMax: snrMax, txMin: txMin, txMax: txMax,
        dsPowerMin: dsPowerMin, dsPowerMax: dsPowerMax, errorMax: errorMax,
        tempMin: tempMin, tempMax: tempMax,
        dlMin: dlMin, dlMax: dlMax,
        modem: modem, speedtest: sortedSpeedtest, speedMarks: speedMarks, events: events, data: data,
        weather: weather, segment: segment, reachabilityBuckets: reachabilityBuckets, reachabilityLane: reachabilityLane,
        xScale: xScale, ySnr: ySnr, yTx: yTx, yDsPower: yDsPower, yDl: yDl, yTemp: yTemp, ySegment: ySegment,
        colors: { snr: snrColor, txPower: txColor, dsPower: dsPowerColor, download: downloadColor, upload: uploadColor, event: warnColor, errors: errorColor, temperature: tempColor, segmentDs: segDsColor, segmentUs: segUsColor, reachability: reachabilityColors, text: textColor, grid: gridColor },
        dpr: dpr
    };

    if (reachabilityLane && _corrVisible.reachability) {
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
                ctx.font = 'bold 9px system-ui, sans-serif';
                ctx.textAlign = 'center';
                var stateMark = reachBucket.state === 'ok' ? '\u2713' : reachBucket.state === 'degraded' ? '!' : reachBucket.state === 'down' ? '\u00d7' : '?';
                ctx.fillText(stateMark, (reachX1 + reachX2) / 2, reachabilityLane.y + 12);
            }
        }
        ctx.restore();
    }

    // Grid lines
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 0.5;
    ctx.setLineDash([2, 4]);
    for (var s = Math.ceil(snrMin); s <= snrMax; s += 5) {
        var y = ySnr(s);
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + plotW, y); ctx.stroke();
    }
    ctx.setLineDash([]);

    // Time axis labels
    ctx.fillStyle = textColor;
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    var labelCount = Math.min(8, Math.floor(plotW / 80));
    for (var i = 0; i <= labelCount; i++) {
        var t = tMin + (tMax - tMin) * i / labelCount;
        var range = getPillValue('correlation-tabs') || '1d';
        var label = docsightFormatXAxisLabel(t, range);
        ctx.fillText(label, xScale(t), H - pad.bottom + 18);
    }

    // Right axis labels (Speed) — only if download or upload visible
    if ((_corrVisible.download || _corrVisible.upload) && speedtest.length > 0) {
        ctx.textAlign = 'left';
        ctx.fillStyle = goodColor;
        var dlStep = Math.max(1, Math.ceil(dlMax / 5 / 50) * 50);
        for (var v = 0; v <= dlMax; v += dlStep) {
            ctx.fillText(v + ' Mbps', pad.left + plotW + 6, yDl(v) + 3);
        }
        ctx.save();
        ctx.translate(W - 8, pad.top + plotH / 2);
        ctx.rotate(Math.PI / 2);
        ctx.textAlign = 'center';
        ctx.font = '11px system-ui, sans-serif';
        ctx.fillText('Mbps', 0, 0);
        ctx.restore();
    }

    // Draw modem health background bands behind every evidence source.
    if (_corrVisible.poorSignal) {
        for (var i = 0; i < modem.length; i++) {
            var x1 = xScale(new Date(modem[i].timestamp).getTime());
            var x2 = i < modem.length - 1 ? xScale(new Date(modem[i + 1].timestamp).getTime()) : x1 + 2;
            var h = modem[i].health;
            if (h === 'critical') {
                ctx.fillStyle = 'rgba(244,67,54,0.08)';
            } else if (h === 'marginal') {
                ctx.fillStyle = 'rgba(255,152,0,0.06)';
            } else if (h === 'tolerated') {
                ctx.fillStyle = 'rgba(132,204,22,0.06)';
            } else {
                continue;
            }
            ctx.fillRect(x1, pad.top, x2 - x1, plotH);
        }
    }

    // Speedtests are point-in-time measurements. Draw their stems and heads
    // before signal/error/event evidence so those sources remain visually on top.
    _corrDrawSpeedMarks(ctx, speedMarks, yDl(0), {
        download: downloadColor,
        upload: uploadColor
    }, {
        download: _corrVisible.download,
        upload: _corrVisible.upload
    });

    // Draw modem SNR line without an area fill to keep the chart uncluttered
    if (_corrVisible.snr && modem.length > 1) {
        ctx.beginPath();
        for (var i = 0; i < modem.length; i++) {
            var x = xScale(new Date(modem[i].timestamp).getTime());
            var y = ySnr(modem[i].ds_snr_min || snrMin);
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                var x0 = xScale(new Date(modem[i - 1].timestamp).getTime());
                var y0 = ySnr(modem[i - 1].ds_snr_min || snrMin);
                var cpx = x0 + (x - x0) * 0.4;
                ctx.bezierCurveTo(cpx, y0, x - (x - x0) * 0.4, y, x, y);
            }
        }
        ctx.strokeStyle = snrColor;
        ctx.lineWidth = 2;
        ctx.stroke();
    }

    // Draw upstream TX power line
    if (_corrVisible.txPower && modem.length > 1 && txValues.length > 0) {
        ctx.beginPath();
        for (var i = 0; i < modem.length; i++) {
            var txVal = modem[i].us_power_avg;
            if (!txVal) continue;
            var x = xScale(new Date(modem[i].timestamp).getTime());
            var y = yTx(txVal);
            if (ctx._txStarted) {
                var x0 = ctx._txLastX;
                var y0 = ctx._txLastY;
                var cpx = x0 + (x - x0) * 0.4;
                ctx.bezierCurveTo(cpx, y0, x - (x - x0) * 0.4, y, x, y);
            } else {
                ctx.moveTo(x, y);
                ctx._txStarted = true;
            }
            ctx._txLastX = x;
            ctx._txLastY = y;
        }
        delete ctx._txStarted;
        delete ctx._txLastX;
        delete ctx._txLastY;
        ctx.strokeStyle = txColor;
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // Draw DS Power line (dotted pink)
    if (_corrVisible.dsPower && modem.length > 1 && dsPowerValues.length > 0) {
        ctx.beginPath();
        var dsStarted = false;
        for (var i = 0; i < modem.length; i++) {
            var dsVal = modem[i].ds_power_avg;
            if (dsVal == null) continue;
            var x = xScale(new Date(modem[i].timestamp).getTime());
            var y = yDsPower(dsVal);
            if (!dsStarted) {
                ctx.moveTo(x, y);
                dsStarted = true;
            } else {
                ctx.lineTo(x, y);
            }
        }
        ctx.strokeStyle = dsPowerColor;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([2, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // Draw uncorrectable error spikes (red bars from bottom)
    if (_corrVisible.errors && errorMax > 0) {
        var spikeMaxH = plotH * 0.3; // max 30% of plot height
        for (var i = 0; i < modem.length; i++) {
            var errVal = modem[i].ds_uncorrectable_errors || 0;
            if (errVal === 0) continue;
            var x = xScale(new Date(modem[i].timestamp).getTime());
            var spikeH = (errVal / errorMax) * spikeMaxH;
            if (spikeH < 2) spikeH = 2;
            ctx.fillStyle = errorColor;
            ctx.fillRect(x - 1.5, pad.top + plotH - spikeH, 3, spikeH);
        }
    }

    // Draw event markers (vertical dashed lines)
    var filteredEvents = _corrFilteredEvents(events);
    if (_corrVisible.events && filteredEvents.length > 0) {
        for (var i = 0; i < filteredEvents.length; i++) {
            var x = xScale(new Date(filteredEvents[i].timestamp).getTime());
            var sev = _corrNormalizeSeverity(filteredEvents[i]);
            ctx.strokeStyle = sev === 'critical' ? critColor : sev === 'warning' ? warnColor : textColor;
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(x, pad.top);
            ctx.lineTo(x, pad.top + plotH);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = ctx.strokeStyle;
            ctx.beginPath();
            ctx.moveTo(x, pad.top);
            ctx.lineTo(x - 4, pad.top - 8);
            ctx.lineTo(x + 4, pad.top - 8);
            ctx.closePath();
            ctx.fill();
        }
    }

    // Temperature line (dashed)
    if (_corrVisible.temperature && weather.length > 1) {
        ctx.beginPath();
        var started = false;
        for (var i = 0; i < weather.length; i++) {
            if (weather[i].temperature == null) continue;
            var x = xScale(new Date(weather[i].timestamp).getTime());
            var y = yTemp(weather[i].temperature);
            if (!started) { ctx.moveTo(x, y); started = true; }
            else {
                var x0 = xScale(new Date(weather[i - 1].timestamp).getTime());
                var y0 = yTemp(weather[i - 1].temperature);
                var cpx = x0 + (x - x0) * 0.4;
                ctx.bezierCurveTo(cpx, y0, x - (x - x0) * 0.4, y, x, y);
            }
        }
        ctx.strokeStyle = tempColor;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // Segment utilization lines (solid)
    if (segment.length > 1) {
        // DS total line
        if (_corrVisible.segmentDs) {
            ctx.beginPath();
            var started = false;
            for (var i = 0; i < segment.length; i++) {
                if (segment[i].ds_total == null) continue;
                var x = xScale(new Date(segment[i].timestamp).getTime());
                var y = ySegment(segment[i].ds_total);
                if (!started) { ctx.moveTo(x, y); started = true; }
                else { ctx.lineTo(x, y); }
            }
            ctx.strokeStyle = segDsColor;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([]);
            ctx.stroke();
        }
        // US total line
        if (_corrVisible.segmentUs) {
            ctx.beginPath();
            var started = false;
            for (var i = 0; i < segment.length; i++) {
                if (segment[i].us_total == null) continue;
                var x = xScale(new Date(segment[i].timestamp).getTime());
                var y = ySegment(segment[i].us_total);
                if (!started) { ctx.moveTo(x, y); started = true; }
                else { ctx.lineTo(x, y); }
            }
            ctx.strokeStyle = segUsColor;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([]);
            ctx.stroke();
        }
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
        if (errorMax > 0) {
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
            var sev = _corrNormalizeSeverity(events[i]);
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
            var filterBadge = item.visibleEventCount < item.totalEventCount ? ' <span style="font-size:0.7em;opacity:0.7;">(' + item.visibleEventCount + '/' + item.totalEventCount + ')</span>' : '';
            var eventCls = cls ? cls + ' corr-legend-events' : 'corr-legend-events';
            return '<span data-metric="events" tabindex="0" role="button" class="' + eventCls + '" title="' + (T.correlation_toggle_hint || 'Click to toggle') + '" style="color:' + item.color + ';">' + item.label + filterBadge +
                ' <span class="corr-event-filter-btn" title="' + (T.correlation_event_filter || 'Event Filter') + '">&#9881;</span></span>';
        }
        return '<span data-metric="' + item.metric + '" tabindex="0" role="button" class="' + cls + '" title="' + (T.correlation_toggle_hint || 'Click to toggle') + '" style="color:' + item.color + ';">' + item.label + '</span>';
    }).join('') + '<span data-metric="poorSignal" tabindex="0" role="button" class="corr-poor-signal-badge' + (_corrVisible.poorSignal ? '' : ' disabled') + '" title="' + (T.correlation_toggle_hint || 'Click to toggle') + '">' + (T.correlation_poor_signal || 'Poor Signal') + '</span>';

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
            var html = '<div style="font-weight:600; margin-bottom:6px; color:var(--text,#f0f0f0);">' + (T.event_filter_title || 'Event Types') + '</div>';
            var sortedTypes = Object.keys(eventTypes).sort();
            for (var si = 0; si < sortedTypes.length; si++) {
                var et = sortedTypes[si];
                var checked = _corrEventFilter[et] ? ' checked' : '';
                var label = typeLabel[et] || et.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
                var severityFilter = _corrEnsureEventSeverityFilter(et);
                html += '<div class="corr-event-filter-group" style="padding:5px 0 7px; border-top:1px solid rgba(148,163,184,0.14);">' +
                    '<label style="display:flex; align-items:center; gap:6px; padding:3px 0; cursor:pointer; color:var(--text-secondary,#9ca3af);">' +
                    '<input type="checkbox" data-event-type="' + _corrEscapeAttr(et) + '"' + checked + ' style="accent-color:' + warnColor + ';"> ' +
                    '<span style="font-weight:600; color:var(--text,#f0f0f0);">' + escapeHtml(label) + '</span> <span style="opacity:0.5; font-size:0.85em;">(' + eventTypes[et] + ')</span></label>' +
                    '<div style="display:flex; flex-wrap:wrap; gap:6px; padding-left:22px; margin-top:2px;">';
                for (var sj = 0; sj < _CORR_SEVERITIES.length; sj++) {
                    var sv = _CORR_SEVERITIES[sj];
                    var svChecked = severityFilter[sv] !== false ? ' checked' : '';
                    var svCount = (eventSeverityCounts[et] && eventSeverityCounts[et][sv]) || 0;
                    html += '<label style="display:inline-flex; align-items:center; gap:4px; cursor:pointer; color:var(--text-secondary,#9ca3af); font-size:0.85em;">' +
                        '<input type="checkbox" data-event-type="' + _corrEscapeAttr(et) + '" data-event-severity="' + _corrEscapeAttr(sv) + '"' + svChecked + ' style="accent-color:' + warnColor + ';"> ' +
                        escapeHtml(severityLabel[sv] || sv) + ' <span style="opacity:0.5;">(' + svCount + ')</span></label>';
                }
                html += '</div></div>';
            }
            pop.innerHTML = html;
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
    if (zoomBtn) zoomBtn.style.display = _corrZoom ? 'block' : 'none';

    // Setup tooltip interaction on overlay canvas
    _setupCorrelationTooltip(overlay, octx);
}

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
            newOctx.fillStyle = 'rgba(168,85,247,0.15)';
            newOctx.fillRect(x1, st.pad.top, x2 - x1, st.plotH);
            newOctx.strokeStyle = 'rgba(168,85,247,0.5)';
            newOctx.lineWidth = 1;
            newOctx.strokeRect(x1, st.pad.top, x2 - x1, st.plotH);
            tooltip.style.display = 'none';
            return;
        }

        var inPlot = mouseY >= st.pad.top && mouseY <= st.pad.top + st.plotH;
        var inReachabilityLane = st.reachabilityLane && _corrVisible.reachability
            && mouseY >= st.reachabilityLane.y && mouseY <= st.reachabilityLane.y + st.reachabilityLane.height;
        // Only interact within the shared time axis or the Reachability lane.
        if (mouseX < st.pad.left || mouseX > st.pad.left + st.plotW || (!inPlot && !inReachabilityLane)) {
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
        var anyModemVisible = _corrVisible.snr || _corrVisible.txPower || _corrVisible.dsPower || _corrVisible.errors;
        var nearestModem = null;
        if (st.modem.length > 0 && anyModemVisible) {
            var bestDist = Infinity;
            for (var i = 0; i < st.modem.length; i++) {
                var ts = new Date(st.modem[i].timestamp).getTime();
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
                var ts = new Date(st.speedtest[i].timestamp).getTime();
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
                var ts = new Date(visibleEvents[i].timestamp).getTime();
                var dist = Math.abs(ts - tHover);
                if (dist < bestDist) { bestDist = dist; nearestEvent = visibleEvents[i]; }
            }
        }

        // Find nearest weather point
        var nearestWeather = null;
        if (st.weather && st.weather.length > 0 && _corrVisible.temperature) {
            var bestDist = Infinity;
            for (var i = 0; i < st.weather.length; i++) {
                var ts = new Date(st.weather[i].timestamp).getTime();
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
        newOctx.lineTo(mouseX, st.pad.top + st.plotH);
        newOctx.stroke();
        newOctx.setLineDash([]);

        // Draw highlight dots at nearest data points
        if (nearestModem && _corrVisible.snr) {
            var dx = st.xScale(new Date(nearestModem.timestamp).getTime());
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
            var dx = st.xScale(new Date(nearestModem.timestamp).getTime());
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
            var dx = st.xScale(new Date(nearestModem.timestamp).getTime());
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
            var dx = st.xScale(new Date(nearestWeather.timestamp).getTime());
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
        if (nearestModem) displayTs = new Date(nearestModem.timestamp).getTime();
        if (nearestSpeed) {
            var spTs = new Date(nearestSpeed.timestamp).getTime();
            if (!nearestModem || Math.abs(spTs - tHover) < Math.abs(new Date(nearestModem.timestamp).getTime() - tHover)) {
                displayTs = spTs;
            }
        }
        var dDate = new Date(displayTs);
        var timeStr = String(dDate.getHours()).padStart(2, '0') + ':' + String(dDate.getMinutes()).padStart(2, '0') + ':' + String(dDate.getSeconds()).padStart(2, '0');
        var dateStr = dDate.getFullYear() + '-' + String(dDate.getMonth() + 1).padStart(2, '0') + '-' + String(dDate.getDate()).padStart(2, '0');
        html += '<div class="tt-time">' + dateStr + ' ' + timeStr + '</div>';

        if (nearestModem && _corrVisible.snr) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.snr + ';"></span> ' + (T.correlation_tt_snr || 'SNR') + ': ' + (nearestModem.ds_snr_min || 0).toFixed(1) + ' dB</div>';
        }
        if (nearestModem && _corrVisible.txPower && nearestModem.us_power_avg) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.txPower + ';"></span> ' + (T.correlation_tt_tx_power || 'TX Power') + ': ' + nearestModem.us_power_avg.toFixed(1) + ' dBmV</div>';
        }
        if (nearestModem && _corrVisible.dsPower && nearestModem.ds_power_avg != null) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.dsPower + ';"></span> ' + (T.correlation_tt_ds_power || 'DS Power') + ': ' + nearestModem.ds_power_avg.toFixed(1) + ' dBmV</div>';
        }
        if (nearestModem && _corrVisible.errors && (nearestModem.ds_uncorrectable_errors || 0) > 0) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.errors + ';"></span> ' + (T.correlation_tt_errors || 'Errors') + ': ' + nearestModem.ds_uncorrectable_errors.toLocaleString() + '</div>';
        }
        if (nearestSpeed) {
            var speedDownload = _corrMeasurement(nearestSpeed.download_mbps);
            var speedUpload = _corrMeasurement(nearestSpeed.upload_mbps);
            var speedPing = _corrMeasurement(nearestSpeed.ping_ms);
            var speedJitter = _corrMeasurement(nearestSpeed.jitter_ms);
            var speedPacketLoss = _corrMeasurement(nearestSpeed.packet_loss_pct);
            html += '<div class="tt-row tt-speedtest-time">' + (T.timestamp || 'Timestamp') + ': ' + escapeHtml(_corrFormatTimestamp(nearestSpeed.timestamp)) + '</div>';
            if (_corrVisible.download && speedDownload !== null) {
                html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.download + ';"></span> ' + (T.correlation_tt_download || 'Download') + ': ' + speedDownload.toFixed(1) + ' Mbps</div>';
            }
            if (_corrVisible.upload && speedUpload !== null) {
                html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.upload + ';"></span> ' + (T.correlation_tt_upload || 'Upload') + ': ' + speedUpload.toFixed(1) + ' Mbps</div>';
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
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.event + ';"></span> ' + (T.correlation_tt_event || 'Event') + ': ' + escapeHtml(nearestEvent.message || nearestEvent.severity || '') + '</div>';
        }
        if (nearestWeather && _corrVisible.temperature && nearestWeather.temperature != null) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.temperature + ';"></span> ' + (T.temperature || 'Temperature') + ': ' + fmtTemp(nearestWeather.temperature) + '</div>';
        }
        if (reachabilityBucket) {
            var stateLabels = {
                ok: T.correlation_reachability_ok || 'OK',
                degraded: T.correlation_reachability_degraded || 'Degraded',
                down: T.correlation_reachability_down || 'Down',
                unknown: T.correlation_reachability_unknown || 'Unknown'
            };
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.reachability[reachabilityBucket.state] + ';"></span> '
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
                var sd = Math.abs(new Date(st.segment[si].timestamp).getTime() - tHover);
                if (sd < segDist) { segDist = sd; nearestSeg = st.segment[si]; }
            }
            if (nearestSeg && segDist < (st.tMax - st.tMin) * 0.05) {
                if (_corrVisible.segmentDs && nearestSeg.ds_total != null) {
                    html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.segmentDs + ';"></span> ' + (T.seg_correlation_ds || 'Segment DS') + ': ' + nearestSeg.ds_total.toFixed(1) + '%</div>';
                }
                if (_corrVisible.segmentUs && nearestSeg.us_total != null) {
                    html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.segmentUs + ';"></span> ' + (T.seg_correlation_us || 'Segment US') + ': ' + nearestSeg.us_total.toFixed(1) + '%</div>';
                }
            }
        }

        tooltip.innerHTML = html;
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

    var ts = new Date(timestamp).getTime();
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
    var bg = getComputedStyle(document.documentElement).getPropertyValue('--card-bg').trim() || '#1a1a2e';
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

function _corrEncodeCSVCell(value) {
    if (value == null || value === '') return '';
    if (typeof value !== 'string') return value;

    var firstMeaningful = value.search(/\S/);
    var hasLeadingControlPrefix = /^[\s]*[\t\r]/.test(value);
    if (hasLeadingControlPrefix
            || (firstMeaningful !== -1 && '=+-@'.indexOf(value.charAt(firstMeaningful)) !== -1)) {
        value = "'" + value;
    }
    if (/[",\r\n]/.test(value)) return '"' + value.replace(/"/g, '""') + '"';
    return value;
}

function _corrExportCSV() {
    var reachabilityBuckets = _corrChartState && _corrChartState.reachabilityBuckets ? _corrChartState.reachabilityBuckets : [];
    if ((!_correlationData || _correlationData.length === 0) && reachabilityBuckets.length === 0) return;
    var baseHeaders = ['timestamp', 'source', 'health', 'ds_snr_min', 'ds_power_avg', 'us_power_avg', 'ds_uncorrectable_errors', 'download_mbps', 'upload_mbps', 'ping_ms', 'severity', 'message'];
    var reachabilityHeaders = ['state', 'packet_loss_pct', 'sample_count', 'bucket_start', 'bucket_end', 'target_scope'];
    var headers = baseHeaders.concat(reachabilityHeaders);
    var rows = [headers.map(_corrEncodeCSVCell).join(',')];
    for (var i = 0; i < _correlationData.length; i++) {
        var d = _correlationData[i];
        var row = headers.map(function(h) {
            if (reachabilityHeaders.indexOf(h) !== -1) return '';
            var v = d[h];
            return _corrEncodeCSVCell(v);
        });
        rows.push(row.join(','));
    }
    for (var ri = 0; ri < reachabilityBuckets.length; ri++) {
        var bucket = reachabilityBuckets[ri];
        var reachabilityRow = {
            timestamp: new Date(bucket.startMs).toISOString(),
            source: 'connection_monitor',
            state: bucket.state,
            packet_loss_pct: bucket.lossPct == null ? '' : Number(bucket.lossPct.toFixed(4)),
            sample_count: bucket.sampleCount,
            bucket_start: new Date(bucket.startMs).toISOString(),
            bucket_end: new Date(bucket.endMs).toISOString(),
            target_scope: bucket.targetScope || ''
        };
        rows.push(headers.map(function(h) {
            var v = reachabilityRow[h];
            return _corrEncodeCSVCell(v);
        }).join(','));
    }
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

    // Show newest first in table
    var sorted = data.slice().reverse();

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
        return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
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

    var sorted = data.slice().reverse();
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
        var ts = escapeHtml(e.timestamp.replace('T', ' '));
        var src = e.source;
        var msg = '';
        var details = '';

        if (src === 'modem') {
            var h = e.health || 'unknown';
            var badge = '<span class="st-health-badge health-' + h + '">' + (healthLabels[h] || h) + '</span>';
            src = '<span style="color:var(--accent);">Modem</span>';
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
            src = '<span style="color:var(--good);">Speedtest</span>';
            msg = (e.download_mbps ? e.download_mbps.toFixed(1) + ' / ' + (e.upload_mbps || 0).toFixed(1) + ' Mbps' : '');
            var mhBadge = '';
            if (e.modem_health) {
                mhBadge = ' <span class="st-health-badge health-' + e.modem_health + '" style="font-size:0.75em;">'
                    + (healthLabels[e.modem_health] || e.modem_health) + '</span>';
            }
            details = (T.speedtest_ping || 'Ping') + ' ' + (e.ping_ms || '') + ' ms | Jitter ' + (e.jitter_ms || '') + ' ms' + mhBadge;
        } else if (src === 'capture') {
            var scStatus = e.status || '';
            var scColor = scStatus === 'completed' ? 'var(--good)'
                : scStatus === 'suppressed' ? 'var(--muted)'
                : scStatus === 'expired' ? 'var(--crit)'
                : 'var(--accent)';
            src = '<span style="color:' + scColor + ';">' + escapeHtml(T.correlation_source_capture || 'Capture') + '</span>';
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
            var eventSeverity = _corrNormalizeSeverity(e);
            var sevColor = eventSeverity === 'critical' ? 'var(--crit)' : eventSeverity === 'warning' ? 'var(--warn)' : 'var(--muted)';
            src = '<span style="color:' + sevColor + ';">' + escapeHtml(sevLabels[eventSeverity] || eventSeverity) + '</span>';
            msg = escapeHtml(e.message || '');
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
}
