(function() {
    'use strict';

    /* Fills the Connection Monitor entry in the Home source row:
       "2/3 OK · 9.3 ms", or why there is no reading yet. */
    var REFRESH_INTERVAL = 10000; // 10s
    var SETTINGS_SECTION = 'mod-docsight_connection_monitor';

    function fmtNumber(value, digits) {
        if (value == null || !isFinite(value)) return '–';
        var fixed = Number(value).toFixed(digits == null ? 1 : digits);
        return fixed.replace(/\.0$/, '');
    }

    function translate(key, fallback) {
        var dict = (typeof window !== 'undefined' && window.T) || (typeof T !== 'undefined' && T) || {};
        return dict[key] || fallback;
    }

    function source() {
        return document.getElementById('cm-source');
    }

    function show(text, state, health) {
        var el = source();
        var value = document.getElementById('cm-source-value');
        if (!el || !value) return;
        el.setAttribute('data-cm-state', state);
        el.setAttribute('data-cm-health', health || 'muted');
        value.textContent = text;
    }

    function openTarget(event) {
        var el = source();
        if (!el || el.getAttribute('data-cm-state') !== 'off') return;
        if (event && event.preventDefault) event.preventDefault();
        window.location.href = docsightUrl('/settings') + '#' + SETTINGS_SECTION;
    }

    function healthFor(down, degraded, complete) {
        if (down.length > 0) return 'crit';
        if (degraded.length > 0) return 'warn';
        if (!complete) return 'muted';
        return 'good';
    }

    function average(values) {
        if (!values.length) return null;
        return values.reduce(function(a, b) { return a + b; }, 0) / values.length;
    }

    function update() {
        if (!source()) return;
        fetch(docsightUrl('/api/connection-monitor/summary'))
            .then(function(r) {
                if (!r.ok) throw new Error('Connection Monitor summary unavailable');
                return r.json();
            })
            .then(function(data) {
                var enabled = Object.values(data || {}).filter(function(t) { return t && t.enabled; });
                var observed = enabled.filter(function(t) {
                    return t.sample_count > 0 && t.packet_loss_pct != null;
                });
                // The summary is empty when the monitor is switched off.
                if (enabled.length === 0) {
                    show(translate('cm_card_off', 'Off') + ' · ' + translate('cm_card_off_hint', 'Turn on in Settings'), 'off');
                    return;
                }
                if (observed.length === 0) {
                    show(translate('cm_card_starting', 'Starting') + ' · ' + translate('cm_card_starting_hint', 'Collecting first measurements…'), 'starting');
                    return;
                }
                var ok = observed.filter(function(t) { return t.packet_loss_pct === 0; });
                var degraded = observed.filter(function(t) { return t.packet_loss_pct > 0 && t.packet_loss_pct < 100; });
                var down = observed.filter(function(t) { return t.packet_loss_pct >= 100; });
                var latency = average(observed
                    .map(function(t) { return t.avg_latency_ms != null ? Number(t.avg_latency_ms) : NaN; })
                    .filter(function(v) { return isFinite(v); }));
                var loss = average(observed.map(function(t) { return Number(t.packet_loss_pct); }).filter(function(v) { return isFinite(v); }));

                var parts = [ok.length + '/' + enabled.length + ' OK'];
                if (latency != null) parts.push(fmtNumber(latency, 1) + ' ms');
                if (loss) parts.push(fmtNumber(loss, 1) + '% ' + translate('packet_loss', 'Packet Loss'));
                show(parts.join(' · '), 'active', healthFor(down, degraded, observed.length === enabled.length));
            })
            .catch(function() { show('–', 'unknown'); });
    }

    function start() {
        // The Home section is re-rendered on refresh, so listen on the document.
        document.addEventListener('click', function(event) {
            var target = event.target && event.target.closest ? event.target.closest('#cm-source') : null;
            if (target) openTarget(event);
        });
        update();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
    setInterval(update, REFRESH_INTERVAL);
})();
