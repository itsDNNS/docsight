/* snapshot-panel.js — the snapshot behind a chart point.
   Clicking a point in a chart opens a side panel (a sheet on phones) with the
   snapshot taken closest to that time: its health and why, the key levels, new
   uncorrectable errors since the snapshot before, and the weakest downstream
   channels. ‹ › step through snapshots; the chart marks the open one. */
(function() {
    'use strict';

    var HEALTH_BADGE = {good: 'badge-good', tolerated: 'badge-tolerated', marginal: 'badge-warn', warning: 'badge-warn', critical: 'badge-crit'};
    var HEALTH_RANK = {critical: 0, marginal: 1, warning: 1, tolerated: 2, good: 3};
    var WEAKEST_COUNT = 4;
    var state = {payload: null, context: {}, opener: null, request: 0};

    function text(key, fallback, values) {
        var value = T[key] || fallback;
        Object.keys(values || {}).forEach(function(name) { value = value.split('{' + name + '}').join(values[name]); });
        return value;
    }

    function el(tag, className, content) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (content !== undefined && content !== null) node.textContent = content;
        return node;
    }

    function num(value, digits) {
        return value === null || value === undefined || isNaN(value) ? '–' : Number(value).toFixed(digits === undefined ? 1 : digits);
    }

    function healthLabel(health) {
        if (health === 'warning') health = 'marginal';
        return T['health_' + health] || health || '';
    }

    function panel() { return document.getElementById('snapshot-panel'); }

    function mark(idx) {
        if (state.context.canvasId && typeof docsightMarkChartPoint === 'function') {
            docsightMarkChartPoint(state.context.canvasId, idx);
        }
    }

    function load(time, step) {
        var request = ++state.request;
        var body = document.getElementById('snapshot-panel-body');
        body.setAttribute('aria-busy', 'true');
        fetch(docsightUrl('/api/snapshots/at?time=' + encodeURIComponent(time) + '&step=' + step))
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(payload) {
                if (request !== state.request) return;
                body.removeAttribute('aria-busy');
                if (!payload) {
                    if (step === 0) renderError();
                    return;
                }
                // Stepping leaves the clicked point; the marker would no longer match.
                if (step !== 0) mark(null);
                state.payload = payload;
                render(payload);
            })
            .catch(function() {
                if (request === state.request) { body.removeAttribute('aria-busy'); renderError(); }
            });
    }

    function renderError() {
        var body = document.getElementById('snapshot-panel-body');
        body.textContent = '';
        body.appendChild(el('p', 'snapshot-panel-message', text('snapshot_error', 'Could not load the snapshot for this point.')));
        document.getElementById('snapshot-panel-foot').hidden = true;
    }

    function kpi(label, value, detail, tone) {
        var item = el('div', 'snapshot-kpi' + (tone ? ' is-' + tone : ''));
        item.appendChild(el('span', 'snapshot-kpi-label', label));
        item.appendChild(el('strong', 'snapshot-kpi-value', value));
        if (detail) item.appendChild(el('span', 'snapshot-kpi-detail', detail));
        return item;
    }

    function weakestChannels(channels) {
        return (channels || []).slice().sort(function(a, b) {
            var rank = (HEALTH_RANK[a.health] !== undefined ? HEALTH_RANK[a.health] : 3) - (HEALTH_RANK[b.health] !== undefined ? HEALTH_RANK[b.health] : 3);
            return rank || (a.snr == null ? 1 : b.snr == null ? -1 : a.snr - b.snr);
        }).slice(0, WEAKEST_COUNT);
    }

    function newErrors(summary, previous) {
        var current = summary.ds_uncorrectable_errors;
        if (current === null || current === undefined) return null;
        if (previous === null || previous === undefined) return null;
        // A counter that dropped was reset by a modem restart; its new value is new errors.
        return current >= previous ? current - previous : current;
    }

    function render(payload) {
        var snapshot = payload.snapshot;
        var summary = snapshot.summary || {};
        var when = formatDocsightTime(snapshot.timestamp, 'datetime');
        var title = document.getElementById('snapshot-panel-title');
        title.textContent = text('snapshot_title', 'Snapshot · {time}', {time: when});
        var badge = document.getElementById('snapshot-panel-health');
        badge.className = 'badge ' + (HEALTH_BADGE[summary.health] || '');
        badge.textContent = healthLabel(summary.health);
        badge.hidden = !summary.health;
        var sub = [];
        if (state.context.source) sub.push(text('snapshot_from_chart', 'From {chart}', {chart: state.context.source}));
        sub.push(text('snapshot_channel_count', '{ds} DS / {us} US channels', {
            ds: (snapshot.ds_channels || []).length, us: (snapshot.us_channels || []).length
        }));
        document.getElementById('snapshot-panel-sub').textContent = sub.join(' · ');
        document.getElementById('snapshot-prev').disabled = !payload.has_previous;
        document.getElementById('snapshot-next').disabled = !payload.has_next;

        var body = document.getElementById('snapshot-panel-body');
        body.textContent = '';
        var kpis = el('div', 'snapshot-kpis');
        kpis.appendChild(kpi(text('snapshot_ds_power', 'DS power'), num(summary.ds_power_avg) + ' dBmV',
            summary.ds_power_min != null ? num(summary.ds_power_min) + ' – ' + num(summary.ds_power_max) : ''));
        kpis.appendChild(kpi(text('snapshot_ds_snr', 'DS SNR'), num(summary.ds_snr_avg) + ' dB',
            summary.ds_snr_min != null ? text('snapshot_min', 'min {value}', {value: num(summary.ds_snr_min)}) : ''));
        kpis.appendChild(kpi(text('snapshot_us_power', 'US power'), num(summary.us_power_avg) + ' dBmV',
            summary.us_power_min != null ? num(summary.us_power_min) + ' – ' + num(summary.us_power_max) : ''));
        var fresh = newErrors(summary, payload.previous_uncorrectable);
        kpis.appendChild(kpi(text('snapshot_new_uncorrectable', 'New uncorrectable'),
            fresh === null ? '–' : '+' + fresh.toLocaleString(),
            fresh === null
                ? (summary.ds_uncorrectable_errors == null ? text('snapshot_not_reported', 'not reported by the modem') : text('snapshot_first', 'first snapshot'))
                : text('snapshot_since_previous', 'since the snapshot before'),
            fresh ? 'warn' : ''));
        body.appendChild(kpis);

        var issues = (summary.health_issues || []).filter(function(issue) { return T['issue_' + issue]; });
        if (summary.health && summary.health !== 'good') {
            var why = el('section', 'snapshot-section');
            why.appendChild(el('h3', 'snapshot-section-title', text('snapshot_why', 'Why {health}', {health: healthLabel(summary.health).toLowerCase()})));
            var list = el('ul', 'snapshot-issues');
            (issues.length ? issues : []).forEach(function(issue) {
                list.appendChild(el('li', 'badge ' + (/critical/.test(issue) ? 'badge-crit' : /tolerated/.test(issue) ? 'badge-tolerated' : 'badge-warn'), T['issue_' + issue]));
            });
            if (!issues.length) list.appendChild(el('li', '', text('snapshot_no_issue_detail', 'No single cause recorded')));
            why.appendChild(list);
            body.appendChild(why);
        }

        var weakest = weakestChannels(snapshot.ds_channels);
        if (weakest.length) {
            var section = el('section', 'snapshot-section');
            section.appendChild(el('h3', 'snapshot-section-title', text('snapshot_weakest', 'Weakest downstream channels')));
            var table = el('table', 'snapshot-channels');
            var head = el('tr');
            [T.ch_abbr || 'Ch', T.frequency || 'Frequency', T.th_power || 'Power', 'SNR', T.mod_abbr || 'Mod.'].forEach(function(label) {
                head.appendChild(el('th', '', label));
            });
            var thead = el('thead');
            thead.appendChild(head);
            table.appendChild(thead);
            var tbody = el('tbody');
            weakest.forEach(function(ch) {
                var row = el('tr');
                row.appendChild(el('td', 'dt-primary', String(ch.channel_id)));
                var freq = String(ch.frequency || '');
                row.appendChild(el('td', '', freq && freq.indexOf('MHz') === -1 ? freq + ' MHz' : freq));
                var power = el('td', 'dt-num', num(ch.power));
                power.setAttribute('data-health', ch.power_health || 'good');
                row.appendChild(power);
                var snr = el('td', 'dt-num', num(ch.snr));
                snr.setAttribute('data-health', ch.snr_health || 'good');
                row.appendChild(snr);
                row.appendChild(el('td', '', String(ch.modulation || '')));
                tbody.appendChild(row);
            });
            table.appendChild(tbody);
            section.appendChild(table);
            body.appendChild(section);
        }

        var openChannel = document.getElementById('snapshot-open-channel');
        openChannel.hidden = !weakest.length;
        if (weakest.length) {
            openChannel.textContent = text('snapshot_open_channel', 'Open channel {id}', {id: weakest[0].channel_id});
            openChannel.dataset.channel = weakest[0].channel_id;
        }
        document.getElementById('snapshot-add-case').hidden = typeof DOCSightCasePicker === 'undefined';
        document.getElementById('snapshot-panel-foot').hidden = false;
    }

    function asText(payload) {
        var snapshot = payload.snapshot;
        var summary = snapshot.summary || {};
        var fresh = newErrors(summary, payload.previous_uncorrectable);
        var lines = [
            text('snapshot_title', 'Snapshot · {time}', {time: formatDocsightTime(snapshot.timestamp, 'datetime')}) + ' (' + healthLabel(summary.health) + ')',
            text('snapshot_ds_power', 'DS power') + ': ' + num(summary.ds_power_avg) + ' dBmV (' + num(summary.ds_power_min) + ' – ' + num(summary.ds_power_max) + ')',
            text('snapshot_ds_snr', 'DS SNR') + ': ' + num(summary.ds_snr_avg) + ' dB (' + text('snapshot_min', 'min {value}', {value: num(summary.ds_snr_min)}) + ')',
            text('snapshot_us_power', 'US power') + ': ' + num(summary.us_power_avg) + ' dBmV (' + num(summary.us_power_min) + ' – ' + num(summary.us_power_max) + ')',
            text('snapshot_new_uncorrectable', 'New uncorrectable') + ': ' + (fresh === null ? '–' : '+' + fresh)
        ];
        (summary.health_issues || []).forEach(function(issue) { if (T['issue_' + issue]) lines.push('- ' + T['issue_' + issue]); });
        return lines.join('\n');
    }

    function open(time, context) {
        var node = panel();
        if (!node) return;
        if (state.context.canvasId && state.context.canvasId !== (context || {}).canvasId) mark(null);
        state.context = context || {};
        state.opener = document.activeElement;
        mark(state.context.index);
        node.hidden = false;
        document.getElementById('snapshot-panel-title').focus();
        load(time, 0);
    }

    function close() {
        var node = panel();
        if (!node || node.hidden) return;
        node.hidden = true;
        mark(null);
        state.request++;
        if (state.opener && state.opener.focus) state.opener.focus();
    }

    function step(direction) {
        if (!state.payload) return;
        load(state.payload.snapshot.timestamp, direction);
    }

    function init() {
        var node = panel();
        if (!node) return;
        document.getElementById('snapshot-close').addEventListener('click', close);
        document.getElementById('snapshot-prev').addEventListener('click', function() { step(-1); });
        document.getElementById('snapshot-next').addEventListener('click', function() { step(1); });
        node.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') { event.stopPropagation(); close(); }
        });
        document.getElementById('snapshot-open-channel').addEventListener('click', function() {
            var id = this.dataset.channel;
            close();
            location.hash = '#channels?mode=timeline&dir=ds&channel=' + encodeURIComponent(id) + '&range=1d';
        });
        document.getElementById('snapshot-add-case').addEventListener('click', function() {
            if (!state.payload || typeof DOCSightCasePicker === 'undefined') return;
            var stamp = state.payload.snapshot.timestamp;
            var when = formatDocsightTime(stamp, 'datetime');
            DOCSightCasePicker.open({
                startDate: stamp.slice(0, 10),
                endDate: stamp.slice(0, 10),
                summary: text('snapshot_case_summary', 'Snapshot of {time}', {time: when}),
                name: text('snapshot_case_name', 'Signal on {time}', {time: when}),
                added: text('snapshot_added_to_case', 'Snapshot day added to “{case}”')
            });
        });
        document.getElementById('snapshot-copy').addEventListener('click', function() {
            if (!state.payload || !navigator.clipboard) return;
            navigator.clipboard.writeText(asText(state.payload)).then(function() {
                if (typeof showToast === 'function') showToast(text('snapshot_copied', 'Snapshot copied'), 'ok');
            });
        });
        // Leaving the view closes the panel; it belongs to the chart that opened it.
        window.addEventListener('hashchange', close);
    }

    window.DOCSightSnapshotPanel = {open: open, close: close, newErrors: newErrors, weakestChannels: weakestChannels};
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
