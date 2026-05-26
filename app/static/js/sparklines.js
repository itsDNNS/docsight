/**
 * Sparklines — Mini trend charts inside metric cards
 *
 * Renders 24h Canvas sparklines for the 4 core metric cards.
 * Reuses /api/trends data (same endpoint as hero chart).
 */
(function() {
    'use strict';

    var DEFAULT_SPARKS = [
        { id: 'spark-ds-power',  key: 'ds_power_avg',           color: '#a78bfa' },
        { id: 'spark-us-power',  key: 'us_power_avg',           color: '#06b6d4' },
        { id: 'spark-snr',       key: 'ds_snr_avg',             color: '#10b981' },
        { id: 'spark-errors',    key: 'ds_uncorrectable_errors', color: '#f59e0b' }
    ];

    function collectSparks() {
        var sparks = DEFAULT_SPARKS.slice();
        var seen = {};
        sparks.forEach(function(s) { seen[s.id] = true; });
        document.querySelectorAll('canvas.metric-spark[data-spark-key]').forEach(function(canvas) {
            if (!canvas.id || seen[canvas.id]) return;
            sparks.push({
                id: canvas.id,
                key: canvas.dataset.sparkKey,
                color: canvas.dataset.sparkColor || '#10b981'
            });
            seen[canvas.id] = true;
        });
        return sparks;
    }

    function drawSparkline(canvas, values, color) {
        if (!canvas || values.length < 2) return;

        var dpr = window.devicePixelRatio || 1;
        var w = canvas.clientWidth;
        var h = canvas.clientHeight;
        canvas.width = w * dpr;
        canvas.height = h * dpr;

        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        var min = Math.min.apply(null, values);
        var max = Math.max.apply(null, values);
        var range = max - min || 1;
        var pad = 2;
        var plotH = h - pad * 2;
        var stepX = w / (values.length - 1);

        // Build points
        var points = [];
        for (var i = 0; i < values.length; i++) {
            points.push({
                x: i * stepX,
                y: pad + plotH - ((values[i] - min) / range) * plotH
            });
        }

        // Gradient fill
        var grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, color + '33');
        grad.addColorStop(1, color + '00');

        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (var j = 1; j < points.length; j++) {
            ctx.lineTo(points[j].x, points[j].y);
        }
        // Fill area
        ctx.lineTo(points[points.length - 1].x, h);
        ctx.lineTo(points[0].x, h);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        // Stroke line
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (var k = 1; k < points.length; k++) {
            ctx.lineTo(points[k].x, points[k].y);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.lineJoin = 'round';
        ctx.stroke();
    }

    function refresh() {
        fetch('/api/trends')
            .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function(data) {
                if (!Array.isArray(data) || data.length === 0) return;

                // Filter to last 24h
                var now = new Date();
                var cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);
                var filtered = data.filter(function(d) {
                    return new Date(d.timestamp) >= cutoff;
                });
                if (filtered.length < 2) return;

                collectSparks().forEach(function(s) {
                    var canvas = document.getElementById(s.id);
                    if (!canvas) return;
                    var vals = filtered.map(function(d) { return d[s.key]; }).filter(function(v) { return v != null; });
                    if (vals.length >= 2) drawSparkline(canvas, vals, s.color);
                });
            })
            .catch(function(err) {
                console.warn('[Sparklines] Failed to load data:', err);
            });
    }

    window.refreshSparklines = refresh;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', refresh);
    } else {
        refresh();
    }
})();
