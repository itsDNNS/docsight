/* ═══ DOCSight Chart Engine ═══ */
/* uPlot rendering with DOCSIS threshold zones, zoom modal, and shared chart registry */

/* ── Shared State ── */
var charts = {};
var _tempOverlayVisible = true;
var currentView = 'live';

/* ── Shared Helpers ── */
function fmtK(v) {
    if (v == null) return '';
    var abs = Math.abs(v);
    if (abs >= 1000000) {
        var m = v / 1000000;
        return (m % 1 === 0 ? m.toFixed(0) : m.toFixed(1)) + 'M';
    }
    if (abs >= 1000) {
        var k = v / 1000;
        return (k % 1 === 0 ? k.toFixed(0) : k.toFixed(1)) + 'k';
    }
    return '' + v;
}
function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate());
}
function pad(n) { return n < 10 ? '0' + n : '' + n; }
function formatDateDE(str) {
    var p = str.split('-');
    return p[2] + '.' + p[1] + '.' + p[0];
}

/* ── DOCSIS Threshold Definitions ── */
var DS_POWER_THRESHOLDS = [
    {value: -4, fill: false, lineColor: 'rgba(76,175,80,0.5)'},
    {value: 13, fill: false, lineColor: 'rgba(76,175,80,0.5)'},
    {value: -8, fill: false, lineColor: 'rgba(255,152,0,0.5)'},
    {value: 20, fill: false, lineColor: 'rgba(255,152,0,0.5)'},
    {value: -15, fill: false, lineColor: 'rgba(244,67,54,0.4)'},
    {value: 25, fill: false, lineColor: 'rgba(244,67,54,0.4)'},
    {yMin: -18, yMax: 28}
];
var DS_SNR_THRESHOLDS = [
    {value: 33, fill: false, lineColor: 'rgba(76,175,80,0.5)'},
    {value: 29, fill: false, lineColor: 'rgba(255,152,0,0.5)'},
    {value: 25, fill: false, lineColor: 'rgba(244,67,54,0.4)'},
    {yMin: 20, yMax: 50}
];
var US_POWER_THRESHOLDS = [
    {value: 41, fill: false, lineColor: 'rgba(76,175,80,0.5)'},
    {value: 47, fill: false, lineColor: 'rgba(76,175,80,0.5)'},
    {value: 35, fill: false, lineColor: 'rgba(255,152,0,0.5)'},
    {value: 53, fill: false, lineColor: 'rgba(255,152,0,0.5)'},
    {value: 20, fill: false, lineColor: 'rgba(244,67,54,0.4)'},
    {value: 60, fill: false, lineColor: 'rgba(244,67,54,0.4)'},
    {yMin: 17, yMax: 63}
];

/* ── Zone Plugin (uPlot hooks) ── */
function zonesPlugin(zones) {
    if (!zones) return {};
    return {
        hooks: {
            drawAxes: [function(u) {
                var ctx = u.ctx;
                var left = u.bbox.left;
                var top = u.bbox.top;
                var width = u.bbox.width;
                var height = u.bbox.height;
                ctx.save();
                ctx.beginPath();
                ctx.rect(left, top, width, height);
                ctx.clip();
                var drawn = {};
                var dpr = window.devicePixelRatio || 1;
                zones.forEach(function(z) {
                    if (z.yMin !== undefined) return; /* skip metadata entries */
                    if (z.fill !== false) {
                        var ztop = u.valToPos(z.max, 'y', true);
                        var zbottom = u.valToPos(z.min, 'y', true);
                        ctx.fillStyle = z.color;
                        ctx.fillRect(left, ztop, width, zbottom - ztop);
                    }
                    var lineColor = z.lineColor || z.color.replace(/[\d.]+\)$/, '0.7)');
                    var vals = z.fill === false ? [z.value] : [z.min, z.max];
                    vals.forEach(function(val) {
                        if (val === undefined || drawn[val]) return;
                        drawn[val] = true;
                        var py = u.valToPos(val, 'y', true);
                        ctx.beginPath();
                        ctx.setLineDash([6 * dpr, 4 * dpr]);
                        ctx.strokeStyle = lineColor;
                        ctx.lineWidth = 1 * dpr;
                        ctx.moveTo(left, py);
                        ctx.lineTo(left + width, py);
                        ctx.stroke();
                    });
                });
                ctx.restore();
            }]
        }
    };
}

/* ── Tooltip Plugin ── */
function tooltipPlugin(labels, tooltipLabelCallback) {
    var tooltip;
    function init(u) {
        tooltip = document.createElement('div');
        tooltip.className = 'uplot-tooltip';
        tooltip.style.display = 'none';
        u.over.appendChild(tooltip);
    }
    function buildLine(color, text) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;';
        var marker = document.createElement('span');
        marker.style.cssText = 'width:10px;height:3px;display:inline-block;border-radius:1px;background:' + color;
        var label = document.createElement('span');
        label.textContent = text;
        row.appendChild(marker);
        row.appendChild(label);
        return row;
    }
    function setCursor(u) {
        var idx = u.cursor.idx;
        if (idx == null) {
            tooltip.style.display = 'none';
            return;
        }
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        tooltip.textContent = '';
        var header = document.createElement('div');
        header.style.cssText = 'font-weight:600;margin-bottom:4px;';
        header.textContent = labels[idx] || '';
        tooltip.appendChild(header);
        for (var i = 1; i < u.series.length; i++) {
            var s = u.series[i];
            if (!s.show) continue;
            var val = u.data[i][idx];
            if (val == null) continue;
            var color = s._stroke || s.stroke;
            if (typeof color === 'function') color = color(u, i);
            var text;
            if (tooltipLabelCallback) {
                text = tooltipLabelCallback({
                    raw: val,
                    parsed: {y: val},
                    dataset: {label: s.label, yAxisID: s._docsightAxisID},
                    dataIndex: idx
                });
            } else {
                text = s.label + ': ' + (typeof val === 'number' ? (val === Math.floor(val) && Math.abs(val) >= 1000 ? fmtK(val) : val.toFixed(2)) : val);
            }
            tooltip.appendChild(buildLine(color, text));
        }
        tooltip.style.display = 'block';
        tooltip.style.background = isDark ? '#16213e' : '#fff';
        tooltip.style.color = isDark ? '#888' : '#666';
        tooltip.style.border = '1px solid ' + (isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)');

        var left = u.cursor.left;
        var top = u.cursor.top;
        var tw = tooltip.offsetWidth;
        var th = tooltip.offsetHeight;
        var plotW = u.over.offsetWidth;
        var plotH = u.over.offsetHeight;
        var x = left + 12;
        var y = top - th - 8;
        if (x + tw > plotW) x = left - tw - 12;
        if (y < 0) y = top + 12;
        if (y + th > plotH) y = plotH - th - 4;
        tooltip.style.left = x + 'px';
        tooltip.style.top = y + 'px';
    }
    return {
        hooks: {
            init: [init],
            setCursor: [setCursor]
        }
    };
}

/* ── Helper: prepare uPlot container from canvas/div element ── */
function prepareContainer(canvasId) {
    var el = document.getElementById(canvasId);
    if (!el) return null;
    var container;
    if (el.tagName === 'CANVAS') {
        container = document.createElement('div');
        container.id = canvasId;
        container.style.width = '100%';
        el.parentNode.replaceChild(container, el);
    } else {
        container = el;
        container.textContent = '';
        container.style.width = '100%';
    }
    return container;
}

/* ── Render Chart ── */
function renderChart(canvasId, labels, datasets, type, zones, opts) {
    var existing = charts[canvasId];
    // Save zoom state before potential destroy — restore after recreate
    var savedZoom = existing && existing._zoomRange ? existing._zoomRange : null;

    if (existing) { existing.destroy(); delete charts[canvasId]; }
    var container = prepareContainer(canvasId);
    if (!container) return;

    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
    var textColor = isDark ? '#888' : '#666';
    var isBar = type === 'bar';
    var n = labels.length;

    /* Build columnar data: [xIndices, series1, series2, ...] */
    var xData = [];
    for (var xi = 0; xi < n; xi++) xData.push(xi);
    var uData = [xData];
    var allDatasets = datasets.slice();

    /* Temperature overlay */
    var tempData = opts && opts.tempData && _tempOverlayVisible ? opts.tempData : null;
    var hasTemp = tempData && tempData.some(function(v) { return v !== null; }) && !isBar;

    allDatasets.forEach(function(ds) { uData.push(ds.data); });
    if (hasTemp) uData.push(tempData);

    /* Series config */
    var uSeries = [{ label: 'X', value: function(u, v) { return labels[v] || ''; } }];

    /* Determine bar path renderer */
    var barPaths = isBar ? uPlot.paths.bars({size: [0.7, 50], gap: 1}) : null;

    allDatasets.forEach(function(ds) {
        var showPoints = ds.showPoints;
        if (showPoints === undefined) showPoints = n <= 30 && !isBar;
        var s = {
            label: ds.label,
            stroke: ds.color || 'rgba(168,85,247,0.9)',
            width: isBar ? 0 : 2,
            fill: isBar ? (ds.color || '#a855f7') + 'cc' : (ds.fill || undefined),
            points: { show: showPoints, size: ds.pointSize || 6 },
            spanGaps: ds.spanGaps !== undefined ? ds.spanGaps : false
        };
        if (isBar) {
            s.paths = barPaths;
            s.points = { show: false };
        }
        if (ds.stepped) {
            s.paths = uPlot.paths.stepped({ align: -1 });
            s.width = 2;
        }
        if (ds.dashed) {
            s.dash = [5, 5];
        }
        uSeries.push(s);
    });

    if (hasTemp) {
        var tempSeries = {
            label: T.temperature || 'Temperature',
            stroke: 'rgba(249,115,22,0.7)',
            width: 1.5,
            dash: [5, 3],
            scale: 'temp',
            points: { show: false },
            spanGaps: true
        };
        tempSeries._docsightAxisID = 'y-temp';
        uSeries.push(tempSeries);
    }

    /* Tooltip callback */
    var tooltipLabelCallback = null;
    if (opts && opts.tooltipLabelCallback) {
        tooltipLabelCallback = opts.tooltipLabelCallback;
    } else if (hasTemp) {
        tooltipLabelCallback = function(ctx) {
            var val = ctx.parsed.y;
            if (val == null) return '';
            if (ctx.dataset.yAxisID === 'y-temp') return ctx.dataset.label + ': ' + val.toFixed(1) + ' °C';
            return ctx.dataset.label + ': ' + val;
        };
    }

    /* Scales */
    var yRange = [null, null];
    if (zones) {
        var zoneMeta = zones.find(function(z) { return z.yMin !== undefined; });
        if (zoneMeta) {
            yRange = [zoneMeta.yMin, zoneMeta.yMax];
        }
    }
    if (opts && opts.yMin !== undefined) yRange[0] = opts.yMin;
    if (opts && opts.yMax !== undefined) yRange[1] = opts.yMax;

    var zoomable = opts && opts.zoomable;
    var scales = {
        x: { time: false },
        y: {}
    };
    if (zoomable) {
        /* Zoom-aware: auto off so setScale isn't overridden by data range */
        scales.x.auto = false;
        scales.x.range = function(u, dmin, dmax) {
            if (u._zoomRange) return [u._zoomRange.min, u._zoomRange.max];
            return [0, n - 1];
        };
    } else {
        scales.x.range = function() { return [-0.5, n - 0.5]; };
    }
    if (yRange[0] !== null && yRange[1] !== null) {
        scales.y.range = function(u, dmin, dmax) {
            var lo = yRange[0] !== null ? yRange[0] : dmin;
            var hi = yRange[1] !== null ? yRange[1] : dmax;
            if (dmin < lo) lo = dmin;
            if (dmax > hi) hi = dmax;
            return [lo, hi];
        };
    }
    if (hasTemp) {
        scales.temp = {};
    }

    /* Axes — pick evenly spaced label positions */
    var xSplits = [];
    var wantTicks = 6;
    if (n <= wantTicks) {
        for (var li = 0; li < n; li++) xSplits.push(li);
    } else {
        var gap = (n - 1) / (wantTicks - 1);
        for (var ti = 0; ti < wantTicks; ti++) {
            xSplits.push(Math.round(ti * gap));
        }
    }

    var axes = [
        {
            scale: 'x',
            splits: function() { return xSplits; },
            values: function(u, vals) { return vals.map(function(v) { return labels[v] || ''; }); },
            stroke: textColor,
            grid: { show: false },
            ticks: { show: false },
            font: '11px system-ui',
            gap: 4
        },
        {
            scale: 'y',
            stroke: textColor,
            grid: { stroke: gridColor, width: 1 },
            ticks: { stroke: gridColor, width: 1 },
            font: '10px system-ui',
            size: 50,
            gap: 4
        }
    ];

    /* Custom y-axis tick labels (e.g., QAM modulation) */
    if (opts && opts.yTickCallback) {
        var origTickCb = opts.yTickCallback;
        axes[1].values = function(u, vals) {
            return vals.map(function(v) { return origTickCb(v) || ''; });
        };
    }

    /* Auto-format Y-axis with k/M when values are large (error counts) */
    if (!zones && !(opts && opts.yTickCallback)) {
        var maxVal = 0;
        allDatasets.forEach(function(ds) {
            ds.data.forEach(function(v) { if (v != null && Math.abs(v) > maxVal) maxVal = Math.abs(v); });
        });
        if (maxVal >= 1000) {
            axes[1].values = function(u, vals) {
                return vals.map(function(v) { return fmtK(v); });
            };
        }
    }

    /* Custom tick generation (e.g., fixed QAM steps) */
    if (opts && opts.yAfterBuildTicks) {
        var fakeTicks = [];
        opts.yAfterBuildTicks({ ticks: fakeTicks });
        if (fakeTicks.length > 0) {
            axes[1].splits = function() {
                return fakeTicks.map(function(t) { return t.value; });
            };
        }
    }

    /* Temperature axis (right side) */
    if (hasTemp) {
        axes.push({
            scale: 'temp',
            side: 1,
            stroke: 'rgba(249,115,22,0.6)',
            grid: { show: false },
            ticks: { stroke: 'rgba(249,115,22,0.3)', width: 1 },
            font: '10px system-ui',
            size: 40,
            gap: 4,
            values: function(u, vals) { return vals.map(function(v) { return v.toFixed(0) + '°'; }); }
        });
    }

    /* Sync crosshairs for trend charts */
    var isTrendChart = ['chart-ds-power', 'chart-ds-snr', 'chart-us-power', 'chart-errors'].indexOf(canvasId) >= 0;
    var cursor = {
        show: true,
        x: true,
        y: false,
        points: { show: false }
    };
    if (isTrendChart) {
        cursor.sync = { key: 'docsight-trends', setSeries: false };
    }
    if (zoomable) {
        cursor.drag = { x: true, y: false, uni: 10 };
    }
    /* Plugins */
    var plugins = [tooltipPlugin(labels, tooltipLabelCallback)];
    if (zones) plugins.push(zonesPlugin(zones));
    if (opts && opts.plugins) { opts.plugins.forEach(function(p) { plugins.push(p); }); }

    /* Build options */
    var width = container.offsetWidth || 400;
    var height = Math.round(width * 0.55);
    if (height < 180) height = 180;
    if (height > 350) height = 350;

    var uOpts = {
        width: width,
        height: height,
        scales: scales,
        axes: axes,
        series: uSeries,
        cursor: cursor,
        legend: { show: allDatasets.length + (hasTemp ? 1 : 0) > 1, live: false },
        plugins: plugins
    };

    var chart = new uPlot(uOpts, uData, container);
    charts[canvasId] = chart;
    chart._docsightParams = {labels: labels, datasets: datasets, type: type, zones: zones, opts: opts};

    /* Restore zoom state from previous chart instance (survives destroy/recreate) */
    if (savedZoom && zoomable) {
        chart._zoomRange = savedZoom;
        chart.setScale('x', savedZoom);
    }

    /* Responsive resize */
    var resizeObserver = new ResizeObserver(function(entries) {
        var entry = entries[0];
        var w = Math.round(entry.contentRect.width);
        if (w > 0 && Math.abs(w - chart.width) > 5) {
            var h = Math.round(w * 0.55);
            if (h < 180) h = 180;
            if (h > 350) h = 350;
            chart.setSize({width: w, height: h});
        }
    });
    resizeObserver.observe(container);
    chart._docsightResizeObs = resizeObserver;

    /* Patch destroy to cleanup observer */
    var origDestroy = chart.destroy.bind(chart);
    chart.destroy = function() {
        if (chart._docsightResizeObs) { chart._docsightResizeObs.disconnect(); chart._docsightResizeObs = null; }
        origDestroy();
    };
}

/* ── Chart Zoom Modal ── */
var zoomChart = null;

function openChartZoom(canvasId) {
    var src = charts[canvasId];
    if (!src || !src._docsightParams) return;
    var params = src._docsightParams;
    var srcEl = document.getElementById(canvasId);
    var card = srcEl ? srcEl.closest('.chart-card') : null;
    var label = card ? card.querySelector('.chart-label') : null;
    document.getElementById('chart-zoom-title').textContent = label ? label.textContent : '';
    var overlay = document.getElementById('chart-zoom-overlay');
    overlay.classList.add('open');

    setTimeout(function() {
        if (zoomChart) { zoomChart.destroy(); zoomChart = null; }
        var zoomContainer = document.getElementById('chart-zoom-canvas');
        if (!zoomContainer) return;
        zoomContainer.textContent = '';
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
        var textColor = isDark ? '#888' : '#666';
        var isBar = params.type === 'bar';
        var n = params.labels.length;
        var isMulti = params.datasets.length > 1;

        /* Build data */
        var xData = [];
        for (var xi = 0; xi < n; xi++) xData.push(xi);
        var uData = [xData];
        params.datasets.forEach(function(ds) { uData.push(ds.data); });

        var zoomTempData = params.opts && params.opts.tempData && _tempOverlayVisible ? params.opts.tempData : null;
        var zoomHasTemp = zoomTempData && zoomTempData.some(function(v) { return v !== null; }) && !isBar;
        if (zoomHasTemp) uData.push(zoomTempData);

        /* Series */
        var barPaths = isBar ? uPlot.paths.bars({size: [0.7, 50], gap: 1}) : null;
        var uSeries = [{ label: 'X', value: function(u, v) { return params.labels[v] || ''; } }];
        params.datasets.forEach(function(ds) {
            var s = {
                label: ds.label,
                stroke: ds.color || 'rgba(168,85,247,0.9)',
                width: isBar ? 0 : 2,
                fill: isBar ? (ds.color || '#a855f7') + 'cc' : (!isMulti && !isBar ? 'rgba(168,85,247,0.15)' : undefined),
                points: { show: n <= 30 && !isBar, size: isBar ? 0 : (n > 30 ? 4 : 8) },
                spanGaps: ds.spanGaps !== undefined ? ds.spanGaps : false
            };
            if (isBar) { s.paths = barPaths; s.points = { show: false }; }
            if (ds.stepped) { s.paths = uPlot.paths.stepped({ align: -1 }); s.width = 2; }
            if (ds.dashed) { s.dash = [5, 5]; }
            uSeries.push(s);
        });

        if (zoomHasTemp) {
            var ts = {
                label: T.temperature || 'Temperature',
                stroke: 'rgba(249,115,22,0.7)',
                width: 1.5,
                dash: [5, 3],
                scale: 'temp',
                points: { show: n <= 30, size: 4 },
                spanGaps: true
            };
            ts._docsightAxisID = 'y-temp';
            uSeries.push(ts);
        }

        /* Tooltip callback */
        var zoomTooltipCb = null;
        if (params.opts && params.opts.tooltipLabelCallback) {
            zoomTooltipCb = params.opts.tooltipLabelCallback;
        } else if (zoomHasTemp) {
            zoomTooltipCb = function(ctx) {
                var val = ctx.parsed.y;
                if (val == null) return '';
                if (ctx.dataset.yAxisID === 'y-temp') return ctx.dataset.label + ': ' + val.toFixed(1) + ' °C';
                return ctx.dataset.label + ': ' + val;
            };
        }

        /* Scales */
        var yRange = [null, null];
        if (params.zones) {
            var zoneMeta = params.zones.find(function(z) { return z.yMin !== undefined; });
            if (zoneMeta) { yRange = [zoneMeta.yMin, zoneMeta.yMax]; }
        }
        if (params.opts && params.opts.yMin !== undefined) yRange[0] = params.opts.yMin;
        if (params.opts && params.opts.yMax !== undefined) yRange[1] = params.opts.yMax;

        var scales = {
            x: { time: false, range: function() { return [-0.5, n - 0.5]; } },
            y: {}
        };
        if (yRange[0] !== null && yRange[1] !== null) {
            scales.y.range = function(u, dmin, dmax) {
                var lo = yRange[0] !== null ? yRange[0] : dmin;
                var hi = yRange[1] !== null ? yRange[1] : dmax;
                if (dmin < lo) lo = dmin;
                if (dmax > hi) hi = dmax;
                return [lo, hi];
            };
        }
        if (zoomHasTemp) { scales.temp = {}; }

        /* Axes */
        var zLongest = '';
        for (var zi = 0; zi < params.labels.length; zi++) {
            if (params.labels[zi] && params.labels[zi].length > zLongest.length) zLongest = params.labels[zi];
        }
        var zLabelWidth = Math.max(zLongest.length * 7, 60);

        var xTickValues = function(u, splits) {
            var maxTicks = Math.floor(zoomContainer.offsetWidth / zLabelWidth);
            if (maxTicks < 2) maxTicks = 2;
            var step = Math.ceil(n / maxTicks);
            return splits.filter(function(v) { return v >= 0 && v < n && v % step === 0; });
        };
        var axes = [
            {
                scale: 'x',
                space: zLabelWidth,
                splits: function() { var o = []; for (var i = 0; i < n; i++) o.push(i); return o; },
                filter: xTickValues,
                values: function(u, vals) { return vals.map(function(v) { return params.labels[v] || ''; }); },
                stroke: textColor,
                grid: { stroke: gridColor, width: 1 },
                ticks: { stroke: gridColor, width: 1 },
                font: '11px system-ui',
                gap: 4
            },
            {
                scale: 'y',
                stroke: textColor,
                grid: { stroke: gridColor, width: 1 },
                ticks: { stroke: gridColor, width: 1 },
                font: '11px system-ui',
                size: 55,
                gap: 4
            }
        ];
        if (params.opts && params.opts.yTickCallback) {
            var cb = params.opts.yTickCallback;
            axes[1].values = function(u, vals) { return vals.map(function(v) { return cb(v) || ''; }); };
        }
        if (params.opts && params.opts.yAfterBuildTicks) {
            var ft = [];
            params.opts.yAfterBuildTicks({ ticks: ft });
            if (ft.length > 0) {
                axes[1].splits = function() { return ft.map(function(t) { return t.value; }); };
            }
        }
        if (zoomHasTemp) {
            axes.push({
                scale: 'temp', side: 1,
                stroke: 'rgba(249,115,22,0.6)',
                grid: { show: false },
                ticks: { stroke: 'rgba(249,115,22,0.3)', width: 1 },
                font: '11px system-ui',
                size: 45,
                gap: 4,
                values: function(u, vals) { return vals.map(function(v) { return v.toFixed(0) + '°'; }); }
            });
        }

        /* Plugins */
        var plugins = [tooltipPlugin(params.labels, zoomTooltipCb)];
        if (params.zones) plugins.push(zonesPlugin(params.zones));

        var w = zoomContainer.offsetWidth || 800;
        var h = zoomContainer.offsetHeight || 500;
        if (h < 300) h = 300;

        var uOpts = {
            width: w,
            height: h,
            scales: scales,
            axes: axes,
            series: uSeries,
            cursor: { show: true, x: true, y: false, points: { show: false } },
            legend: { show: params.datasets.length > 1 || zoomHasTemp, live: false },
            plugins: plugins
        };

        zoomChart = new uPlot(uOpts, uData, zoomContainer);
    }, 50);
}

function closeChartZoom() {
    document.getElementById('chart-zoom-overlay').classList.remove('open');
    if (zoomChart) { zoomChart.destroy(); zoomChart = null; }
}
