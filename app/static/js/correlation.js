/* ═══ DOCSight Correlation Analysis Module ═══ */

/* ═══ Correlation Analysis ═══ */
var _correlationData = [];
var _correlationChart = null;
var _corrVisible = { snr: true, txPower: true, dsPower: true, download: true, upload: true, events: false, errors: true, poorSignal: true, temperature: true };
var _corrWeatherData = [];
var _corrChartState = null; // Stores scales/data for tooltip lookups
var _corrZoom = null; // { tMin, tMax } when zoomed in
// Event type sub-filter: operational events hidden by default
var _corrEventFilter = {};
var _OPERATIONAL_EVENTS = { monitoring_started: true, monitoring_stopped: true };
function _corrFilteredEvents(events) {
    if (!_corrVisible.events) return [];
    return events.filter(function(e) {
        var t = e.event_type || 'unknown';
        if (!(t in _corrEventFilter)) _corrEventFilter[t] = !_OPERATIONAL_EVENTS[t];
        return _corrEventFilter[t];
    });
}

// Re-render chart on container resize
(function() {
    var resizeTimer;
    var observer = new ResizeObserver(function() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function() {
            if (_correlationData && _correlationData.length > 0) {
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
    var hours = getPillValue('correlation-tabs');

    var loading = document.getElementById('correlation-loading');
    var noData = document.getElementById('correlation-no-data');
    var chartContainer = document.getElementById('correlation-chart-container');
    var tableCard = document.getElementById('correlation-table-card');
    loading.style.display = 'flex';
    noData.style.display = 'none';
    chartContainer.style.display = 'none';
    tableCard.style.display = 'none';

    /* Calculate time range for weather fetch */
    var now = new Date();
    var wEnd = now.toISOString().replace('T', ' ').substring(0, 19) + 'Z';
    var wStart = new Date(now.getTime() - parseInt(hours) * 3600000).toISOString().replace('T', ' ').substring(0, 19) + 'Z';
    var weatherUrl = '/api/weather/range?start=' + encodeURIComponent(wStart) + '&end=' + encodeURIComponent(wEnd);

    Promise.all([
        fetch('/api/correlation?hours=' + hours + '&sources=modem,speedtest,events').then(function(r) { return r.json(); }),
        fetch(weatherUrl).then(function(r) { return r.json(); }).catch(function() { return []; })
    ]).then(function(results) {
            var data = results[0];
            _corrWeatherData = results[1] || [];
            loading.style.display = 'none';
            _correlationData = data;
            if (!data || data.length === 0) {
                noData.textContent = T.correlation_no_data;
                noData.style.display = 'block';
                return;
            }
            chartContainer.style.display = 'block';
            tableCard.style.display = 'block';
            renderCorrelationChart(data);
            renderCorrelationTable(data);
        })
        .catch(function() {
            loading.style.display = 'none';
            noData.textContent = T.correlation_no_data;
            noData.style.display = 'block';
        });
}

function renderCorrelationChart(data) {
    var canvas = document.getElementById('correlation-chart');
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    var W = rect.width;
    var H = 280;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    // Setup overlay canvas to match main canvas
    var overlay = document.getElementById('correlation-overlay');
    overlay.width = W * dpr;
    overlay.height = H * dpr;
    overlay.style.width = W + 'px';
    overlay.style.height = H + 'px';
    var octx = overlay.getContext('2d');
    octx.scale(dpr, dpr);
    octx.clearRect(0, 0, W, H);

    var pad = { top: 20, right: 60, bottom: 40, left: 60 };
    var plotW = W - pad.left - pad.right;
    var plotH = H - pad.top - pad.bottom;

    var modem = data.filter(function(d) { return d.source === 'modem'; });
    var speedtest = data.filter(function(d) { return d.source === 'speedtest'; });
    var events = data.filter(function(d) { return d.source === 'event'; });

    if (modem.length === 0 && speedtest.length === 0) {
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
        ctx.font = '13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(T.correlation_no_data, W / 2, H / 2);
        return;
    }

    // Time range (with zoom support)
    var allTs = data.map(function(d) { return new Date(d.timestamp).getTime(); });
    var tMinFull = Math.min.apply(null, allTs);
    var tMaxFull = Math.max.apply(null, allTs);
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
    var dlValues = speedtest.map(function(d) { return d.download_mbps || 0; });
    var ulValues = speedtest.map(function(d) { return d.upload_mbps || 0; });
    var speedMax = dlValues.length ? Math.ceil(Math.max.apply(null, dlValues) * 1.1) : 500;
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
    var tempValues = weather.map(function(d) { return d.temperature; }).filter(function(v) { return v != null; });
    var tempMin = tempValues.length ? Math.floor(Math.min.apply(null, tempValues) - 2) : -10;
    var tempMax = tempValues.length ? Math.ceil(Math.max.apply(null, tempValues) + 2) : 40;
    function yTemp(v) { return pad.top + plotH - (v - tempMin) / (tempMax - tempMin) * plotH; }

    var uploadColor = '#06b6d4'; // cyan
    var snrColor = 'rgba(168,85,247,1)'; // purple
    var txColor = '#f59e0b'; // amber/orange
    var dsPowerColor = '#ec4899'; // pink
    var errorColor = 'rgba(239,68,68,0.6)'; // red semi-transparent
    var tempColor = '#f97316'; // orange

    var style = getComputedStyle(document.documentElement);
    var textColor = style.getPropertyValue('--muted').trim() || '#888';
    var gridColor = style.getPropertyValue('--input-border').trim() || '#333';
    var goodColor = style.getPropertyValue('--good').trim() || '#4caf50';
    var warnColor = style.getPropertyValue('--warn').trim() || '#ff9800';
    var critColor = style.getPropertyValue('--crit').trim() || '#f44336';
    var accentColor = style.getPropertyValue('--accent').trim() || '#2196f3';

    // Store chart state for tooltip lookups
    var sortedSpeedtest = speedtest.slice().sort(function(a, b) {
        return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
    });
    _corrChartState = {
        pad: pad, plotW: plotW, plotH: plotH, W: W, H: H,
        tMin: tMin, tMax: tMax, tMinFull: tMinFull, tMaxFull: tMaxFull,
        snrMin: snrMin, snrMax: snrMax, txMin: txMin, txMax: txMax,
        dsPowerMin: dsPowerMin, dsPowerMax: dsPowerMax, errorMax: errorMax,
        tempMin: tempMin, tempMax: tempMax,
        dlMin: dlMin, dlMax: dlMax,
        modem: modem, speedtest: sortedSpeedtest, events: events, data: data,
        weather: weather,
        xScale: xScale, ySnr: ySnr, yTx: yTx, yDsPower: yDsPower, yDl: yDl, yTemp: yTemp,
        colors: { snr: snrColor, txPower: txColor, dsPower: dsPowerColor, download: goodColor, upload: uploadColor, event: warnColor, errors: errorColor, temperature: tempColor, text: textColor, grid: gridColor },
        dpr: dpr
    };

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
        var d = new Date(t);
        var hours = getPillValue('correlation-tabs');
        var label;
        if (parseInt(hours) > 48) {
            label = (d.getMonth() + 1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        } else {
            label = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        }
        ctx.fillText(label, xScale(t), H - pad.bottom + 18);
    }

    // Left axis labels (SNR) — only if SNR visible
    if (_corrVisible.snr && modem.length > 0) {
        ctx.textAlign = 'right';
        ctx.fillStyle = accentColor;
        for (var s = Math.ceil(snrMin); s <= snrMax; s += 5) {
            ctx.fillText(s + ' dB', pad.left - 6, ySnr(s) + 3);
        }
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textAlign = 'center';
        ctx.font = '11px system-ui, sans-serif';
        ctx.fillText('SNR (dB)', 0, 0);
        ctx.restore();
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

    // Draw modem SNR line with gradient fill
    if (_corrVisible.snr && modem.length > 1) {
        var gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
        gradient.addColorStop(0, 'rgba(168,85,247,0.3)');
        gradient.addColorStop(1, 'rgba(168,85,247,0)');
        ctx.beginPath();
        ctx.moveTo(xScale(new Date(modem[0].timestamp).getTime()), pad.top + plotH);
        for (var i = 0; i < modem.length; i++) {
            var x = xScale(new Date(modem[i].timestamp).getTime());
            var y = ySnr(modem[i].ds_snr_min || snrMin);
            ctx.lineTo(x, y);
        }
        ctx.lineTo(xScale(new Date(modem[modem.length - 1].timestamp).getTime()), pad.top + plotH);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();
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

    // Draw modem health background bands
    if (_corrVisible.poorSignal) {
        for (var i = 0; i < modem.length; i++) {
            var x1 = xScale(new Date(modem[i].timestamp).getTime());
            var x2 = i < modem.length - 1 ? xScale(new Date(modem[i + 1].timestamp).getTime()) : x1 + 2;
            var h = modem[i].health;
            if (h === 'poor' || h === 'critical') {
                ctx.fillStyle = 'rgba(244,67,54,0.08)';
            } else if (h === 'marginal') {
                ctx.fillStyle = 'rgba(255,152,0,0.06)';
            } else {
                continue;
            }
            ctx.fillRect(x1, pad.top, x2 - x1, plotH);
        }
    }

    // Draw speedtest lines
    if (sortedSpeedtest.length > 1) {
        // Download line with gradient fill
        if (_corrVisible.download) {
            var dlGrad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
            dlGrad.addColorStop(0, 'rgba(76,175,80,0.2)');
            dlGrad.addColorStop(1, 'rgba(76,175,80,0)');
            ctx.beginPath();
            ctx.moveTo(xScale(new Date(sortedSpeedtest[0].timestamp).getTime()), pad.top + plotH);
            for (var i = 0; i < sortedSpeedtest.length; i++) {
                var x = xScale(new Date(sortedSpeedtest[i].timestamp).getTime());
                var y = yDl(sortedSpeedtest[i].download_mbps || 0);
                ctx.lineTo(x, y);
            }
            ctx.lineTo(xScale(new Date(sortedSpeedtest[sortedSpeedtest.length - 1].timestamp).getTime()), pad.top + plotH);
            ctx.closePath();
            ctx.fillStyle = dlGrad;
            ctx.fill();
            ctx.beginPath();
            for (var i = 0; i < sortedSpeedtest.length; i++) {
                var x = xScale(new Date(sortedSpeedtest[i].timestamp).getTime());
                var y = yDl(sortedSpeedtest[i].download_mbps || 0);
                if (i === 0) { ctx.moveTo(x, y); }
                else {
                    var x0 = xScale(new Date(sortedSpeedtest[i - 1].timestamp).getTime());
                    var y0 = yDl(sortedSpeedtest[i - 1].download_mbps || 0);
                    var cpx = x0 + (x - x0) * 0.4;
                    ctx.bezierCurveTo(cpx, y0, x - (x - x0) * 0.4, y, x, y);
                }
            }
            ctx.strokeStyle = goodColor;
            ctx.lineWidth = 2;
            ctx.stroke();
        }

        // Upload line
        if (_corrVisible.upload) {
            ctx.beginPath();
            for (var i = 0; i < sortedSpeedtest.length; i++) {
                var x = xScale(new Date(sortedSpeedtest[i].timestamp).getTime());
                var y = yDl(sortedSpeedtest[i].upload_mbps || 0);
                if (i === 0) { ctx.moveTo(x, y); }
                else {
                    var x0 = xScale(new Date(sortedSpeedtest[i - 1].timestamp).getTime());
                    var y0 = yDl(sortedSpeedtest[i - 1].upload_mbps || 0);
                    var cpx = x0 + (x - x0) * 0.4;
                    ctx.bezierCurveTo(cpx, y0, x - (x - x0) * 0.4, y, x, y);
                }
            }
            ctx.strokeStyle = uploadColor;
            ctx.lineWidth = 2;
            ctx.stroke();
        }

        // Data point dots
        for (var i = 0; i < sortedSpeedtest.length; i++) {
            var x = xScale(new Date(sortedSpeedtest[i].timestamp).getTime());
            if (_corrVisible.download) {
                ctx.beginPath();
                ctx.arc(x, yDl(sortedSpeedtest[i].download_mbps || 0), 3, 0, Math.PI * 2);
                ctx.fillStyle = goodColor;
                ctx.fill();
            }
            if (_corrVisible.upload) {
                ctx.beginPath();
                ctx.arc(x, yDl(sortedSpeedtest[i].upload_mbps || 0), 3, 0, Math.PI * 2);
                ctx.fillStyle = uploadColor;
                ctx.fill();
            }
        }
    } else if (sortedSpeedtest.length === 1) {
        var x = xScale(new Date(sortedSpeedtest[0].timestamp).getTime());
        if (_corrVisible.download) {
            ctx.beginPath();
            ctx.arc(x, yDl(sortedSpeedtest[0].download_mbps || 0), 5, 0, Math.PI * 2);
            ctx.fillStyle = goodColor;
            ctx.fill();
        }
        if (_corrVisible.upload) {
            ctx.beginPath();
            ctx.arc(x, yDl(sortedSpeedtest[0].upload_mbps || 0), 5, 0, Math.PI * 2);
            ctx.fillStyle = uploadColor;
            ctx.fill();
        }
    }

    // Draw event markers (vertical dashed lines)
    var filteredEvents = _corrFilteredEvents(events);
    if (_corrVisible.events && filteredEvents.length > 0) {
        for (var i = 0; i < filteredEvents.length; i++) {
            var x = xScale(new Date(filteredEvents[i].timestamp).getTime());
            var sev = filteredEvents[i].severity;
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

    // Interactive Legend
    var legend = document.getElementById('correlation-legend');
    var legendItems = [];
    if (modem.length > 0) {
        legendItems.push({ metric: 'snr', color: snrColor, label: '&#9644; SNR (dB)' });
        if (txValues.length > 0) {
            legendItems.push({ metric: 'txPower', color: txColor, label: '&#9476; TX Power (dBmV)' });
        }
        if (dsPowerValues.length > 0) {
            legendItems.push({ metric: 'dsPower', color: dsPowerColor, label: '&#183;&#183; DS Power (dBmV)' });
        }
        if (errorMax > 0) {
            legendItems.push({ metric: 'errors', color: 'rgba(239,68,68,0.8)', label: '&#9612; Errors' });
        }
    }
    if (speedtest.length > 0) {
        legendItems.push({ metric: 'download', color: goodColor, label: '&#9644; Download (Mbps)' });
        legendItems.push({ metric: 'upload', color: uploadColor, label: '&#9644; Upload (Mbps)' });
    }
    if (events.length > 0) {
        // Populate _corrEventFilter for all event types in current data
        var eventTypes = {};
        for (var i = 0; i < events.length; i++) {
            var et = events[i].event_type || 'unknown';
            eventTypes[et] = (eventTypes[et] || 0) + 1;
            if (!(et in _corrEventFilter)) _corrEventFilter[et] = !_OPERATIONAL_EVENTS[et];
        }
        legendItems.push({ metric: 'events', color: warnColor, label: '&#9650; Events', eventTypes: eventTypes });
    }
    if (weather.length > 0) {
        legendItems.push({ metric: 'temperature', color: tempColor, label: '- - ' + (T.temperature || 'Temperature') + ' (°C)' });
    }
    legend.innerHTML = legendItems.map(function(item) {
        var cls = _corrVisible[item.metric] ? '' : ' disabled';
        if (item.metric === 'events') {
            var filterCount = 0, totalTypes = 0;
            for (var et in item.eventTypes) { totalTypes++; if (_corrEventFilter[et]) filterCount++; }
            var filterBadge = filterCount < totalTypes ? ' <span style="font-size:0.7em;opacity:0.7;">(' + filterCount + '/' + totalTypes + ')</span>' : '';
            return '<span data-metric="events" class="' + cls + '" title="Klicken zum Ein-/Ausblenden" style="color:' + item.color + '; position:relative;">' + item.label + filterBadge +
                ' <span class="corr-event-filter-btn" title="Event-Filter" style="cursor:pointer; font-size:0.75em; opacity:0.6; margin-left:2px;">&#9881;</span></span>';
        }
        return '<span data-metric="' + item.metric + '" class="' + cls + '" title="Klicken zum Ein-/Ausblenden" style="color:' + item.color + ';">' + item.label + '</span>';
    }).join('') + '<span data-metric="poorSignal" class="' + (_corrVisible.poorSignal ? '' : 'disabled') + '" title="Klicken zum Ein-/Ausblenden" style="background:rgba(244,67,54,0.15); padding:1px 6px; border-radius:3px; font-size:0.8em; color:#f44336;">Poor Signal</span>';

    // Event filter popover
    var filterBtn = legend.querySelector('.corr-event-filter-btn');
    if (filterBtn) {
        filterBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            var existing = document.getElementById('corr-event-popover');
            if (existing) { existing.remove(); return; }
            var pop = document.createElement('div');
            pop.id = 'corr-event-popover';
            pop.style.cssText = 'position:absolute; z-index:100; background:var(--bg,#1f2937); border:1px solid var(--card-border,rgba(255,255,255,0.08)); border-radius:8px; padding:8px 12px; min-width:180px; box-shadow:0 4px 16px rgba(0,0,0,0.4); font-size:0.85em;';
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
            var html = '<div style="font-weight:600; margin-bottom:6px; color:var(--text,#f0f0f0);">' + (T.event_filter_title || 'Event Types') + '</div>';
            var sortedTypes = Object.keys(eventTypes).sort();
            for (var si = 0; si < sortedTypes.length; si++) {
                var et = sortedTypes[si];
                var checked = _corrEventFilter[et] ? ' checked' : '';
                var label = typeLabel[et] || et.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
                html += '<label style="display:flex; align-items:center; gap:6px; padding:3px 0; cursor:pointer; color:var(--text-secondary,#9ca3af);">' +
                    '<input type="checkbox" data-event-type="' + et + '"' + checked + ' style="accent-color:' + warnColor + ';"> ' +
                    label + ' <span style="opacity:0.5; font-size:0.85em;">(' + eventTypes[et] + ')</span></label>';
            }
            pop.innerHTML = html;
            this.parentElement.appendChild(pop);
            // Prevent clicks inside popover from bubbling to legend toggle
            pop.addEventListener('click', function(e) { e.stopPropagation(); });
            pop.querySelectorAll('input[data-event-type]').forEach(function(cb) {
                cb.addEventListener('change', function() {
                    _corrEventFilter[this.getAttribute('data-event-type')] = this.checked;
                    renderCorrelationChart(data);
                });
            });
            // Close on outside click
            setTimeout(function() {
                document.addEventListener('click', function closePopover(ev) {
                    if (!pop.contains(ev.target) && ev.target !== filterBtn) {
                        pop.remove();
                        document.removeEventListener('click', closePopover);
                    }
                });
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
    }

    // Show/hide zoom reset button
    var zoomBtn = document.getElementById('correlation-zoom-reset');
    if (zoomBtn) zoomBtn.style.display = _corrZoom ? 'block' : 'none';

    // Setup tooltip interaction on overlay canvas
    _setupCorrelationTooltip(overlay, octx);
}

function _corrResetZoom() {
    _corrZoom = null;
    if (_correlationData && _correlationData.length > 0) {
        renderCorrelationChart(_correlationData);
    }
}

function _setupCorrelationTooltip(overlay, octx) {
    var tooltip = document.getElementById('correlation-tooltip');

    // Remove old listeners by replacing the overlay node
    var newOverlay = overlay.cloneNode(true);
    overlay.parentNode.replaceChild(newOverlay, overlay);
    var newOctx = newOverlay.getContext('2d');
    var st = _corrChartState;
    if (!st) return;
    newOctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);

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
            renderCorrelationChart(st.data);
            return;
        }
        dragStart = null;
    });

    newOverlay.addEventListener('mousemove', function(e) {
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

        // Only interact within plot area
        if (mouseX < st.pad.left || mouseX > st.pad.left + st.plotW || mouseY < st.pad.top || mouseY > st.pad.top + st.plotH) {
            newOctx.clearRect(0, 0, st.W, st.H);
            tooltip.style.display = 'none';
            return;
        }

        // Convert mouseX to timestamp
        var tHover = st.tMin + (mouseX - st.pad.left) / st.plotW * (st.tMax - st.tMin);

        // Find nearest modem point
        var nearestModem = null;
        if (st.modem.length > 0 && _corrVisible.snr) {
            var bestDist = Infinity;
            for (var i = 0; i < st.modem.length; i++) {
                var ts = new Date(st.modem[i].timestamp).getTime();
                var dist = Math.abs(ts - tHover);
                if (dist < bestDist) { bestDist = dist; nearestModem = st.modem[i]; }
            }
        }

        // Find nearest speedtest point
        var nearestSpeed = null;
        if (st.speedtest.length > 0 && (_corrVisible.download || _corrVisible.upload)) {
            var bestDist = Infinity;
            for (var i = 0; i < st.speedtest.length; i++) {
                var ts = new Date(st.speedtest[i].timestamp).getTime();
                var dist = Math.abs(ts - tHover);
                if (dist < bestDist) { bestDist = dist; nearestSpeed = st.speedtest[i]; }
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
        if (nearestSpeed) {
            if (_corrVisible.download) {
                var dx = st.xScale(new Date(nearestSpeed.timestamp).getTime());
                var dy = st.yDl(nearestSpeed.download_mbps || 0);
                newOctx.beginPath();
                newOctx.arc(dx, dy, 5, 0, Math.PI * 2);
                newOctx.fillStyle = st.colors.download;
                newOctx.fill();
                newOctx.strokeStyle = '#fff';
                newOctx.lineWidth = 2;
                newOctx.stroke();
            }
            if (_corrVisible.upload) {
                var dx = st.xScale(new Date(nearestSpeed.timestamp).getTime());
                var dy = st.yDl(nearestSpeed.upload_mbps || 0);
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
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.snr + ';"></span> SNR: ' + (nearestModem.ds_snr_min || 0).toFixed(1) + ' dB</div>';
        }
        if (nearestModem && _corrVisible.txPower && nearestModem.us_power_avg) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.txPower + ';"></span> TX Power: ' + nearestModem.us_power_avg.toFixed(1) + ' dBmV</div>';
        }
        if (nearestModem && _corrVisible.dsPower && nearestModem.ds_power_avg != null) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.dsPower + ';"></span> DS Power: ' + nearestModem.ds_power_avg.toFixed(1) + ' dBmV</div>';
        }
        if (nearestModem && _corrVisible.errors && (nearestModem.ds_uncorrectable_errors || 0) > 0) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.errors + ';"></span> Errors: ' + nearestModem.ds_uncorrectable_errors.toLocaleString() + '</div>';
        }
        if (nearestSpeed && _corrVisible.download) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.download + ';"></span> Download: ' + (nearestSpeed.download_mbps || 0).toFixed(1) + ' Mbps</div>';
        }
        if (nearestSpeed && _corrVisible.upload) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.upload + ';"></span> Upload: ' + (nearestSpeed.upload_mbps || 0).toFixed(1) + ' Mbps</div>';
        }
        if (nearestEvent && _corrVisible.events) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.event + ';"></span> Event: ' + (nearestEvent.message || nearestEvent.severity || '') + '</div>';
        }
        if (nearestWeather && _corrVisible.temperature && nearestWeather.temperature != null) {
            html += '<div class="tt-row"><span class="tt-dot" style="background:' + st.colors.temperature + ';"></span> ' + (T.temperature || 'Temperature') + ': ' + nearestWeather.temperature.toFixed(1) + ' \u00B0C</div>';
        }

        tooltip.innerHTML = html;
        tooltip.style.display = 'block';

        // Position tooltip — flip to left side if near right edge
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

        // Highlight corresponding table rows
        _corrHighlightTableRows(nearestModem, nearestSpeed, nearestEvent);
    });

    newOverlay.addEventListener('mouseleave', function() {
        dragStart = null;
        if (!_corrChartState) return;
        var st = _corrChartState;
        newOctx.clearRect(0, 0, st.W, st.H);
        tooltip.style.display = 'none';
        _corrClearTableHighlight();
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
                if (_corrVisible.download) {
                    var dy = st.yDl(st.speedtest[i].download_mbps || 0);
                    octx.beginPath();
                    octx.arc(x, dy, 6, 0, Math.PI * 2);
                    octx.fillStyle = st.colors.download;
                    octx.fill();
                    octx.strokeStyle = '#fff';
                    octx.lineWidth = 2;
                    octx.stroke();
                }
                if (_corrVisible.upload) {
                    var dy = st.yDl(st.speedtest[i].upload_mbps || 0);
                    octx.beginPath();
                    octx.arc(x, dy, 6, 0, Math.PI * 2);
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
    var canvas = document.getElementById('correlation-chart');
    if (!canvas) return;
    var link = document.createElement('a');
    link.download = 'correlation-chart-' + new Date().toISOString().slice(0, 10) + '.png';
    link.href = canvas.toDataURL('image/png');
    link.click();
}

function _corrExportCSV() {
    if (!_correlationData || _correlationData.length === 0) return;
    var headers = ['timestamp', 'source', 'health', 'ds_snr_min', 'ds_power_avg', 'us_power_avg', 'ds_uncorrectable_errors', 'download_mbps', 'upload_mbps', 'ping_ms', 'severity', 'message'];
    var rows = [headers.join(',')];
    for (var i = 0; i < _correlationData.length; i++) {
        var d = _correlationData[i];
        var row = headers.map(function(h) {
            var v = d[h];
            if (v == null) return '';
            if (typeof v === 'string' && (v.indexOf(',') !== -1 || v.indexOf('"') !== -1)) {
                return '"' + v.replace(/"/g, '""') + '"';
            }
            return v;
        });
        rows.push(row.join(','));
    }
    var blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    var link = document.createElement('a');
    link.download = 'correlation-data-' + new Date().toISOString().slice(0, 10) + '.csv';
    link.href = URL.createObjectURL(blob);
    link.click();
    URL.revokeObjectURL(link.href);
}

function renderCorrelationTable(data) {
    var tbody = document.getElementById('correlation-tbody');
    tbody.innerHTML = '';

    // Show newest first in table
    var sorted = data.slice().reverse();

    var healthLabels = {
        good: T.health_good,
        marginal: T.health_marginal,
        poor: T.health_poor,
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

        var tr = document.createElement('tr');
        tr.setAttribute('data-ts', e.timestamp);
        tr.setAttribute('data-src', e.source);
        var ts = escapeHtml(e.timestamp.replace('T', ' '));
        var src = e.source;
        var msg = '';
        var details = '';

        if (src === 'modem') {
            var h = e.health || 'unknown';
            var badge = '<span class="st-health-badge health-' + h + '">' + (healthLabels[h] || h) + '</span>';
            src = '<span style="color:var(--accent);">Modem</span>';
            msg = badge;
            details = 'SNR ' + (e.ds_snr_min != null ? e.ds_snr_min + ' dB' : '') +
                      ' | Power ' + (e.ds_power_avg != null ? e.ds_power_avg + ' dBmV' : '') +
                      ' | TX ' + (e.us_power_avg != null ? e.us_power_avg + ' dBmV' : '') +
                      ' | Errors ' + (e.ds_uncorrectable_errors || 0);
        } else if (src === 'speedtest') {
            src = '<span style="color:var(--good);">Speedtest</span>';
            msg = (e.download_mbps ? e.download_mbps.toFixed(1) + ' / ' + (e.upload_mbps || 0).toFixed(1) + ' Mbps' : '');
            var mhBadge = '';
            if (e.modem_health) {
                mhBadge = ' <span class="st-health-badge health-' + e.modem_health + '" style="font-size:0.75em;">'
                    + (healthLabels[e.modem_health] || e.modem_health) + '</span>';
            }
            details = 'Ping ' + (e.ping_ms || '') + ' ms | Jitter ' + (e.jitter_ms || '') + ' ms' + mhBadge;
        } else if (src === 'event') {
            var sevColor = e.severity === 'critical' ? 'var(--crit)' : e.severity === 'warning' ? 'var(--warn)' : 'var(--muted)';
            src = '<span style="color:' + sevColor + ';">' + (sevLabels[e.severity] || e.severity) + '</span>';
            msg = escapeHtml(e.message || '');
            details = typeLabels[e.event_type] || e.event_type || '';
        }

        tr.innerHTML = '<td style="white-space:nowrap; font-size:0.82em;">' + ts + '</td>'
            + '<td>' + src + '</td>'
            + '<td>' + msg + '</td>'
            + '<td style="font-size:0.82em; color:var(--muted);">' + details + '</td>';
        tr.addEventListener('mouseenter', function() {
            var rowTs = this.getAttribute('data-ts');
            var rowSrc = this.getAttribute('data-src');
            _corrHighlightFromTable(rowTs, rowSrc);
        });
        tr.addEventListener('mouseleave', function() {
            _corrClearChartHighlight();
        });
        tbody.appendChild(tr);
        count++;
    }
}
