(function() {
    'use strict';

    /* Fills the Connection Monitor summary on Home: the entry in the source
       row ("2/3 OK · 9.3 ms") or, without DOCSIS data, the module card. */
    var REFRESH_INTERVAL = 10000; // 10s
    var LATENCY_RANGE_MAX_MS = 150;
    var BADGES = {good: 'health_good', warn: 'health_marginal', crit: 'health_critical', muted: 'cm_card_partial'};

    function fmtNumber(value) {
        if (value == null || !isFinite(value)) return '–';
        return Number(value).toFixed(1).replace(/\.0$/, '');
    }

    function ms(value, fallback) {
        var number = value == null ? NaN : Number(value);
        return isFinite(number) ? number : fallback;
    }

    function average(values) {
        if (!values.length) return null;
        return values.reduce(function(a, b) { return a + b; }, 0) / values.length;
    }

    function pct(value) {
        if (value == null) return 0;
        return Math.max(0, Math.min(100, value / LATENCY_RANGE_MAX_MS * 100));
    }

    function idle(state, label, hint) {
        return {state: state, health: 'muted', label: label, hint: hint};
    }

    function summarize(data) {
        var enabled = Object.values(data || {}).filter(function(t) { return t && t.enabled; });
        var observed = enabled.filter(function(t) {
            return t.sample_count > 0 && t.packet_loss_pct != null;
        });
        // The summary is empty when the monitor is switched off.
        if (enabled.length === 0) return idle('off', T.cm_card_off, T.cm_card_off_hint);
        if (observed.length === 0) return idle('starting', T.cm_card_starting, T.cm_card_starting_hint);
        var timed = observed.filter(function(t) { return ms(t.avg_latency_ms) != null; });
        function latency(key) {
            return timed.map(function(t) { return ms(t[key], ms(t.avg_latency_ms)); });
        }
        var losses = observed.map(function(t) { return t.packet_loss_pct; });
        var health = 'good';
        if (losses.some(function(loss) { return loss >= 100; })) health = 'crit';
        else if (losses.some(function(loss) { return loss > 0; })) health = 'warn';
        else if (observed.length < enabled.length) health = 'muted';
        return {
            state: 'active',
            health: health,
            ok: losses.filter(function(loss) { return loss === 0; }).length,
            total: enabled.length,
            avg: average(latency('avg_latency_ms')),
            min: timed.length ? Math.min.apply(null, latency('min_latency_ms')) : null,
            max: timed.length ? Math.max.apply(null, latency('max_latency_ms')) : null,
            loss: average(losses.map(Number)),
        };
    }

    function renderSource(s) {
        var text = s.hint ? s.label + ' · ' + s.hint : s.label;
        if (s.state === 'active') {
            var parts = [s.ok + '/' + s.total + ' OK'];
            if (s.avg != null) parts.push(fmtNumber(s.avg) + ' ms');
            if (s.loss) parts.push(fmtNumber(s.loss) + '% ' + T.packet_loss);
            text = parts.join(' · ');
        }
        var el = document.getElementById('cm-source');
        el.setAttribute('data-cm-state', s.state);
        el.setAttribute('data-cm-health', s.health);
        document.getElementById('cm-source-value').textContent = text;
    }

    function appendText(el, text, className) {
        var span = document.createElement('span');
        span.className = className;
        span.textContent = text;
        el.appendChild(span);
    }

    function renderCard(s) {
        var active = s.state === 'active';
        var accent = 'var(--' + s.health + ')';
        var latency = document.getElementById('cm-card-latency');
        var badge = document.getElementById('cm-card-badge');
        var modRow = document.getElementById('cm-card-mod-row');
        var range = document.getElementById('cm-card-range').style;
        var start = pct(s.min);
        var end = pct(s.max);
        document.getElementById('connection-monitor-card').setAttribute('data-cm-state', s.state);
        latency.textContent = fmtNumber(s.avg);
        if (s.avg != null) appendText(latency, 'ms', 'unit');
        latency.style.color = accent;
        document.getElementById('cm-card-avg').textContent = active
            ? T.metric_average_label + ' · ' + s.ok + '/' + s.total + ' OK' : s.hint;
        badge.textContent = active ? T[BADGES[s.health]] : s.label;
        badge.className = 'badge badge-' + (s.state === 'off' ? 'muted' : s.health === 'muted' ? 'info' : s.health);
        modRow.textContent = '';
        if (active) {
            appendText(modRow, T.packet_loss + ' ', 'metric-sub-label');
            appendText(modRow, fmtNumber(s.loss) + '%', 'range');
        }
        range.setProperty('--metric-marker', pct(s.avg).toFixed(1) + '%');
        range.setProperty('--metric-span-start', Math.min(start, end).toFixed(1) + '%');
        range.setProperty('--metric-span-width', Math.abs(end - start).toFixed(1) + '%');
        range.setProperty('--metric-range-accent', accent);
        document.getElementById('cm-card-range-context').textContent = s.min != null && s.max != null
            ? fmtNumber(s.min) + ' – ' + fmtNumber(s.max) + ' ms' : '–';
    }

    function shown() {
        return document.getElementById('cm-source') || document.getElementById('connection-monitor-card');
    }

    function update() {
        if (!shown()) return;
        fetch(docsightUrl('/api/connection-monitor/summary'))
            .then(function(r) {
                if (!r.ok) throw new Error('Connection Monitor summary unavailable');
                return r.json();
            })
            .then(summarize)
            .catch(function() { return idle('unknown', '–', ''); })
            .then(function(s) {
                // A dashboard refresh may have swapped the Home section during the request.
                var el = shown();
                if (el) (el.id === 'cm-source' ? renderSource : renderCard)(s);
            });
    }

    // While the monitor is off, both entries lead to the setting that turns it on.
    function openSettingsIfOff(el) {
        if (el.getAttribute('data-cm-state') !== 'off') return false;
        window.location.href = docsightUrl('/settings') + '#mod-docsight_connection_monitor';
        return true;
    }

    window.openConnectionMonitorCard = function() {
        if (!openSettingsIfOff(document.getElementById('connection-monitor-card'))) switchView('connection-monitor');
    };

    function start() {
        // The Home section is re-rendered on refresh, so listen on the document.
        document.addEventListener('click', function(event) {
            var source = event.target.closest('#cm-source');
            if (source && openSettingsIfOff(source)) event.preventDefault();
        });
        update();
    }

    // Deferred scripts run before DOMContentLoaded; wait for it so later scripts are loaded too.
    if (document.readyState !== 'complete') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
    // Poll only while the summary is on screen; catch up as soon as the tab is visible again.
    function poll() {
        var el = shown();
        if (el && !document.hidden && el.closest('.view.active')) update();
    }
    setInterval(poll, REFRESH_INTERVAL);
    document.addEventListener('visibilitychange', poll);
})();
