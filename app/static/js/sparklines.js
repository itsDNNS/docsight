/**
 * Sparklines — Mini trend charts inside metric cards
 *
 * Renders 24h Canvas sparklines for the 4 core metric cards.
 * Shares the compact Hero series; error/family/module data follows separately.
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

    var signalKeys = ['ds_power_avg', 'us_power_avg', 'ds_snr_avg'];
    var cachedSignals = [];
    var cachedLegacy = [];
    var legacyGeneration = -1;
    var legacyPromise = null;
    var requestId = 0;

    function render(data, signals) {
        var cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000);
        var filtered = data.filter(function(row) { return new Date(row.timestamp) >= cutoff; });
        collectSparks().forEach(function(s) {
            if ((signalKeys.indexOf(s.key) !== -1) !== signals) return;
            var canvas = document.getElementById(s.id);
            if (!canvas) return;
            var values = filtered.map(function(row) { return row[s.key]; }).filter(function(v) { return v != null; });
            canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
            if (values.length >= 2) drawSparkline(canvas, values, s.color);
        });
    }

    function getLegacy(generation) {
        if (legacyGeneration === generation && legacyPromise) return legacyPromise;
        legacyGeneration = generation;
        var promise = fetch(docsightUrl('/api/trends?range=1d'))
            .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function(rows) {
                if (!Array.isArray(rows)) throw new Error('Invalid trend series');
                return rows;
            }).catch(function(error) {
                if (legacyPromise === promise) legacyPromise = null;
                throw error;
            });
        legacyPromise = promise;
        return promise;
    }

    function refresh(generation) {
        var series = window.DOCSightSignalSeries;
        if (generation == null) generation = series.generation();
        var id = ++requestId;
        function current() { return id === requestId && series.isCurrent(generation); }
        // The HTML swap replaces canvases. Restore the last successful sparse
        // data while fetching, including module rows at different timestamps.
        render(cachedSignals, true);
        render(cachedLegacy, false);
        return series.get().then(function(rows) {
            if (!current()) return;
            cachedSignals = rows;
            render(rows, true);
        }).catch(function(error) {
            if (current()) console.warn('[Sparklines] Failed to load signals:', error);
        }).then(function() {
            // Allow the signal render to paint before starting legacy CPU work.
            // Failure also reaches this path so errors/modules can recover alone.
            return new Promise(function(resolve) {
                requestAnimationFrame(function() { setTimeout(resolve, 0); });
            });
        }).then(function() {
            if (!current()) return;
            return getLegacy(generation).then(function(rows) {
                if (!current()) return;
                cachedLegacy = rows;
                render(rows, false);
            }).catch(function(error) {
                if (current()) console.warn('[Sparklines] Failed to load data:', error);
            });
        });
    }

    window.refreshSparklines = function(generation) {
        return refresh(generation == null ? window.DOCSightSignalSeries.refresh() : generation);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { refresh(); });
    } else {
        refresh();
    }
})();
