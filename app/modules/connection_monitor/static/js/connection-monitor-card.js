(function() {
    'use strict';

    var REFRESH_INTERVAL = 10000; // 10s
    var LATENCY_RANGE_MAX_MS = 150;

    function fmtNumber(value, digits) {
        if (value == null || !isFinite(value)) return '–';
        var fixed = Number(value).toFixed(digits == null ? 1 : digits);
        return fixed.replace(/\.0$/, '');
    }

    function translate(key, fallback) {
        var dict = (typeof window !== 'undefined' && window.T) || (typeof T !== 'undefined' && T) || {};
        return dict[key] || fallback;
    }

    function pct(value, max) {
        if (value == null || !isFinite(value) || max <= 0) return 0;
        return Math.max(0, Math.min(100, value / max * 100));
    }

    function clear(el) {
        if (!el) return;
        el.textContent = '';
    }

    function appendText(el, text, className) {
        if (!el) return null;
        var span = document.createElement('span');
        if (className) span.className = className;
        span.textContent = text;
        el.appendChild(span);
        return span;
    }

    function setText(el, text) {
        if (!el) return;
        el.textContent = text;
    }

    function setEmpty(elements) {
        setText(elements.latency, '–');
        setText(elements.avg, '');
        setText(elements.badge, '–');
        if (elements.badge) elements.badge.className = 'badge badge-info';
        setText(elements.modRow, '');
        setText(elements.rangeContext, '–');
        if (elements.range) {
            elements.range.style.setProperty('--metric-marker', '0%');
            elements.range.style.setProperty('--metric-span-start', '0%');
            elements.range.style.setProperty('--metric-span-width', '0%');
            elements.range.style.setProperty('--metric-range-accent', 'var(--muted)');
        }
    }

    function collectStats(enabled) {
        var latencies = enabled
            .filter(function(t) { return t.avg_latency_ms != null; })
            .map(function(t) { return Number(t.avg_latency_ms); })
            .filter(function(v) { return isFinite(v); });
        var ranges = enabled.map(function(t) {
            var avg = t.avg_latency_ms != null ? Number(t.avg_latency_ms) : null;
            var min = t.min_latency_ms != null ? Number(t.min_latency_ms) : avg;
            var max = t.max_latency_ms != null ? Number(t.max_latency_ms) : avg;
            if (avg == null || !isFinite(avg)) return null;
            return {
                min: isFinite(min) ? min : avg,
                max: isFinite(max) ? max : avg
            };
        }).filter(Boolean);
        var losses = enabled.map(function(t) { return Number(t.packet_loss_pct || 0); }).filter(function(v) { return isFinite(v); });

        var avgLatency = null;
        if (latencies.length > 0) {
            avgLatency = latencies.reduce(function(a, b) { return a + b; }, 0) / latencies.length;
        }
        var minLatency = ranges.length ? Math.min.apply(null, ranges.map(function(r) { return r.min; })) : avgLatency;
        var maxLatency = ranges.length ? Math.max.apply(null, ranges.map(function(r) { return r.max; })) : avgLatency;
        var jitter = null;
        if (ranges.length) {
            jitter = ranges.reduce(function(sum, r) { return sum + Math.max(0, r.max - r.min); }, 0) / ranges.length;
        }
        var packetLoss = losses.length ? losses.reduce(function(a, b) { return a + b; }, 0) / losses.length : 0;

        return {
            avgLatency: avgLatency,
            minLatency: minLatency,
            maxLatency: maxLatency,
            jitter: jitter,
            packetLoss: packetLoss
        };
    }

    function healthFor(enabled, down, degraded) {
        if (down.length > 0) {
            return { key: 'crit', badge: translate('health_critical', 'Critical') };
        }
        if (degraded.length > 0) {
            return { key: 'warn', badge: translate('health_marginal', 'Marginal') };
        }
        return { key: 'good', badge: translate('health_good', 'Good') };
    }

    function updateCard() {
        fetch('/api/connection-monitor/summary')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var elements = {
                    latency: document.getElementById('cm-card-latency') || document.getElementById('cm-card-status'),
                    avg: document.getElementById('cm-card-avg'),
                    badge: document.getElementById('cm-card-badge'),
                    modRow: document.getElementById('cm-card-mod-row') || document.getElementById('cm-card-details'),
                    range: document.getElementById('cm-card-range'),
                    rangeContext: document.getElementById('cm-card-range-context')
                };
                if (!elements.latency) return;

                var targets = Object.values(data || {});
                var enabled = targets.filter(function(t) { return t && t.enabled; });
                if (enabled.length === 0) {
                    setEmpty(elements);
                    return;
                }

                var ok = enabled.filter(function(t) { return (t.packet_loss_pct || 0) === 0; });
                var degraded = enabled.filter(function(t) {
                    var loss = t.packet_loss_pct || 0;
                    return loss > 0 && loss < 100;
                });
                var down = enabled.filter(function(t) { return (t.packet_loss_pct || 0) >= 100; });
                var health = healthFor(enabled, down, degraded);
                var stats = collectStats(enabled);

                if (stats.avgLatency != null) {
                    setText(elements.latency, fmtNumber(stats.avgLatency, 1) + ' ms ' + translate('metric_average_label', 'avg').toLowerCase());
                } else {
                    setText(elements.latency, '–');
                }
                if (elements.latency) elements.latency.style.color = 'var(--' + health.key + ')';

                setText(elements.avg, ok.length + '/' + enabled.length + ' OK');
                setText(elements.badge, health.badge);
                if (elements.badge) elements.badge.className = 'badge badge-' + health.key;

                clear(elements.modRow);
                appendText(elements.modRow, translate('packet_loss', 'Packet Loss') + ' ', 'metric-sub-label');
                appendText(elements.modRow, fmtNumber(stats.packetLoss, 1) + '%', 'range');
                appendText(elements.modRow, ' · ', 'metric-separator');
                appendText(elements.modRow, translate('jitter', 'Jitter') + ' ', 'metric-sub-label');
                appendText(elements.modRow, (stats.jitter == null ? '–' : fmtNumber(stats.jitter, 1) + ' ms'), 'range');

                if (elements.range) {
                    var marker = pct(stats.avgLatency, LATENCY_RANGE_MAX_MS);
                    var start = pct(stats.minLatency, LATENCY_RANGE_MAX_MS);
                    var end = pct(stats.maxLatency, LATENCY_RANGE_MAX_MS);
                    elements.range.style.setProperty('--metric-marker', marker.toFixed(1) + '%');
                    elements.range.style.setProperty('--metric-span-start', Math.min(start, end).toFixed(1) + '%');
                    elements.range.style.setProperty('--metric-span-width', Math.max(0, Math.abs(end - start)).toFixed(1) + '%');
                    elements.range.style.setProperty('--metric-range-accent', 'var(--' + health.key + ')');
                }
                if (elements.rangeContext) {
                    if (stats.minLatency != null && stats.maxLatency != null) {
                        setText(elements.rangeContext, fmtNumber(stats.minLatency, 1) + ' – ' + fmtNumber(stats.maxLatency, 1) + ' ms');
                    } else {
                        setText(elements.rangeContext, '–');
                    }
                }
            })
            .catch(function() {}); // silent on error
    }

    // Initial load + periodic refresh
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', updateCard);
    } else {
        updateCard();
    }
    setInterval(updateCard, REFRESH_INTERVAL);
})();
