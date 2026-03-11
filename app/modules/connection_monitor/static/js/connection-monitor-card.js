(function() {
    'use strict';

    var REFRESH_INTERVAL = 10000; // 10s

    function setStatusSpan(el, text, colorVar) {
        el.textContent = '';
        var span = document.createElement('span');
        span.style.color = colorVar;
        span.textContent = text;
        el.appendChild(span);
    }

    function updateCard() {
        fetch('/api/connection-monitor/summary')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var statusEl = document.getElementById('cm-card-status');
                var detailsEl = document.getElementById('cm-card-details');
                if (!statusEl) return;

                var targets = Object.values(data);
                if (targets.length === 0) {
                    statusEl.textContent = '—';
                    detailsEl.textContent = '';
                    return;
                }

                var enabled = targets.filter(function(t) { return t.enabled; });
                var ok = enabled.filter(function(t) { return (t.packet_loss_pct || 0) === 0; });
                var degraded = enabled.filter(function(t) {
                    var loss = t.packet_loss_pct || 0;
                    return loss > 0 && loss < 100;
                });
                var down = enabled.filter(function(t) { return (t.packet_loss_pct || 0) >= 100; });

                // Status text
                if (down.length > 0) {
                    setStatusSpan(statusEl, down.length + ' Down', 'var(--crit)');
                } else if (degraded.length > 0) {
                    setStatusSpan(statusEl, degraded.length + ' Degraded', 'var(--warn)');
                } else {
                    setStatusSpan(statusEl, ok.length + '/' + enabled.length + ' OK', 'var(--good)');
                }

                // Details: avg latency across all targets
                var latencies = enabled
                    .filter(function(t) { return t.avg_latency_ms != null; })
                    .map(function(t) { return t.avg_latency_ms; });
                if (latencies.length > 0) {
                    var sum = latencies.reduce(function(a, b) { return a + b; }, 0);
                    var avgLatency = (sum / latencies.length).toFixed(1);
                    detailsEl.textContent = avgLatency + ' ms avg';
                } else {
                    detailsEl.textContent = '';
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
