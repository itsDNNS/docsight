/**
 * Connection Monitor Charts - wraps chart-engine.js renderChart()
 */
/* global renderChart */
var CMCharts = (function() {
    'use strict';

    function renderLatencyChart(canvasId, samples) {
        if (!samples || samples.length === 0) return;

        var labels = samples.map(function(s) { return new Date(s.timestamp * 1000); });
        var data = samples.map(function(s) { return s.timeout ? null : s.latency_ms; });

        var datasets = [{
            label: 'Latency (ms)',
            data: data,
            borderColor: 'rgba(59, 130, 246, 0.8)',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: true,
            spanGaps: false
        }];

        var zones = [
            { from: 0, to: 30, color: 'rgba(34,197,94,0.08)' },
            { from: 30, to: 100, color: 'rgba(234,179,8,0.08)' },
            { from: 100, to: null, color: 'rgba(239,68,68,0.08)' }
        ];

        renderChart(canvasId, labels, datasets, 'line', zones, {
            scales: {
                y: { beginAtZero: true, title: { display: true, text: 'ms' } }
            }
        });
    }

    function renderLossChart(canvasId, samples, windowMs) {
        if (!samples || samples.length === 0) return;
        windowMs = windowMs || 60000; // 1 minute buckets

        // Bucket samples into time windows
        var buckets = {};
        samples.forEach(function(s) {
            var bucket = Math.floor(s.timestamp * 1000 / windowMs) * windowMs;
            if (!buckets[bucket]) buckets[bucket] = { total: 0, lost: 0 };
            buckets[bucket].total++;
            if (s.timeout) buckets[bucket].lost++;
        });

        var sortedKeys = Object.keys(buckets).sort(function(a, b) { return a - b; });
        var labels = sortedKeys.map(function(k) { return new Date(Number(k)); });
        var data = sortedKeys.map(function(k) {
            var b = buckets[k];
            return b.total > 0 ? (b.lost / b.total * 100) : 0;
        });

        var datasets = [{
            label: 'Packet Loss (%)',
            data: data,
            backgroundColor: data.map(function(v) {
                return v > 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.3)';
            }),
            borderWidth: 0
        }];

        renderChart(canvasId, labels, datasets, 'bar', null, {
            scales: {
                y: { beginAtZero: true, max: 100, title: { display: true, text: '%' } }
            }
        });
    }

    function renderAvailabilityBand(containerId, samples) {
        var container = document.getElementById(containerId);
        if (!container || !samples || samples.length === 0) {
            if (container) container.textContent = '';
            return;
        }

        // Build segments: consecutive ok/timeout blocks
        var segments = [];
        var currentTimeout = samples[0].timeout;
        var segStart = 0;

        for (var i = 1; i < samples.length; i++) {
            if (samples[i].timeout !== currentTimeout) {
                segments.push({ timeout: currentTimeout, start: segStart, end: i });
                currentTimeout = samples[i].timeout;
                segStart = i;
            }
        }
        segments.push({ timeout: currentTimeout, start: segStart, end: samples.length });

        var total = samples.length;

        // Clear container and append DOM nodes (no innerHTML with user content)
        container.textContent = '';
        segments.forEach(function(seg) {
            var pct = ((seg.end - seg.start) / total * 100).toFixed(2);
            var div = document.createElement('div');
            div.style.cssText = 'width:' + pct + '%;background:' + (seg.timeout ? 'var(--crit)' : 'var(--good)') + ';height:100%;';
            div.title = (seg.timeout ? 'Down' : 'OK') + ' (' + pct + '%)';
            container.appendChild(div);
        });
    }

    return {
        renderLatencyChart: renderLatencyChart,
        renderLossChart: renderLossChart,
        renderAvailabilityBand: renderAvailabilityBand
    };
})();
