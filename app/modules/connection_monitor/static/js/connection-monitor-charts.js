/**
 * Connection Monitor Charts - PingPlotter-style combined latency view
 * All targets overlaid in one chart with threshold zones and packet loss markers.
 * Uses renderChart() from chart-engine.js with custom loss markers plugin.
 */
/* global renderChart, charts */
var CMCharts = (function() {
    'use strict';

    var TARGET_COLORS = [
        'rgba(156,163,175,0.9)',  // gray (gateway/local)
        'rgba(96,165,250,0.9)',   // blue
        'rgba(251,146,60,0.9)',   // orange
        'rgba(168,85,247,0.9)',   // purple
        'rgba(52,211,153,0.9)',   // teal
        'rgba(251,113,133,0.9)'   // pink
    ];

    /**
     * uPlot plugin: draw red vertical lines at packet loss indices.
     * Uses 'draw' hook so lines render ON TOP of series (like PingPlotter).
     */
    function lossMarkersPlugin(lossIndices) {
        if (!lossIndices || lossIndices.length === 0) return {};
        return {
            hooks: {
                draw: [function(u) {
                    var ctx = u.ctx;
                    var dpr = window.devicePixelRatio || 1;
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
                    ctx.clip();
                    ctx.strokeStyle = 'rgba(239,68,68,0.7)';
                    ctx.lineWidth = 1.5 * dpr;
                    for (var i = 0; i < lossIndices.length; i++) {
                        var x = u.valToPos(lossIndices[i], 'x', true);
                        if (x >= u.bbox.left && x <= u.bbox.left + u.bbox.width) {
                            ctx.beginPath();
                            ctx.moveTo(x, u.bbox.top);
                            ctx.lineTo(x, u.bbox.top + u.bbox.height);
                            ctx.stroke();
                        }
                    }
                    ctx.restore();
                }]
            }
        };
    }

    function p2(n) { return n < 10 ? '0' + n : '' + n; }

    /**
     * Render combined PingPlotter-style chart with all targets overlaid.
     * @param {string} containerId - DOM element ID
     * @param {Array} allTargetData - [{target: {id, label, host}, samples: [...]}]
     */
    function renderCombinedChart(containerId, allTargetData) {
        if (!allTargetData || allTargetData.length === 0) return;

        // Build unified timeline from all targets' samples
        var timeMap = {};
        allTargetData.forEach(function(td) {
            td.samples.forEach(function(s) { timeMap[s.timestamp] = true; });
        });
        var timestamps = Object.keys(timeMap).map(Number).sort(function(a, b) { return a - b; });
        if (timestamps.length === 0) return;

        // Build index lookup
        var tsIndex = {};
        for (var i = 0; i < timestamps.length; i++) tsIndex[timestamps[i]] = i;

        // Format time labels
        var labels = timestamps.map(function(ts) {
            var d = new Date(ts * 1000);
            return p2(d.getHours()) + ':' + p2(d.getMinutes());
        });

        // Build datasets (one per target) and collect loss indices
        var datasets = [];
        var lossSet = {};

        allTargetData.forEach(function(td, tIdx) {
            var sampleMap = {};
            td.samples.forEach(function(s) {
                sampleMap[s.timestamp] = s;
                if (s.timeout) lossSet[tsIndex[s.timestamp]] = true;
            });

            var data = new Array(timestamps.length);
            for (var i = 0; i < timestamps.length; i++) {
                var s = sampleMap[timestamps[i]];
                data[i] = (s && !s.timeout && s.latency_ms != null) ? s.latency_ms : null;
            }

            datasets.push({
                label: td.target.label + (td.target.host ? ' (' + td.target.host + ')' : ''),
                data: data,
                color: TARGET_COLORS[tIdx % TARGET_COLORS.length],
                spanGaps: false
            });
        });

        var lossIndices = Object.keys(lossSet).map(Number).sort(function(a, b) { return a - b; });

        // PingPlotter-style threshold zones (vertically scaled backgrounds)
        // lineColor: transparent suppresses the dashed boundary lines
        var zones = [
            { min: 0, max: 30, color: 'rgba(34,197,94,0.12)', lineColor: 'transparent' },
            { min: 30, max: 100, color: 'rgba(234,179,8,0.10)', lineColor: 'transparent' },
            { min: 100, max: 10000, color: 'rgba(239,68,68,0.08)', lineColor: 'transparent' },
            { yMin: 0, yMax: 200 }
        ];

        renderChart(containerId, labels, datasets, 'line', zones, {
            yMin: 0,
            tooltipLabelCallback: function(ctx) {
                var val = ctx.parsed.y;
                if (val == null) return '';
                return ctx.dataset.label + ': ' + val.toFixed(1) + ' ms';
            },
            plugins: [lossMarkersPlugin(lossIndices)]
        });
    }

    /**
     * Render combined availability band across all targets.
     * Green = all OK, orange = some loss, red = all down.
     */
    function renderAvailabilityBand(containerId, allTargetData) {
        var container = document.getElementById(containerId);
        if (!container) return;

        if (!allTargetData || allTargetData.length === 0) {
            container.textContent = '';
            return;
        }

        // Build unified timeline with timeout counts
        var timeMap = {};
        allTargetData.forEach(function(td) {
            td.samples.forEach(function(s) {
                if (!timeMap[s.timestamp]) timeMap[s.timestamp] = { total: 0, timeout: 0 };
                timeMap[s.timestamp].total++;
                if (s.timeout) timeMap[s.timestamp].timeout++;
            });
        });
        var timestamps = Object.keys(timeMap).map(Number).sort(function(a, b) { return a - b; });
        if (timestamps.length === 0) { container.textContent = ''; return; }

        // Build segments of consecutive same-state
        var segments = [];
        var prevState = stateOf(timeMap[timestamps[0]]);
        var segStart = 0;

        for (var i = 1; i < timestamps.length; i++) {
            var state = stateOf(timeMap[timestamps[i]]);
            if (state !== prevState) {
                segments.push({ state: prevState, start: segStart, end: i });
                prevState = state;
                segStart = i;
            }
        }
        segments.push({ state: prevState, start: segStart, end: timestamps.length });

        container.textContent = '';
        var total = timestamps.length;
        segments.forEach(function(seg) {
            var pct = ((seg.end - seg.start) / total * 100).toFixed(2);
            var div = document.createElement('div');
            var bg = seg.state === 'down' ? 'var(--crit)' : seg.state === 'degraded' ? 'var(--warn, orange)' : 'var(--good)';
            div.style.cssText = 'width:' + pct + '%;background:' + bg + ';height:100%;';
            div.title = seg.state + ' (' + pct + '%)';
            container.appendChild(div);
        });
    }

    function stateOf(entry) {
        if (!entry) return 'ok';
        if (entry.timeout === entry.total) return 'down';
        if (entry.timeout > 0) return 'degraded';
        return 'ok';
    }

    return {
        renderCombinedChart: renderCombinedChart,
        renderAvailabilityBand: renderAvailabilityBand,
        TARGET_COLORS: TARGET_COLORS
    };
})();
