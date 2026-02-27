/* ═══ DOCSight Chart Engine ═══ */
/* Chart.js rendering with DOCSIS threshold zones, zoom modal, and shared chart registry */

/* ── Shared State ── */
var charts = {};
var _tempOverlayVisible = true;

/* ── Zone Plugin ── */
var zonesPlugin = {
    id: 'zones',
    beforeDatasetsDraw: function(chart) {
        var zones = chart._docsightZones;
        if (!zones) return;
        var ctx = chart.ctx;
        var yAxis = chart.scales.y;
        var chartArea = chart.chartArea;
        ctx.save();
        ctx.beginPath();
        ctx.rect(chartArea.left, chartArea.top, chartArea.right - chartArea.left, chartArea.bottom - chartArea.top);
        ctx.clip();
        var drawn = {};
        zones.forEach(function(z) {
            if (z.yMin !== undefined) return; /* skip metadata entries */
            if (z.fill !== false) {
                var top = yAxis.getPixelForValue(z.max);
                var bottom = yAxis.getPixelForValue(z.min);
                ctx.fillStyle = z.color;
                ctx.fillRect(chartArea.left, top, chartArea.right - chartArea.left, bottom - top);
            }
            var lineColor = z.lineColor || z.color.replace(/[\d.]+\)$/, '0.7)');
            var vals = z.fill === false ? [z.value] : [z.min, z.max];
            vals.forEach(function(val) {
                if (val === undefined || drawn[val]) return;
                drawn[val] = true;
                var py = yAxis.getPixelForValue(val);
                ctx.beginPath();
                ctx.setLineDash([6, 4]);
                ctx.strokeStyle = lineColor;
                ctx.lineWidth = 1;
                ctx.moveTo(chartArea.left, py);
                ctx.lineTo(chartArea.right, py);
                ctx.stroke();
            });
        });
        ctx.restore();
    }
};

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

/* ── Render Chart ── */
function renderChart(canvasId, labels, datasets, type, zones, opts) {
    if (charts[canvasId]) charts[canvasId].destroy();
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;
    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
    var textColor = isDark ? '#888' : '#666';

    var chartDatasets = datasets.map(function(ds, idx) {
        var r = {
            label: ds.label, data: ds.data,
            borderColor: type === 'bar' ? ds.color : (ds.color || 'rgba(168,85,247,0.9)'),
            backgroundColor: type === 'bar' ? ds.color + 'cc' : 'transparent',
            borderWidth: type === 'bar' ? 3 : 2,
            tension: type === 'bar' ? 0 : 0.4,
            pointRadius: labels.length > 30 ? 0 : 3,
            fill: false
        };
        if (ds.stepped) { r.stepped = 'before'; r.tension = 0; }
        if (ds.dashed) { r.borderDash = [5, 5]; }
        if (ds.spanGaps !== undefined) { r.spanGaps = ds.spanGaps; }
        return r;
    });

    /* Temperature overlay dataset */
    var tempData = opts && opts.tempData && _tempOverlayVisible ? opts.tempData : null;
    var hasTemp = tempData && tempData.some(function(v) { return v !== null; });
    if (hasTemp && type !== 'bar') {
        chartDatasets.push({
            label: T.temperature || 'Temperature',
            data: tempData,
            borderColor: 'rgba(249,115,22,0.7)',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            borderDash: [5, 3],
            tension: 0.4,
            pointRadius: 0,
            yAxisID: 'y-temp',
            fill: false,
            spanGaps: true
        });
    }

    var hasLegend = chartDatasets.length > 1;
    var legendPos = hasLegend ? 'bottom' : 'top';
    var tooltipCallbacks = {};
    if (opts && opts.tooltipLabelCallback) {
        tooltipCallbacks.label = opts.tooltipLabelCallback;
    } else if (hasTemp) {
        tooltipCallbacks.label = function(context) {
            var val = context.parsed.y;
            if (val == null) return '';
            if (context.dataset.yAxisID === 'y-temp') {
                return context.dataset.label + ': ' + val.toFixed(1) + ' °C';
            }
            return context.dataset.label + ': ' + val;
        };
    }
    var chartConfig = {
        type: type || 'line',
        data: { labels: labels, datasets: chartDatasets },
        options: {
            responsive: true, maintainAspectRatio: true,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { display: hasLegend, position: legendPos, labels: { color: textColor, font: { size: 11 } } },
                tooltip: { backgroundColor: isDark ? '#16213e' : '#fff', titleColor: textColor, bodyColor: textColor, borderColor: gridColor, borderWidth: 1,
                    callbacks: Object.keys(tooltipCallbacks).length > 0 ? tooltipCallbacks : undefined }
            },
            scales: {
                x: { ticks: { color: textColor, font: { size: 10 }, maxRotation: 45 }, grid: { color: gridColor } },
                y: { ticks: { color: textColor, font: { size: 10 }, callback: opts && opts.yTickCallback ? opts.yTickCallback : undefined }, grid: { color: gridColor } }
            }
        },
        plugins: zones ? [zonesPlugin] : []
    };

    /* Secondary temperature Y-axis */
    if (hasTemp && type !== 'bar') {
        chartConfig.options.scales['y-temp'] = {
            type: 'linear', position: 'right',
            title: { display: true, text: '°C', color: 'rgba(249,115,22,0.8)', font: { size: 10 } },
            grid: { display: false },
            ticks: { color: 'rgba(249,115,22,0.6)', font: { size: 10 } }
        };
    }

    if (opts && opts.yMin !== undefined) chartConfig.options.scales.y.min = opts.yMin;
    if (opts && opts.yMax !== undefined) chartConfig.options.scales.y.max = opts.yMax;
    if (opts && opts.yAfterBuildTicks) chartConfig.options.scales.y.afterBuildTicks = opts.yAfterBuildTicks;
    if (zones) {
        var zoneMeta = zones.find(function(z) { return z.yMin !== undefined; });
        if (zoneMeta) {
            chartConfig.options.scales.y.suggestedMin = zoneMeta.yMin;
            chartConfig.options.scales.y.suggestedMax = zoneMeta.yMax;
        }
    }
    charts[canvasId] = new Chart(ctx, chartConfig);
    if (zones) {
        charts[canvasId]._docsightZones = zones;
    }
    /* Store render params so the zoom modal can re-render this chart */
    charts[canvasId]._docsightParams = {labels: labels, datasets: datasets, type: type, zones: zones, opts: opts};
}

/* ── Chart Zoom Modal ── */
var zoomChart = null;

function openChartZoom(canvasId) {
    var src = charts[canvasId];
    if (!src || !src._docsightParams) return;
    var params = src._docsightParams;
    var card = document.getElementById(canvasId).closest('.chart-card');
    var label = card ? card.querySelector('.chart-label') : null;
    document.getElementById('chart-zoom-title').textContent = label ? label.textContent : '';
    var overlay = document.getElementById('chart-zoom-overlay');
    overlay.classList.add('open');
    /* Re-render the chart on the modal canvas (maintainAspectRatio: false to fill) */
    setTimeout(function() {
        if (zoomChart) { zoomChart.destroy(); zoomChart = null; }
        var ctx = document.getElementById('chart-zoom-canvas');
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
        var textColor = isDark ? '#888' : '#666';

        var isMulti = params.datasets.length > 1;
        var chartDatasets = params.datasets.map(function(ds) {
            var lineColor = ds.color || 'rgba(168,85,247,0.9)';
            var r = {
                label: ds.label, data: ds.data,
                borderColor: params.type === 'bar' ? ds.color : lineColor,
                backgroundColor: params.type === 'bar' ? ds.color + 'cc' : (isMulti ? 'transparent' : function(context) {
                    var chart = context.chart;
                    var ctx = chart.ctx;
                    var chartArea = chart.chartArea;
                    if (!chartArea) return 'rgba(168,85,247,0.25)';
                    var gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
                    gradient.addColorStop(0, 'rgba(168,85,247,0.5)');
                    gradient.addColorStop(0.7, 'rgba(168,85,247,0.1)');
                    gradient.addColorStop(1, 'rgba(168,85,247,0)');
                    return gradient;
                }),
                borderWidth: params.type === 'bar' ? 3 : 2,
                tension: params.type === 'bar' ? 0.3 : 0.4,
                pointRadius: params.labels.length > 30 ? 2 : 4,
                fill: isMulti ? false : params.type !== 'bar'
            };
            if (ds.stepped) { r.stepped = 'before'; r.tension = 0; }
            if (ds.dashed) { r.borderDash = [5, 5]; }
            return r;
        });

        /* Temperature overlay in zoom modal */
        var zoomTempData = params.opts && params.opts.tempData && _tempOverlayVisible ? params.opts.tempData : null;
        var zoomHasTemp = zoomTempData && zoomTempData.some(function(v) { return v !== null; });
        if (zoomHasTemp && params.type !== 'bar') {
            chartDatasets.push({
                label: T.temperature || 'Temperature',
                data: zoomTempData,
                borderColor: 'rgba(249,115,22,0.7)',
                backgroundColor: 'transparent',
                borderWidth: 1.5,
                borderDash: [5, 3],
                tension: 0.4,
                pointRadius: params.labels.length > 30 ? 0 : 2,
                yAxisID: 'y-temp',
                fill: false,
                spanGaps: true
            });
        }

        var hasLegend = chartDatasets.length > 1;
        var zoomTooltipCallbacks = {};
        if (params.opts && params.opts.tooltipLabelCallback) {
            zoomTooltipCallbacks.label = params.opts.tooltipLabelCallback;
        } else if (zoomHasTemp) {
            zoomTooltipCallbacks.label = function(context) {
                var val = context.parsed.y;
                if (val == null) return '';
                if (context.dataset.yAxisID === 'y-temp') return context.dataset.label + ': ' + val.toFixed(1) + ' °C';
                return context.dataset.label + ': ' + val;
            };
        }
        var cfg = {
            type: params.type || 'line',
            data: { labels: params.labels, datasets: chartDatasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: hasLegend, position: 'bottom', labels: { color: textColor, font: { size: 12 } } },
                    tooltip: { backgroundColor: isDark ? '#16213e' : '#fff', titleColor: textColor, bodyColor: textColor, borderColor: gridColor, borderWidth: 1,
                        callbacks: Object.keys(zoomTooltipCallbacks).length > 0 ? zoomTooltipCallbacks : undefined }
                },
                scales: {
                    x: { ticks: { color: textColor, font: { size: 11 }, maxRotation: 45 }, grid: { color: gridColor } },
                    y: { ticks: { color: textColor, font: { size: 11 }, callback: params.opts && params.opts.yTickCallback ? params.opts.yTickCallback : undefined }, grid: { color: gridColor } }
                }
            },
            plugins: params.zones ? [zonesPlugin] : []
        };
        if (zoomHasTemp && params.type !== 'bar') {
            cfg.options.scales['y-temp'] = {
                type: 'linear', position: 'right',
                title: { display: true, text: '°C', color: 'rgba(249,115,22,0.8)', font: { size: 11 } },
                grid: { display: false },
                ticks: { color: 'rgba(249,115,22,0.6)', font: { size: 11 } }
            };
        }
        if (params.opts && params.opts.yMin !== undefined) cfg.options.scales.y.min = params.opts.yMin;
        if (params.opts && params.opts.yMax !== undefined) cfg.options.scales.y.max = params.opts.yMax;
        if (params.opts && params.opts.yAfterBuildTicks) cfg.options.scales.y.afterBuildTicks = params.opts.yAfterBuildTicks;
        if (params.zones) {
            var zoneMeta = params.zones.find(function(z) { return z.yMin !== undefined; });
            if (zoneMeta) {
                cfg.options.scales.y.suggestedMin = zoneMeta.yMin;
                cfg.options.scales.y.suggestedMax = zoneMeta.yMax;
            }
        }
        zoomChart = new Chart(ctx, cfg);
        if (params.zones) {
            zoomChart._docsightZones = params.zones;
        }
    }, 50);
}

function closeChartZoom() {
    document.getElementById('chart-zoom-overlay').classList.remove('open');
    if (zoomChart) { zoomChart.destroy(); zoomChart = null; }
}
