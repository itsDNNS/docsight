/* global renderChart, charts, bandPlugin, zoomPlugin */
var BQMChart = (function() {
    'use strict';

    function formatTick(ts) {
        var d = new Date(ts * 1000);
        var day = String(d.getDate()).padStart(2, '0');
        var month = String(d.getMonth() + 1).padStart(2, '0');
        var hours = String(d.getHours()).padStart(2, '0');
        var minutes = String(d.getMinutes()).padStart(2, '0');
        return day + '.' + month + ' ' + hours + ':' + minutes;
    }

    function toUnixSeries(timestamps) {
        return timestamps.map(function(ts) {
            return Math.floor(new Date(ts).getTime() / 1000);
        });
    }

    function bqmLossPlugin(seriesIdx) {
        return {
            hooks: {
                draw: [function(u) {
                    var data = u.data[seriesIdx];
                    if (!data) return;
                    var ctx = u.ctx;
                    var dpr = window.devicePixelRatio || 1;
                    var scaleName = u.series[seriesIdx].scale;
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
                    ctx.clip();
                    ctx.strokeStyle = 'rgba(239,68,68,0.75)';
                    ctx.lineWidth = 1.5 * dpr;
                    for (var i = 0; i < data.length; i++) {
                        var lost = data[i];
                        if (!lost) continue;
                        var x = u.valToPos(u.data[0][i], 'x', true);
                        var top = u.valToPos(lost, scaleName, true);
                        var bottom = u.valToPos(0, scaleName, true);
                        ctx.beginPath();
                        ctx.moveTo(x, bottom);
                        ctx.lineTo(x, top);
                        ctx.stroke();
                    }
                    ctx.restore();
                }]
            }
        };
    }

    function render(container, payload, opts) {
        opts = opts || {};
        var el = typeof container === 'string' ? document.getElementById(container) : container;
        if (!el || !payload || !payload.data) return;

        var timestamps = payload.data.timestamps || [];
        var latencyAvg = payload.data.latency_avg || [];
        var latencyMin = payload.data.latency_min || [];
        var latencyMax = payload.data.latency_max || [];
        var lostPolls = payload.data.lost_polls || [];
        var hasLoss = lostPolls.some(function(v) { return v > 0; });
        var lossMax = hasLoss ? Math.max.apply(null, lostPolls) : 1;
        var xData = toUnixSeries(timestamps);
        var labels = timestamps.map(function(ts) {
            return formatTick(Math.floor(new Date(ts).getTime() / 1000));
        });

        renderChart(el.id, labels, [
            {
                label: (T && T.bqm_chart_avg) || 'Avg Latency',
                data: latencyAvg,
                color: 'rgba(96,165,250,0.95)',
                spanGaps: false,
            },
            {
                label: (T && T.bqm_chart_range) || 'Min/Max Range',
                data: latencyMin,
                color: 'transparent',
                show: false,
            },
            {
                label: (T && T.bqm_chart_range) || 'Min/Max Range',
                data: latencyMax,
                color: 'transparent',
                show: false,
            },
            {
                label: (T && T.bqm_chart_lost_polls) || 'Lost Polls',
                data: lostPolls,
                color: 'rgba(239,68,68,0.9)',
                spanGaps: false,
                scale: 'loss',
                showPoints: false,
            },
        ], 'line', null, {
            xData: xData,
            xValueCallback: formatTick,
            zoomable: true,
            yMin: 0,
            heightRatio: 0.48,
            scales: {
                loss: {
                    range: function(u, dmin, dmax) {
                        var maxVal = Math.max(lossMax, dmax || 0, 1);
                        return [maxVal, 0];
                    },
                },
            },
            axes: [{
                scale: 'loss',
                side: 1,
                stroke: 'rgba(239,68,68,0.7)',
                grid: { show: false },
                ticks: { stroke: 'rgba(239,68,68,0.25)', width: 1 },
                font: '10px system-ui',
                size: 40,
                gap: 4,
                values: function(u, vals) {
                    if (!hasLoss) return vals.map(function() { return ''; });
                    return vals.map(function(v) { return Number(v).toFixed(0); });
                },
            }],
            tooltipLabelCallback: function(ctx) {
                var idx = ctx.dataIndex;
                if (ctx.dataset.label === ((T && T.bqm_chart_lost_polls) || 'Lost Polls')) {
                    return ctx.dataset.label + ': ' + lostPolls[idx];
                }
                return ((T && T.bqm_chart_avg) || 'Avg Latency')
                    + ': ' + latencyAvg[idx].toFixed(2) + ' ms'
                    + ' | min ' + latencyMin[idx].toFixed(2)
                    + ' | max ' + latencyMax[idx].toFixed(2)
                    + ' | loss ' + lostPolls[idx];
            },
            plugins: [
                bandPlugin(2, 3, 'rgba(96,165,250,0.12)'),
                bqmLossPlugin(4),
                zoomPlugin(),
            ],
        });
    }

    function destroy(container) {
        var el = typeof container === 'string' ? document.getElementById(container) : container;
        if (!el || !charts[el.id]) return;
        charts[el.id].destroy();
        delete charts[el.id];
    }

    return {
        render: render,
        destroy: destroy,
    };
})();
