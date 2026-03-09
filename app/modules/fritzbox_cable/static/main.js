/* ── FRITZ!Box Cable Segment Utilization ── */

var _fritzCableRange = '24h';

/* ── Range Tab Switching ── */
var fritzCableTabs = document.querySelectorAll('#fritz-cable-range-tabs .trend-tab');
fritzCableTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _fritzCableRange = this.getAttribute('data-range');
        fritzCableTabs.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-range') === _fritzCableRange);
        });
        loadFritzCableData();
    });
});

/* ── i18n helper ── */
function _fcT(key, fallback) {
    return T[key] || T['docsight.fritzbox_cable.' + key] || fallback || key;
}

/* ── Data Loading ── */
function loadFritzCableData() {
    var msg = document.getElementById('fritz-cable-message');
    var content = document.getElementById('fritz-cable-content');
    if (!msg || !content) return;

    msg.textContent = _fcT('loading', 'Loading segment utilization...');
    msg.style.display = 'block';
    content.style.display = 'none';

    fetch('/api/fritzbox/segment-utilization?range=' + encodeURIComponent(_fritzCableRange))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                msg.textContent = data.error;
                return;
            }
            if (!data.samples || data.samples.length === 0) {
                msg.textContent = _fcT('no_data', 'No segment utilization data collected yet.');
                return;
            }
            msg.style.display = 'none';
            content.style.display = '';
            _fritzCableUpdateKPIs(data);
            _fritzCableRenderChart('fritz-cable-ds-chart', data.samples, 'ds_total', 'ds_own');
            _fritzCableRenderChart('fritz-cable-us-chart', data.samples, 'us_total', 'us_own');
        })
        .catch(function() {
            msg.textContent = _fcT('unavailable', 'Configuration unavailable.');
        });
}

/* ── KPI Update ── */
function _fritzCableUpdateKPIs(data) {
    var latest = data.latest && data.latest[0];
    var stats = data.stats || {};

    var dsEl = document.getElementById('fritz-cable-ds-total');
    var usEl = document.getElementById('fritz-cable-us-total');
    var statusEl = document.getElementById('fritz-cable-status');
    var dsStats = document.getElementById('fritz-cable-ds-stats');
    var usStats = document.getElementById('fritz-cable-us-stats');
    var countEl = document.getElementById('fritz-cable-count');

    if (dsEl) dsEl.textContent = latest ? (latest.ds_total != null ? latest.ds_total.toFixed(1) + '%' : '-') : '-';
    if (usEl) usEl.textContent = latest ? (latest.us_total != null ? latest.us_total.toFixed(1) + '%' : '-') : '-';
    if (statusEl) statusEl.textContent = stats.count > 0 ? _fcT('status_polling', 'Collecting') : _fcT('status_disabled', 'Disabled');

    if (dsStats && stats.count > 0) {
        dsStats.textContent = _fcT('min', 'Min') + ' ' + (stats.ds_total_min != null ? stats.ds_total_min.toFixed(1) : '-') + '% · '
            + _fcT('avg', 'Avg') + ' ' + (stats.ds_total_avg != null ? stats.ds_total_avg.toFixed(1) : '-') + '% · '
            + _fcT('max', 'Max') + ' ' + (stats.ds_total_max != null ? stats.ds_total_max.toFixed(1) : '-') + '%';
    }
    if (usStats && stats.count > 0) {
        usStats.textContent = _fcT('min', 'Min') + ' ' + (stats.us_total_min != null ? stats.us_total_min.toFixed(1) : '-') + '% · '
            + _fcT('avg', 'Avg') + ' ' + (stats.us_total_avg != null ? stats.us_total_avg.toFixed(1) : '-') + '% · '
            + _fcT('max', 'Max') + ' ' + (stats.us_total_max != null ? stats.us_total_max.toFixed(1) : '-') + '%';
    }
    if (countEl) countEl.textContent = stats.count + ' samples';
}

/* ── SVG Chart Rendering ──
   Renders SVG charts with numeric-only data from our own SQLite storage.
   All values are server-controlled floats (percentages), no user input involved.
   This matches the existing SVG rendering pattern used throughout DOCSight. */
function _fritzCableRenderChart(containerId, samples, totalKey, ownKey) {
    var container = document.getElementById(containerId);
    if (!container) return;

    var width = container.offsetWidth || 600;
    var height = 200;
    var padL = 45, padR = 10, padT = 10, padB = 25;
    var chartW = width - padL - padR;
    var chartH = height - padT - padB;

    var totalVals = samples.map(function(s) { return s[totalKey]; });
    var ownVals = samples.map(function(s) { return s[ownKey]; });
    var timestamps = samples.map(function(s) { return s.timestamp; });

    /* Y scale: 0 to max(totalVals) * 1.2, minimum 5 */
    var yMax = 5;
    for (var i = 0; i < totalVals.length; i++) {
        if (totalVals[i] != null && totalVals[i] > yMax) yMax = totalVals[i];
    }
    yMax = Math.ceil(yMax * 1.2);
    if (yMax < 5) yMax = 5;

    var n = samples.length;

    function xPos(idx) { return padL + (idx / Math.max(n - 1, 1)) * chartW; }
    function yPos(val) { return padT + chartH - (val / yMax) * chartH; }

    /* Build SVG path for a data array */
    function buildPath(vals) {
        var parts = [];
        var started = false;
        for (var j = 0; j < vals.length; j++) {
            if (vals[j] == null) { started = false; continue; }
            var x = xPos(j).toFixed(1);
            var y = yPos(vals[j]).toFixed(1);
            parts.push((started ? 'L' : 'M') + x + ',' + y);
            started = true;
        }
        return parts.join(' ');
    }

    /* Build filled area path */
    function buildFill(vals) {
        var pts = [];
        var firstX = null, lastX = null;
        for (var j = 0; j < vals.length; j++) {
            if (vals[j] == null) continue;
            var x = xPos(j).toFixed(1);
            var y = yPos(vals[j]).toFixed(1);
            if (firstX === null) firstX = x;
            lastX = x;
            pts.push(x + ',' + y);
        }
        if (pts.length < 2) return '';
        var baseline = yPos(0).toFixed(1);
        return 'M' + firstX + ',' + baseline + ' L' + pts.join(' L') + ' L' + lastX + ',' + baseline + ' Z';
    }

    /* Theme-aware colors */
    var cs = getComputedStyle(document.documentElement);
    var gridColor = cs.getPropertyValue('--border-color').trim() || 'rgba(128,128,128,0.2)';
    var textColor = cs.getPropertyValue('--text-secondary').trim() || '#888';
    var totalColor = '#a855f7';
    var ownColor = '#6366f1';

    /* Build SVG via DOM API (numeric-only server data, no user strings) */
    var svgNS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);

    /* Gradient definition */
    var gradId = containerId + '-grad';
    var defs = document.createElementNS(svgNS, 'defs');
    var grad = document.createElementNS(svgNS, 'linearGradient');
    grad.setAttribute('id', gradId);
    grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0');
    grad.setAttribute('x2', '0'); grad.setAttribute('y2', '1');
    var stop1 = document.createElementNS(svgNS, 'stop');
    stop1.setAttribute('offset', '0%'); stop1.setAttribute('stop-color', totalColor); stop1.setAttribute('stop-opacity', '0.25');
    var stop2 = document.createElementNS(svgNS, 'stop');
    stop2.setAttribute('offset', '100%'); stop2.setAttribute('stop-color', totalColor); stop2.setAttribute('stop-opacity', '0.02');
    grad.appendChild(stop1); grad.appendChild(stop2);
    defs.appendChild(grad);
    svg.appendChild(defs);

    /* Y-axis grid lines + labels */
    var steps = 5;
    for (var s = 0; s <= steps; s++) {
        var val = (yMax / steps) * s;
        var yy = yPos(val);
        var gridLine = document.createElementNS(svgNS, 'line');
        gridLine.setAttribute('x1', padL); gridLine.setAttribute('y1', yy);
        gridLine.setAttribute('x2', width - padR); gridLine.setAttribute('y2', yy);
        gridLine.setAttribute('stroke', gridColor); gridLine.setAttribute('stroke-width', '1');
        svg.appendChild(gridLine);
        var yLabel = document.createElementNS(svgNS, 'text');
        yLabel.setAttribute('x', padL - 5); yLabel.setAttribute('y', yy + 3);
        yLabel.setAttribute('text-anchor', 'end'); yLabel.setAttribute('fill', textColor);
        yLabel.setAttribute('font-size', '10');
        yLabel.textContent = val.toFixed(0) + '%';
        svg.appendChild(yLabel);
    }

    /* X-axis labels */
    var xLabelCount = Math.min(6, n);
    for (var xl = 0; xl < xLabelCount; xl++) {
        var idx = Math.round(xl * (n - 1) / Math.max(xLabelCount - 1, 1));
        var ts = timestamps[idx];
        var d = new Date(ts);
        var label = (d.getHours() < 10 ? '0' : '') + d.getHours() + ':' + (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();
        if (_fritzCableRange !== '24h') {
            label = (d.getDate() < 10 ? '0' : '') + d.getDate() + '.' + ((d.getMonth() + 1) < 10 ? '0' : '') + (d.getMonth() + 1) + ' ' + label;
        }
        var xLabel = document.createElementNS(svgNS, 'text');
        xLabel.setAttribute('x', xPos(idx)); xLabel.setAttribute('y', height - 3);
        xLabel.setAttribute('text-anchor', 'middle'); xLabel.setAttribute('fill', textColor);
        xLabel.setAttribute('font-size', '10');
        xLabel.textContent = label;
        svg.appendChild(xLabel);
    }

    /* Total fill area */
    var totalFillPath = buildFill(totalVals);
    if (totalFillPath) {
        var fillEl = document.createElementNS(svgNS, 'path');
        fillEl.setAttribute('d', totalFillPath);
        fillEl.setAttribute('fill', 'url(#' + gradId + ')');
        svg.appendChild(fillEl);
    }

    /* Total line (solid) */
    var totalPathD = buildPath(totalVals);
    var totalLine = document.createElementNS(svgNS, 'path');
    totalLine.setAttribute('d', totalPathD);
    totalLine.setAttribute('fill', 'none');
    totalLine.setAttribute('stroke', totalColor);
    totalLine.setAttribute('stroke-width', '2');
    svg.appendChild(totalLine);

    /* Own line (dashed) */
    var ownPathD = buildPath(ownVals);
    var ownLine = document.createElementNS(svgNS, 'path');
    ownLine.setAttribute('d', ownPathD);
    ownLine.setAttribute('fill', 'none');
    ownLine.setAttribute('stroke', ownColor);
    ownLine.setAttribute('stroke-width', '1.5');
    ownLine.setAttribute('stroke-dasharray', '4,3');
    svg.appendChild(ownLine);

    /* Replace container contents */
    container.textContent = '';
    container.appendChild(svg);
}

window.loadFritzCableData = loadFritzCableData;
