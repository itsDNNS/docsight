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
     * uPlot plugin: fill a band between two series (min/max range for aggregated data).
     */
    function bandPlugin(minSeriesIdx, maxSeriesIdx, color) {
        return {
            hooks: {
                draw: [function(u) {
                    var ctx = u.ctx;
                    var minData = u.data[minSeriesIdx];
                    var maxData = u.data[maxSeriesIdx];
                    if (!minData || !maxData) return;
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
                    ctx.clip();
                    ctx.fillStyle = color;
                    ctx.beginPath();
                    var started = false;
                    for (var i = 0; i < maxData.length; i++) {
                        if (maxData[i] != null && minData[i] != null) {
                            var x = u.valToPos(u.data[0][i], 'x', true);
                            var y = u.valToPos(maxData[i], u.series[minSeriesIdx].scale, true);
                            if (!started) { ctx.moveTo(x, y); started = true; }
                            else ctx.lineTo(x, y);
                        }
                    }
                    for (var i = minData.length - 1; i >= 0; i--) {
                        if (maxData[i] != null && minData[i] != null) {
                            var x = u.valToPos(u.data[0][i], 'x', true);
                            var y = u.valToPos(minData[i], u.series[minSeriesIdx].scale, true);
                            ctx.lineTo(x, y);
                        }
                    }
                    ctx.closePath();
                    ctx.fill();
                    ctx.restore();
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

    function p2(n) { return n < 10 ? '0' + n : '' + n; }

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

        // Format time labels - show date for ranges > 24h
        var rangeSeconds = timestamps[timestamps.length - 1] - timestamps[0];
        var showDate = rangeSeconds > 86400;
        var labels = timestamps.map(function(ts) {
            var d = new Date(ts * 1000);
            var time = p2(d.getHours()) + ':' + p2(d.getMinutes());
            if (showDate) return p2(d.getDate()) + '.' + p2(d.getMonth() + 1) + ' ' + time;
            return time;
        });

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
            zoomable: true,
            tooltipLabelCallback: function(ctx) {
                var val = ctx.parsed.y;
                if (val == null) return '';
                return ctx.dataset.label + ': ' + val.toFixed(1) + ' ms';
            },
            plugins: [lossMarkersPlugin(lossIndices), zoomPlugin()].concat(bandPlugins)
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

        // Build unified timeline with weighted loss counts
        var timeMap = {};
        allTargetData.forEach(function(td) {
            td.samples.forEach(function(s) {
                var sampleCount = sampleCountOf(s);
                if (!timeMap[s.timestamp]) timeMap[s.timestamp] = { total: 0, lossWeight: 0 };
                timeMap[s.timestamp].total += sampleCount;
                timeMap[s.timestamp].lossWeight += lossPctOf(s) * sampleCount;
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
        if (!entry || entry.total === 0) return 'ok';
        var lossPct = entry.lossWeight / entry.total;
        if (lossPct >= 100) return 'down';
        if (lossPct > 0) return 'degraded';
        return 'ok';
    }

    /**
     * Render stats cards (min/max/avg latency, packet loss) from sample data.
     */
    function renderStatsCards(containerId, allTargetData) {
        var container = document.getElementById(containerId);
        if (!container) return;
        container.textContent = '';

        if (!allTargetData || allTargetData.length === 0) return;

        // Prefer exact range stats from the backend when present.
        var statsAvailable = allTargetData.every(function(td) { return !!td.stats; });

        var min = null;
        var max = null;
        var avg = null;
        var p95 = null;
        var totalSamples = 0;
        var totalTimeouts = 0;

        if (statsAvailable) {
            var weightedLatencySum = 0;
            var weightedLatencyCount = 0;
            var p95Values = [];

            allTargetData.forEach(function(td) {
                var stats = td.stats;
                var sampleCount = stats.sample_count || 0;
                var latencyCount = stats.latency_count || 0;
                var packetLoss = stats.packet_loss_pct || 0;
                var timeouts = Math.round(sampleCount * packetLoss / 100);

                totalSamples += sampleCount;
                totalTimeouts += timeouts;
                weightedLatencyCount += latencyCount;
                weightedLatencySum += (stats.avg_latency_ms || 0) * latencyCount;

                if (stats.min_latency_ms != null) {
                    min = min == null ? stats.min_latency_ms : Math.min(min, stats.min_latency_ms);
                }
                if (stats.max_latency_ms != null) {
                    max = max == null ? stats.max_latency_ms : Math.max(max, stats.max_latency_ms);
                }
                if (stats.p95_latency_ms != null) {
                    p95Values.push(stats.p95_latency_ms);
                }
            });

            avg = weightedLatencyCount > 0 ? (weightedLatencySum / weightedLatencyCount) : null;
            if (p95Values.length > 0) {
                p95Values.sort(function(a, b) { return a - b; });
                p95 = p95Values[Math.floor(p95Values.length * 0.95)];
            }
        } else {
            var weightedLatencySum = 0;
            var weightedLatencyCount = 0;
            var p95Values = [];
            allTargetData.forEach(function(td) {
                if (!td.samples) return;
                td.samples.forEach(function(s) {
                    var sampleCount = sampleCountOf(s);
                    totalSamples += sampleCount;
                    totalTimeouts += sampleCount * lossPctOf(s) / 100;
                    if (s.latency_ms != null) {
                        weightedLatencySum += s.latency_ms * sampleCount;
                        weightedLatencyCount += sampleCount;
                        var minLatency = s.min_latency_ms != null ? s.min_latency_ms : s.latency_ms;
                        var maxLatency = s.max_latency_ms != null ? s.max_latency_ms : s.latency_ms;
                        min = min == null ? minLatency : Math.min(min, minLatency);
                        max = max == null ? maxLatency : Math.max(max, maxLatency);
                        p95Values.push(s.p95_latency_ms != null ? s.p95_latency_ms : s.latency_ms);
                    }
                });
            });

            if (weightedLatencyCount > 0) {
                avg = weightedLatencySum / weightedLatencyCount;
            }
            if (p95Values.length > 0) {
                p95Values.sort(function(a, b) { return a - b; });
                p95 = p95Values[Math.floor(p95Values.length * 0.95)];
            }
        }

        if (avg == null || min == null || max == null) return;
        var lossPct = totalSamples > 0 ? (totalTimeouts / totalSamples * 100) : 0;

        var cards = [
            { label: 'Avg Latency', value: avg.toFixed(1) + ' ms', color: avg < 30 ? 'var(--good)' : avg < 100 ? 'var(--warn, orange)' : 'var(--crit)' },
            { label: 'Min', value: min.toFixed(1) + ' ms', color: 'var(--text-muted)' },
            { label: 'Max', value: max.toFixed(1) + ' ms', color: max > 100 ? 'var(--crit)' : 'var(--text-muted)' },
            { label: 'P95', value: p95 != null ? p95.toFixed(1) + ' ms' : '-', color: p95 != null && p95 > 100 ? 'var(--warn, orange)' : 'var(--text-muted)' },
            { label: 'Packet Loss', value: lossPct.toFixed(2) + '%', color: lossPct > 2 ? 'var(--crit)' : lossPct > 0 ? 'var(--warn, orange)' : 'var(--good)' },
            { label: 'Samples', value: totalSamples.toLocaleString(), color: 'var(--text-muted)' }
        ];

        cards.forEach(function(c) {
            var card = document.createElement('div');
            card.className = 'glass';
            card.style.cssText = 'padding:12px 16px; text-align:center;';
            var val = document.createElement('div');
            val.style.cssText = 'font-size:1.3rem; font-weight:700; color:' + c.color + ';';
            val.textContent = c.value;
            var lbl = document.createElement('div');
            lbl.style.cssText = 'font-size:0.75rem; color:var(--text-muted); margin-top:2px;';
            lbl.textContent = c.label;
            card.appendChild(val);
            card.appendChild(lbl);
            container.appendChild(card);
        });
    }

    /**
     * Detect if a host is a private/local IP (gateway, router, LAN device).
     */
    function isPrivateIP(host) {
        if (!host) return false;
        return /^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.)/.test(host);
    }

    /**
     * Render per-target stats comparison table with fault diagnosis.
     * Shows each target's metrics side-by-side so the user can see
     * "Gateway 0% loss, Cloudflare 2% loss = external problem".
     */
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
        var lDiagExt = container.dataset.diagExternal || 'External issue - gateway OK but external targets show packet loss';
        var lDiagInt = container.dataset.diagInternal || 'Internal/ISP issue - gateway also affected';

        // Calculate per-target stats using weighted computation
        var stats = allTargetData.map(function(td, tIdx) {
            var totalSamples = 0;
            var avg = null;
            var p95 = null;
            var loss = 0;

            if (td.stats) {
                totalSamples = td.stats.sample_count || 0;
                avg = td.stats.avg_latency_ms;
                p95 = td.stats.p95_latency_ms;
                loss = td.stats.packet_loss_pct || 0;
            } else {
                var latencies = [];
                var timeouts = 0;

                if (td.samples) {
                    td.samples.forEach(function(s) {
                        var sampleCount = sampleCountOf(s);
                        totalSamples += sampleCount;
                        timeouts += sampleCount * lossPctOf(s) / 100;
                        if (s.latency_ms != null) {
                            latencies.push(s.p95_latency_ms != null ? s.p95_latency_ms : s.latency_ms);
                        }
                    });
                }

                latencies.sort(function(a, b) { return a - b; });
                avg = latencies.length > 0 ? (latencies.reduce(function(a, b) { return a + b; }, 0) / latencies.length) : null;
                p95 = latencies.length > 0 ? latencies[Math.floor(latencies.length * 0.95)] : null;
                loss = totalSamples > 0 ? (timeouts / totalSamples * 100) : 0;
            }
            return {
                label: td.target.label,
                host: td.target.host,
                color: TARGET_COLORS[tIdx % TARGET_COLORS.length],
                avg: avg,
                p95: p95,
                loss: loss,
                samples: totalSamples,
                isLocal: isPrivateIP(td.target.host)
            };
        });

        // Build table
        var table = document.createElement('table');
        table.className = 'data-table';
        table.style.cssText = 'width:100%;';

        var thead = document.createElement('thead');
        var headerRow = document.createElement('tr');
        [lTarget, lAvg, lP95, lLoss, lSamples].forEach(function(text, i) {
            var th = document.createElement('th');
            th.textContent = text;
            if (i >= 3) th.style.textAlign = 'right';
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
            dot.style.cssText = 'display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle;background:' + s.color;
            tdTarget.appendChild(dot);
            var nameSpan = document.createElement('span');
            nameSpan.textContent = s.label;
            tdTarget.appendChild(nameSpan);
            if (s.host) {
                var hostSpan = document.createElement('span');
                hostSpan.style.cssText = 'color:var(--text-muted);font-size:0.8em;margin-left:4px;';
                hostSpan.textContent = '(' + s.host + ')';
                tdTarget.appendChild(hostSpan);
            }

            var tdAvg = document.createElement('td');
            tdAvg.textContent = s.avg != null ? s.avg.toFixed(1) + ' ms' : '-';

            var tdP95 = document.createElement('td');
            tdP95.textContent = s.p95 != null ? s.p95.toFixed(1) + ' ms' : '-';

            // Packet Loss with color
            var tdLoss = document.createElement('td');
            tdLoss.style.cssText = 'text-align:right;font-weight:600;';
            tdLoss.style.color = s.loss > 2 ? 'var(--crit)' : s.loss > 0 ? 'var(--warn, orange)' : 'var(--good)';
            tdLoss.textContent = s.loss.toFixed(2) + '%';

            var tdSamples = document.createElement('td');
            tdSamples.style.cssText = 'text-align:right;color:var(--text-muted);';
            tdSamples.textContent = s.samples.toLocaleString();

            tr.appendChild(tdTarget);
            tr.appendChild(tdAvg);
            tr.appendChild(tdP95);
            tr.appendChild(tdLoss);
            tr.appendChild(tdSamples);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);

        // Fault diagnosis: compare local vs external targets
        var localStats = stats.filter(function(s) { return s.isLocal; });
        var externalStats = stats.filter(function(s) { return !s.isLocal; });

        var hasExternalLoss = externalStats.some(function(s) { return s.loss > 1; });
        var hasLocalLoss = localStats.some(function(s) { return s.loss > 1; });

        if (hasExternalLoss && !hasLocalLoss && localStats.length > 0) {
            var diag = document.createElement('div');
            diag.style.cssText = 'margin-top:8px;padding:8px 12px;border-radius:6px;font-size:0.8rem;font-weight:600;display:flex;align-items:center;gap:6px;background:rgba(239,68,68,0.12);color:var(--crit);';
            var icon = document.createElement('i');
            icon.setAttribute('data-lucide', 'alert-triangle');
            icon.style.cssText = 'width:16px;height:16px;';
            diag.appendChild(icon);
            var txt = document.createElement('span');
            txt.textContent = lDiagExt;
            diag.appendChild(txt);
            container.appendChild(diag);
            if (window.lucide) lucide.createIcons();
        } else if (hasLocalLoss && hasExternalLoss) {
            var diag = document.createElement('div');
            diag.style.cssText = 'margin-top:8px;padding:8px 12px;border-radius:6px;font-size:0.8rem;font-weight:600;display:flex;align-items:center;gap:6px;background:rgba(234,179,8,0.12);color:var(--warn, orange);';
            var icon = document.createElement('i');
            icon.setAttribute('data-lucide', 'wifi-off');
            icon.style.cssText = 'width:16px;height:16px;';
            diag.appendChild(icon);
            var txt = document.createElement('span');
            txt.textContent = lDiagInt;
            diag.appendChild(txt);
            container.appendChild(diag);
            if (window.lucide) lucide.createIcons();
        }
    }

    return {
        renderCombinedChart: renderCombinedChart,
        renderAvailabilityBand: renderAvailabilityBand,
        renderStatsCards: renderStatsCards,
        renderPerTargetStats: renderPerTargetStats,
        TARGET_COLORS: TARGET_COLORS
    };
})();
