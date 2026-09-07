/**
 * Connection Monitor Charts - PingPlotter-style combined latency view
 * All targets overlaid in one chart with threshold zones and packet loss markers.
 * Uses renderChart() from chart-engine.js with custom loss markers plugin.
 */
/* global renderChart, charts, bandPlugin */
var CMCharts = (function() {
    'use strict';

    var TARGET_COLORS = [
        'rgba(156,163,175,0.9)',  // gray
        'rgba(96,165,250,0.9)',   // blue
        'rgba(251,146,60,0.9)',   // orange
        'rgba(168,85,247,0.9)',   // purple
        'rgba(52,211,153,0.9)',   // teal
        'rgba(251,113,133,0.9)'   // pink
    ];

    /**
     * uPlot plugin: drag-to-zoom on X-axis, double-click to reset.
     * Requires zoomable:true in renderChart opts (disables fixed x-scale range).
     */
    function zoomPlugin() {
        function showResetBtn(u) {
            if (u._resetBtn) { u._resetBtn.style.display = ''; return; }
            var btn = document.createElement('button');
            btn.textContent = '\u2715 Reset Zoom';
            btn.style.cssText = 'position:absolute;top:8px;right:8px;z-index:10;' +
                'font-size:0.7rem;padding:3px 8px;border:1px solid rgba(255,255,255,0.2);' +
                'border-radius:4px;background:rgba(30,30,30,0.85);color:#ccc;cursor:pointer;' +
                'backdrop-filter:blur(4px);transition:opacity 0.15s;';
            btn.onmouseenter = function() { btn.style.color = '#fff'; };
            btn.onmouseleave = function() { btn.style.color = '#ccc'; };
            btn.onclick = function() {
                u._zoomRange = null;
                u.setScale('x', { min: 0, max: u.data[0].length - 1 });
                btn.style.display = 'none';
            };
            u.root.style.position = 'relative';
            u.root.appendChild(btn);
            u._resetBtn = btn;
        }
        function hideResetBtn(u) {
            if (u._resetBtn) u._resetBtn.style.display = 'none';
        }
        return {
            hooks: {
                init: [function(u) {
                    u.over.style.cursor = 'crosshair';
                    // Hint: show drag-to-zoom tooltip on first hover
                    u.over.title = 'Drag to zoom, double-click to reset';
                }],
                ready: [function(u) {
                    u.over.addEventListener('dblclick', function() {
                        u._zoomRange = null;
                        u.setScale('x', { min: 0, max: u.data[0].length - 1 });
                        hideResetBtn(u);
                    });
                }],
                setSelect: [function(u) {
                    var min = u.posToVal(u.select.left, 'x');
                    var max = u.posToVal(u.select.left + u.select.width, 'x');
                    if (max - min > 1) {
                        u._zoomRange = { min: min, max: max };
                        u.setScale('x', u._zoomRange);
                        showResetBtn(u);
                    }
                    u.setSelect({ left: 0, width: 0, top: 0, height: 0 }, false);
                }]
            }
        };
    }

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

    function sampleCountOf(sample) {
        return sample && sample.sample_count ? sample.sample_count : 1;
    }

    function lossPctOf(sample) {
        if (!sample) return 0;
        if (sample.packet_loss_pct != null) return sample.packet_loss_pct;
        var sampleCount = sampleCountOf(sample);
        var timeoutCount = sample.timeout_count != null ? sample.timeout_count : (sample.timeout ? sampleCount : 0);
        return sampleCount > 0 ? (timeoutCount / sampleCount * 100) : 0;
    }

    /**
     * Render combined PingPlotter-style chart with all targets overlaid.
     * @param {string} containerId - DOM element ID
     * @param {Array} allTargetData - [{target: {id, label, host}, samples: [...]}]
     * @param {number|string} range - Selected range in seconds or a normalized range key.
     */
    function renderCombinedChart(containerId, allTargetData, range) {
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

        var rangeSeconds = timestamps[timestamps.length - 1] - timestamps[0];
        var axisRange;
        if (range !== undefined && range !== null) {
            axisRange = /^\d+$/.test(String(range)) ? String(range) + 's' : range;
        } else {
            axisRange = String(Math.max(Math.round(rangeSeconds), 0)) + 's';
        }
        var labels = docsightFormatXAxisLabels(timestamps, axisRange);

        // Build datasets (one per target) and collect loss indices
        var datasets = [];
        var lossSet = {};
        var bandPlugins = [];

        allTargetData.forEach(function(td, tIdx) {
            var sampleMap = {};
            td.samples.forEach(function(s) {
                sampleMap[s.timestamp] = s;
                if (lossPctOf(s) > 0) lossSet[tsIndex[s.timestamp]] = true;
            });
            var data = new Array(timestamps.length);
            var minData = new Array(timestamps.length);
            var maxData = new Array(timestamps.length);
            var hasAggregated = false;
            for (var i = 0; i < timestamps.length; i++) {
                var s = sampleMap[timestamps[i]];
                if (s && s.latency_ms != null) {
                    data[i] = s.latency_ms;
                    minData[i] = s.min_latency_ms;
                    maxData[i] = s.max_latency_ms;
                    if (s.min_latency_ms != null) hasAggregated = true;
                } else {
                    data[i] = null;
                    minData[i] = null;
                    maxData[i] = null;
                }
            }
            var color = TARGET_COLORS[tIdx % TARGET_COLORS.length];
            datasets.push({
                label: td.target.label + (td.target.host ? ' (' + td.target.host + ')' : ''),
                data: data,
                color: color,
                spanGaps: false,
                dashed: hasAggregated ? true : undefined
            });
            if (hasAggregated) {
                datasets.push({ data: minData, color: 'transparent', label: '_min_' + tIdx, show: false });
                datasets.push({ data: maxData, color: 'transparent', label: '_max_' + tIdx, show: false });
                // uPlot series[0] is x-axis, so data indices are offset by +1
                var bandColor = color.replace(/[\d.]+\)$/, '0.12)');
                bandPlugins.push(bandPlugin(datasets.length - 1, datasets.length, bandColor));
            }
        });

        var lossIndices = Object.keys(lossSet).map(Number).sort(function(a, b) { return a - b; });

        // Compute dynamic Y-max from actual data with headroom
        var dataMax = 0;
        datasets.forEach(function(ds) {
            ds.data.forEach(function(v) { if (v != null && v > dataMax) dataMax = v; });
        });
        // 40ms floor ensures green zone is always visible with breathing room.
        // Above 30ms: moderate headroom. Above 100ms: tighter headroom.
        var yMax;
        if (dataMax <= 30) yMax = 40;
        else if (dataMax <= 100) yMax = Math.ceil(dataMax * 1.2);
        else yMax = Math.ceil(dataMax * 1.15);

        // PingPlotter-style threshold zones (vertically scaled backgrounds)
        // lineColor: transparent suppresses the dashed boundary lines
        var zones = [
            { min: 0, max: 30, color: 'rgba(34,197,94,0.12)', lineColor: 'transparent' },
            { min: 30, max: 100, color: 'rgba(234,179,8,0.10)', lineColor: 'transparent' },
            { min: 100, max: 10000, color: 'rgba(239,68,68,0.08)', lineColor: 'transparent' },
            { yMin: 0, yMax: yMax }
        ];

        renderChart(containerId, labels, datasets, 'line', zones, {
            yMin: 0,
            zoomable: true,
            minHeight: 260,
            maxHeight: 440,
            heightRatio: 0.42,
            tooltipLabelCallback: function(ctx) {
                var val = ctx.parsed.y;
                if (val == null) return '';
                return ctx.dataset.label + ': ' + val.toFixed(1) + ' ms';
            },
            plugins: [lossMarkersPlugin(lossIndices), zoomPlugin()].concat(bandPlugins)
        });
    }

    // Keep comparisons tied to individual targets and their measured statistics.
    function renderPerTargetStats(containerId, allTargetData) {
        var container = document.getElementById(containerId);
        if (!container) return;
        container.textContent = '';

        if (!allTargetData || allTargetData.length === 0) return;

        // Read i18n labels from data attributes
        var lTarget = container.dataset.lTarget || 'Target';
        var lAvg = container.dataset.lAvg || 'Avg';
        var lP95 = container.dataset.lP95 || 'P95';
        var lLoss = container.dataset.lLoss || 'Packet Loss';
        var lSamples = container.dataset.lSamples || 'Samples';

        // Use the range-statistics endpoint, not percentiles of chart buckets.
        var stats = allTargetData.map(function(td, tIdx) {
            var measured = td.stats || {};
            return {
                label: td.target.label,
                host: td.target.host,
                color: TARGET_COLORS[tIdx % TARGET_COLORS.length],
                avg: measured.avg_latency_ms,
                p95: measured.p95_latency_ms,
                loss: measured.packet_loss_pct,
                samples: measured.sample_count || 0
            };
        });

        // Build table
        var table = document.createElement('table');
        table.className = 'data-table cm-target-table';

        var thead = document.createElement('thead');
        var headerRow = document.createElement('tr');
        [lTarget, lAvg, lP95, lLoss, lSamples].forEach(function(text, i) {
            var th = document.createElement('th');
            th.textContent = text;
            if (i >= 3) th.className = 'text-right';
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        stats.forEach(function(s) {
            var tr = document.createElement('tr');

            // Target with color dot
            var tdTarget = document.createElement('td');
            var dot = document.createElement('span');
            dot.className = 'cm-target-dot';
            dot.style.background = s.color;
            tdTarget.appendChild(dot);
            var nameSpan = document.createElement('span');
            nameSpan.textContent = s.label;
            tdTarget.appendChild(nameSpan);
            if (s.host) {
                var hostSpan = document.createElement('span');
                hostSpan.className = 'cm-target-host';
                hostSpan.textContent = '(' + s.host + ')';
                tdTarget.appendChild(hostSpan);
            }

            var tdAvg = document.createElement('td');
            tdAvg.dataset.label = lAvg;
            tdAvg.textContent = s.avg != null ? s.avg.toFixed(1) + ' ms' : '-';

            var tdP95 = document.createElement('td');
            tdP95.dataset.label = lP95;
            tdP95.textContent = s.p95 != null ? s.p95.toFixed(1) + ' ms' : '-';

            // Packet Loss with color
            var tdLoss = document.createElement('td');
            tdLoss.className = 'cm-loss-cell';
            tdLoss.dataset.label = lLoss;
            tdLoss.style.color = s.loss == null ? 'var(--muted)' : s.loss > 2 ? 'var(--crit)' : s.loss > 0 ? 'var(--warn, orange)' : 'var(--good)';
            tdLoss.textContent = s.loss != null ? s.loss.toFixed(2) + '%' : '-';

            var tdSamples = document.createElement('td');
            tdSamples.className = 'cm-samples-cell';
            tdSamples.dataset.label = lSamples;
            tdSamples.textContent = s.samples.toLocaleString();

            tr.appendChild(tdTarget);
            tr.appendChild(tdAvg);
            tr.appendChild(tdP95);
            tr.appendChild(tdLoss);
            tr.appendChild(tdSamples);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        var tableWrap = document.createElement('div');
        tableWrap.className = 'cm-table-wrap cm-target-table-wrap';
        tableWrap.appendChild(table);
        container.appendChild(tableWrap);
    }

    return {
        renderCombinedChart: renderCombinedChart,
        renderPerTargetStats: renderPerTargetStats,
        TARGET_COLORS: TARGET_COLORS
    };
})();
