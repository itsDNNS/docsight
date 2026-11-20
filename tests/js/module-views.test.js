'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const root = path.resolve(__dirname, '../..');

function element() {
    const classes = new Set();
    return {
        style: {}, dataset: {}, innerHTML: '', textContent: '',
        classList: {
            add: name => classes.add(name), remove: name => classes.delete(name),
            contains: name => classes.has(name),
            toggle(name, on) { if (on) classes.add(name); else classes.delete(name); }
        },
        replaceChildren() { this.innerHTML = ''; },
        addEventListener() {}, removeEventListener() {},
        querySelectorAll: () => [], querySelector: () => null,
        setAttribute() {}, getAttribute: () => null,
    };
}

function browser(ids = [], hash = '') {
    const elements = Object.fromEntries(ids.map(id => [id, element()]));
    const listeners = {};
    const timers = new Map();
    let nextTimer = 0;
    let listenerCount = 0;
    const context = {
        document: {
            getElementById: id => elements[id] || null,
            querySelector: () => null,
            querySelectorAll: selector => selector === '.main-content > .view'
                ? Object.entries(elements).filter(([id]) => id.startsWith('view-')).map(([, el]) => el) : [],
            addEventListener() { listenerCount++; },
            documentElement: element(), body: element(), hidden: false,
        },
        location: {hash, pathname: '/docsight/', search: '?lang=en'},
        history: {replaceState(_state, _title, url) { context.location.hash = ''; context.replacedUrl = url; }},
        navigator: {onLine: true},
        localStorage: {getItem: () => null, setItem() {}},
        matchMedia: () => ({matches: false}),
        addEventListener(name, fn) { listenerCount++; listeners[name] = fn; },
        setTimeout(fn) { timers.set(++nextTimer, fn); return nextTimer; },
        clearTimeout(id) { timers.delete(id); },
        setInterval(fn) { timers.set(++nextTimer, fn); return nextTimer; },
        clearInterval(id) { timers.delete(id); },
        lucide: {createIcons() {}}, currentView: 'live', T: {},
        DOCSightBrowserContracts: {parseDashboardBootstrapText: () => ({translations: {}})},
        fetch() { throw new Error('Unexpected fetch'); },
    };
    context.window = context;
    vm.createContext(context);
    run(context, 'app/static/js/trusted-html.js');
    run(context, 'app/static/js/view-state.js');
    return {context, elements, listeners, timers, listenerCount: () => listenerCount};
}

function run(context, file) {
    vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, {filename: file});
}

test('Speedtest rows distinguish missing measurements from measured zero', () => {
    const {context, elements} = browser(['speedtest-tbody']);
    const rows = [];
    context.document.createElement = () => element();
    elements['speedtest-tbody'].appendChild = row => rows.push(row.innerHTML);
    context.escapeHtml = value => String(value);
    context.formatDocsightTime = value => String(value);
    run(context, 'app/modules/speedtest/static/main.js');
    context._speedtestAllData = [
        {id: 1, download_mbps: 100, upload_mbps: 20, ping_ms: null, jitter_ms: null, packet_loss_pct: null},
        {id: 2, download_mbps: 100, upload_mbps: 20, ping_ms: 0, jitter_ms: 0, packet_loss_pct: 0},
    ];
    context.renderSpeedtestRows();
    assert.equal((rows[0].match(/&#8212;/g) || []).length, 3);
    assert.doesNotMatch(rows[0], /null|0%/);
    assert.match(rows[1], /0 ms/);
    assert.match(rows[1], /0%/);
});

test('Speedtest signal detail leaves out power and SNR no channel reported', () => {
    const {context} = browser();
    context.document.createElement = () => ({...element(), children: [], appendChild(child) { this.children.push(child); }});
    run(context, 'app/modules/speedtest/static/main.js');
    const container = context.document.createElement('div');
    context._renderSignalDetail({
        found: true, health: 'good', ds_total: 0, us_total: 0, snapshot_timestamp: '2026-11-18T10:00:00Z',
        ds_power_min: null, ds_power_avg: null, ds_power_max: null, ds_snr_min: null, ds_snr_avg: null,
        us_power_min: null, us_power_avg: null, us_power_max: null,
    }, container);
    const text = container.children.map(item => item.children.map(part => part.textContent).join(': '));
    assert.deepEqual(text, ['Health: Good', 'DS / US: 0 / 0', 'Snapshot: 2026-11-18T10:00:00Z']);
});

test('Speedtest rows name their expand toggle and show the server name', () => {
    const {context, elements} = browser(['speedtest-tbody']);
    const rows = [];
    context.document.createElement = () => element();
    elements['speedtest-tbody'].appendChild = row => rows.push(row.innerHTML);
    context.escapeHtml = value => String(value).replace(/&/g, '&amp;');
    context.formatDocsightTime = value => String(value);
    run(context, 'app/modules/speedtest/static/main.js');
    context._speedtestAllData = [
        {id: 7, server_id: 34567, server_name: '1&1 Versatel - Dusseldorf', download_mbps: 100, upload_mbps: 20},
        {id: 8, server_id: 12345, download_mbps: 100, upload_mbps: 20},
    ];
    context.renderSpeedtestRows();
    assert.match(rows[0], /aria-label="Show signal at this time"/);
    assert.match(rows[0], /aria-expanded="false"/);
    assert.match(rows[0], /aria-controls="st-signal-7"/);
    assert.match(rows[0], /<td class="st-col-server" data-label="Server" title="#34567">1&amp;1 Versatel - Dusseldorf<\/td>/);
    assert.match(rows[1], /<td class="st-col-server" data-label="Server">#12345<\/td>/);
    for (const column of ['time', 'dl', 'ul', 'ping', 'jitter', 'loss']) {
        assert.match(rows[0], new RegExp('<td class="st-col-' + column + '[^"]*" data-label="[^"]+"'));
    }
});

const runRow = id => ({id, download_mbps: id, upload_mbps: 1, ping_ms: 1});
const ranTest = id => `success: Speedtest complete: ${id} / 1 Mbps, 1 ms`;
const ranLong = 'warning: Speedtest is taking longer than expected. Refresh to check.';
const [before, failed] = [[runRow(100)], 'error: Network error'];
// 101 finishes between the click (newest cached: 100) and the queued 102. A 'slow' request answers only at the
// given second, or never, and a 'broken' one then fails; 'throw' fails before it is sent, 500 answers with an
// error. The deadline is at 150 s.
for (const [label, queuedId, first, polls, answerAt, toast, sent, posts] of [
    ['reports the test it queued', 102, before, [[runRow(101), runRow(100)], [runRow(102), runRow(101)]], null,
        ranTest(102), 2, 1],
    ['compares only the first row without a queued id', null, before, [[runRow(100), runRow(101)], [runRow(101)]], null,
        ranTest(101), 2, 1],
    ['waits for a slow answer without sending another poll', 102, before, ['slow'], 100, ranTest(102), 1, 1],
    ['times out once when a poll never gets an answer', 102, before, ['slow'], null, ranLong, 1, 1],
    ['ignores an answer after the deadline', 102, before, ['slow'], 160, ranLong, 1, 1],
    ['stops polling at the deadline', 102, before, Array(30).fill([runRow(101)]), null, ranLong, 24, 1],
    ['starts no test when the first answer comes after the deadline', 102, 'slow', [], 160, ranLong, 0, 0],
    ['ignores a first answer that fails after the deadline', 102, 'broken', [], 160, ranLong, 0, 0],
    ['starts no test when the first request fails', 102, 500, [], null, failed, 0, 0],
    ['ends once when a request throws', 102, 'throw', [], null, failed, 0, 0],
]) {
    test(`Run Speedtest ${label}`, async () => {
        const {context, elements} = browser(['speedtest-run-btn']);
        const toasts = [], timers = [], intervals = [], counts = {sent: 0, posts: 0};
        let now = 0, answer;
        Object.assign(context, {
            docsightUrl: url => url, showToast: (message, type) => toasts.push(type + ': ' + message),
            setTimeout: (fn, ms) => { const timer = {fn, at: now + ms}; timers.push(timer); return timer; },
            clearTimeout: timer => { timer.at = Infinity; },
            setInterval: fn => intervals.push(fn), clearInterval: id => { intervals[id - 1] = () => {}; },
        });
        context.document.createElement = context.document.createTextNode = () => element();
        elements['speedtest-run-btn'].appendChild = () => {};
        const reply = (body, ok = true) => Promise.resolve({ok, json: async () => body});
        context.fetch = (url, options) => {
            if (options && options.method === 'POST') return counts.posts++, reply({success: true, result_id: queuedId});
            const spec = url.endsWith('count=1') ? first : (counts.sent++, polls.shift());
            if (spec === 'throw') throw new TypeError('Failed to fetch');
            const late = spec === 'broken' ? Promise.resolve({json: () => Promise.reject(new SyntaxError('not JSON'))})
                : reply(url.endsWith('count=1') ? before : [runRow(102)]);
            if (['slow', 'broken'].includes(spec)) return new Promise(resolve => { answer = () => resolve(late); });
            return spec === 500 ? reply({error: 'unavailable'}, false) : reply(spec);
        };
        run(context, 'app/modules/speedtest/static/main.js');
        context.runSpeedtest();
        for (; now < 200000; now += 5000) {  // every five seconds the due timers fire
            for (const timer of timers.filter(t => t.at <= now)) { timer.at = Infinity; timer.fn(); }
            intervals.forEach(fn => fn());
            if (answer && now === answerAt * 1000) answer();
            await new Promise(resolve => setImmediate(resolve));
        }
        assert.deepEqual([toasts, counts, elements['speedtest-run-btn'].disabled], [[toast], {sent, posts}, false]);
    });
}

for (const name of ['journal', 'bqm', 'speedtest']) {
    test(`${name} loads on Settings and its hook is safe without dashboard globals`, () => {
        const {context, timers} = browser();
        run(context, `app/modules/${name}/static/main.js`);
        const hook = `init${name[0].toUpperCase()}${name.slice(1)}View`;
        assert.equal(typeof context[hook], 'function');
        context[hook]();
        context[hook]();
        assert.equal(timers.size, 0);
    });
}

for (const hash of ['#journal', '#bqm', '#speedtest', '#unknown?mode=timeline']) {
    test(`unavailable initial ${hash} returns to live and clears the hash`, () => {
        const {context, elements} = browser(['topnav', 'topnav-backdrop', 'theme-toggle-sidebar', 'view-dashboard'], hash);
        context.initJournalView = context.initBqmView = context.initSpeedtestView = () => assert.fail('Unavailable module initialized');
        run(context, 'app/static/js/topnav.js');
        run(context, 'app/static/js/dashboard.js');
        run(context, 'app/static/js/dashboard-routing.js');
        assert.equal(context.location.hash, '');
        assert.equal(context.currentView, 'live');
        assert.equal(elements['view-dashboard'].classList.contains('active'), true);
    });
}

test('routing accepts optional hooks, repeated activation, deactivated views and browser back', () => {
    const {context, elements, listeners} = browser(['topnav', 'topnav-backdrop', 'theme-toggle-sidebar', 'view-dashboard', 'view-speedtest']);
    run(context, 'app/static/js/topnav.js');
    run(context, 'app/static/js/dashboard.js');
    context.switchView('speedtest');
    assert.equal(elements['view-speedtest'].classList.contains('active'), true);
    let calls = 0;
    context.initSpeedtestView = () => calls++;
    context.switchView('speedtest');
    context.switchView('speedtest');
    assert.equal(calls, 2);
    delete elements['view-speedtest'];
    context.location.hash = '#speedtest';
    listeners.hashchange();
    assert.equal(context.currentView, 'live');
    assert.equal(context.location.hash, '');
    assert.equal(calls, 2);
    assert.equal(elements['view-dashboard'].classList.contains('active'), true);
});

test('BQM repeated activation retains one timer and fixed listeners, leaving cancels it', () => {
    const {context, timers, listenerCount} = browser(['view-bqm']);
    context.todayStr = () => '2026-09-05';
    run(context, 'app/modules/bqm/static/main.js');
    context._bqmDatesLoaded = true;
    context.renderBqmCalendar = () => {};
    let loads = 0;
    context.loadBqmLive = () => loads++;
    context.currentView = 'bqm';
    const before = listenerCount();
    for (let i = 0; i < 5; i++) context.initBqmView();
    assert.equal(timers.size, 1);
    assert.equal(listenerCount(), before);
    const [timerId, tick] = timers.entries().next().value;
    timers.delete(timerId);
    const beforeTick = loads;
    tick();
    assert.equal(loads, beforeTick + 1);
    assert.equal(timers.size, 1);
    context.stopBqmLiveRefresh();
    assert.equal(timers.size, 0);
});

test('Journal and Speedtest activation does not rebind listeners or start timers', () => {
    for (const name of ['journal', 'speedtest']) {
        const {context, timers, listenerCount} = browser([`view-${name}`]);
        run(context, `app/modules/${name}/static/main.js`);
        let loads = 0;
        context.loadJournal = context.loadSpeedtestHistory = () => loads++;
        context.loadIncidents = () => {};
        const before = listenerCount();
        const hook = `init${name[0].toUpperCase()}${name.slice(1)}View`;
        for (let i = 0; i < 5; i++) context[hook]();
        assert.equal(loads, 5);
        assert.equal(timers.size, 0);
        assert.equal(listenerCount(), before);
    }
});

test('Evidence retains unavailable status and hint while omitting impossible view actions', () => {
    const {context, elements} = browser(['evidence-items', 'view-journal']);
    run(context, 'app/modules/evidence/static/main.js');
    const items = ['journal', 'bqm', 'speedtest'].map(key => ({
        key, status: 'unavailable', hint_key: 'missing',
        action: key === 'journal' ? {view: 'journal', action: 'add_note'} : {view: key}
    }));
    context._evidenceRenderItems(items);
    const html = elements['evidence-items'].innerHTML;
    assert.match(html, /data-evidence-view="journal"/);
    assert.doesNotMatch(html, /data-evidence-view="(?:bqm|speedtest)"/);
    assert.equal((html.match(/evidence-status-unavailable/g) || []).length, 3);
    assert.equal((html.match(/Review this evidence source/g) || []).length, 3);
    delete elements['view-journal'];
    context._evidenceRenderItems(items);
    const unavailableHtml = elements['evidence-items'].innerHTML;
    assert.doesNotMatch(unavailableHtml, /data-evidence-view="journal"/);
    assert.doesNotMatch(unavailableHtml, /data-evidence-action="add_note"/);
});

test('comparison health labels use the translated state names', () => {
    const {context} = browser();
    context.T = {health_good: 'Gut', 'docsight.comparison.health_unknown': 'Unbekannt'};
    run(context, 'app/modules/comparison/static/main.js');
    assert.equal(context._cmpTopHealth({good: 96, unknown: 4}), 'Gut (96%)');
    assert.equal(context._cmpTopHealth({good: 1, unknown: 3}), 'Unbekannt (75%)');
    assert.equal(context._cmpTopHealth({}), '-');
});

test('evidence status icons ship in the vendored icon subset', () => {
    const {context} = browser();
    run(context, 'app/modules/evidence/static/main.js');
    const bundle = fs.readFileSync(path.join(root, 'app/static/vendor/lucide.min.js'), 'utf8');
    for (const status of ['present', 'stale', 'missing', 'optional', 'not_applicable', 'unavailable', 'something-else']) {
        const icon = context._evidenceStatusIcon(status);
        assert.ok(bundle.includes('"' + icon + '":'), status + ' -> ' + icon);
    }
});

test('comparison fields show local time and send the matching UTC instant', () => {
    const previousTz = process.env.TZ;
    process.env.TZ = 'Europe/Berlin';
    try {
        const {context} = browser();
        run(context, 'app/modules/comparison/static/main.js');
        assert.equal(context._cmpFmtDT(new Date(2026, 2, 1, 15, 30), 0, 0), '2026-03-01T00:00');
        assert.equal(context._cmpToISO('2026-03-01T00:00'), '2026-02-28T23:00:00Z');
        assert.equal(context._cmpToISO('2026-07-01T00:00'), '2026-06-30T22:00:00Z');
        assert.equal(context._cmpToISO(''), '');
        assert.equal(context._cmpToISO('not a date'), '');
    } finally {
        if (previousTz === undefined) delete process.env.TZ;
        else process.env.TZ = previousTz;
    }
});
