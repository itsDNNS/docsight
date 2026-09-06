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
    return {context, elements, listeners, timers, listenerCount: () => listenerCount};
}

function run(context, file) {
    vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, {filename: file});
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
        const {context, elements} = browser(['sidebar', 'sidebar-backdrop', 'theme-toggle-sidebar', 'view-dashboard'], hash);
        context.initJournalView = context.initBqmView = context.initSpeedtestView = () => assert.fail('Unavailable module initialized');
        run(context, 'app/static/js/dashboard.js');
        run(context, 'app/static/js/dashboard-routing.js');
        assert.equal(context.location.hash, '');
        assert.equal(context.currentView, 'live');
        assert.equal(elements['view-dashboard'].classList.contains('active'), true);
    });
}

test('routing accepts optional hooks, repeated activation, deactivated views and browser back', () => {
    const {context, elements, listeners} = browser(['sidebar', 'sidebar-backdrop', 'theme-toggle-sidebar', 'view-dashboard', 'view-speedtest']);
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
