'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const run = (c, file) => vm.runInContext(fs.readFileSync(file, 'utf8'), c);

// Stands in for the shared empty-state component (tested in empty-state.test.js).
const emptyState = {
    show(el, options) { if (el) Object.assign(el, {hidden: false, empty: {kind: 'show', ...options}}); },
    showRange(el, options) { if (el) Object.assign(el, {hidden: false, empty: {kind: 'range', ...options}}); },
    showError(el, options) { if (el) Object.assign(el, {hidden: false, empty: {kind: 'error', ...options}}); },
    hide(el) { if (el) Object.assign(el, {hidden: true, empty: null}); },
};

function setup({chart = true} = {}) {
    const elements = {};
    function element(id) {
        const classes = new Set();
        return elements[id] = {id, style: {}, attrs: {}, children: [],
            classList: {toggle(n, on) { on ? classes.add(n) : classes.delete(n); }, add(n) { classes.add(n); }, contains(n) { return classes.has(n); }},
            setAttribute(n, v) { this.attrs[n] = v; }, addEventListener(n, fn) { this[n] = fn; },
            querySelectorAll() { return this.children; },
            appendChild(el) { this.children.push(el); },
            replaceChildren() { this.children = []; }};
    }
    for (const file of ['bqm_tab', 'bqm_dialogs']) {
        for (const [, id] of fs.readFileSync(`app/modules/bqm/templates/${file}.html`, 'utf8').matchAll(/id="([^"]+)"/g)) element(id);
    }
    for (const id of ['today', 'yesterday', '7d', '30d']) elements['bqm-quick-range'].appendChild(elements['bqm-' + id + '-btn']);
    const requests = [];
    // The browser clock is a day ahead of the configured time zone's date from todayStr().
    class FixedDate extends Date {
        constructor(...args) { super(...(args.length ? args : ['2026-01-03T12:00:00'])); }
    }
    const c = vm.createContext({DOCSightEmptyState: emptyState, document: {getElementById: id => elements[id], createElement: () => element('cell'), createTextNode: text => ({nodeType: 3, textContent: String(text)})},
        Date: FixedDate,
        T: require('./english-catalog')(), todayStr: () => '2026-01-02', pad: n => String(n).padStart(2, '0'),
        formatDateDE: s => s, clearTimeout() {}, docsightUrl: s => s, labelDataTable() {},
        URL: {createObjectURL: file => 'blob:' + file.name, revokeObjectURL() {}},
        fetch: async url => { requests.push(url); return {json: async () => ({points: 1, data: {}})}; },
        ...(chart && {BQMChart: {render(...args) { c.rendered = args; }}})});
    c.window = c;
    run(c, 'app/static/js/segmented.js');
    run(c, 'app/modules/bqm/static/main.js');
    c.bqmDate = '2026-01-02';  // initBqmView() starts on today
    c._bqmCsvDates = new Set(['2026-01-02', '2026-01-01', '2025-12-30']);
    c._bqmAvailableDates = c._bqmCsvDates;
    return {c, elements, requests};
}
function selected(elements, expected) {
    for (const name of ['today', 'yesterday', '7d', '30d']) {
        const el = elements['bqm-' + name + '-btn'];
        assert.equal(el.classList.contains('active'), name === expected, name);
        assert.equal(el.attrs['aria-pressed'], String(name === expected), name);
    }
}
test('quick selection follows dates, ranges, calendar transitions and month navigation', () => {
    const {c, elements} = setup();
    c.updateBqmQuickButtons(); selected(elements, 'today');
    c.setBqmQuickRange(7); selected(elements, '7d');
    c.bqmMonthNav(-1); selected(elements, '7d');
    c.setBqmQuickRange(30); selected(elements, '30d');
    c.selectBqmDate('2026-01-01'); selected(elements, 'yesterday');
    c.selectBqmDate('2025-12-30'); selected(elements, null);
    c.setBqmQuickRange(7);
    const cell = elements['bqm-calendar-grid'].children.findLast(el => el.attrs['data-date'] === '2026-01-01');
    cell.click({shiftKey: true}); selected(elements, null);
    c.setBqmQuickRange(1); selected(elements, 'today');
});
test('quick range group hides as a whole without stored data', () => {
    const {c, elements} = setup();
    c.updateBqmQuickButtons();
    assert.equal(elements['bqm-quick-range'].hidden, false);
    c._bqmCsvDates = new Set();
    c.updateBqmQuickButtons();
    assert.equal(elements['bqm-quick-range'].hidden, true);
});
test('loaders pass selected date mode even for sparse responses', async () => {
    const {c} = setup();
    for (const [start, end, dates] of [['2025-12-27', '2026-01-02', true], ['2025-12-04', '2026-01-02', true], ['2026-01-02', '2026-01-02', false]]) {
        c.loadBqmRangeChart(start, end);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(c.rendered[2].dateAxis, dates);
    }
    c.loadBqmChart('2026-01-01');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(c.rendered[2].dateAxis, false);
});
for (const [name, date] of [['today', '2026-01-02'], ['yesterday', '2026-01-01']]) {
    test(name + ' shows both formats, stops live refresh and retains the image deletion range', async () => {
        const {c, elements, requests} = setup();
        const clearedTimers = [];
        c.clearTimeout = timer => clearedTimers.push(timer);
        c._bqmPngDates = new Set([date]);
        c._bqmLiveTimer = 42;
        c._bqmRangeStart = '2025-12-04';
        c._bqmRangeEnd = '2026-01-02';
        c.bqmMonthNav(-1);

        elements['bqm-' + name + '-btn'].click();
        await new Promise(resolve => setImmediate(resolve));

        assert.deepEqual(requests, ['/api/bqm/data/' + date]);
        assert.equal(c._bqmLiveTimer, null);
        assert.equal(elements['bqm-view-toggle'].hidden, false);
        assert.equal(c.bqmDate, date);
        assert.equal(c._bqmRangeStart, date);
        assert.equal(c._bqmRangeEnd, date);
        assert.deepEqual(clearedTimers, [42]);
        assert.equal(elements['bqm-range-label'].textContent, date + ' \u2013 ' + date + ' (1)');
        assert.equal(elements['bqm-month-label'].textContent, 'January 2026');
        assert.equal(c.rendered[2].dateAxis, false);
        selected(elements, name);

        let deletion;
        c.docsightConfirm = async () => true;
        c.showToast = () => {};
        c.fetch = async (url, opts) => {
            if (opts && opts.method === 'DELETE') deletion = {url, body: JSON.parse(opts.body)};
            return {json: async () => ({deleted: 1})};
        };
        c.deleteBqmImages();
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(deletion, {url: '/api/bqm/images', body: {start: date, end: date}});
    });
}
test('7d and 30d load the range that ends today', async () => {
    const {c, elements, requests} = setup();
    for (const [name, start] of [['7d', '2025-12-27'], ['30d', '2025-12-04']]) {
        elements['bqm-' + name + '-btn'].click();
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual([c._bqmRangeStart, c._bqmRangeEnd, c.bqmDate], [start, '2026-01-02', '2026-01-02']);
        assert.equal(requests.at(-1), '/api/bqm/data/range?start=' + start + '&end=2026-01-02');
        assert.equal(elements['bqm-range-label'].textContent, start + ' \u2013 2026-01-02 (3)');
        selected(elements, name);
    }
});
test('PNG days and the live graph still load when the chart script failed to load', async () => {
    const {c, elements, requests} = setup({chart: false});
    c._bqmAvailableDates = new Set([...c._bqmCsvDates, '2025-12-20']);
    c.selectBqmDate('2025-12-20');
    assert.equal(elements['bqm-image'].src, '/api/bqm/image/2025-12-20');
    c._bqmCsvDates = new Set();
    c.selectBqmDate('2026-01-02');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.at(-1), '/api/bqm/live');
    // The fake live response is not ok, so the view falls back to today's stored PNG.
    assert.equal(elements['bqm-image'].src, '/api/bqm/image/2026-01-02');
});
test('first opening after midnight starts on the new day, not the day the page loaded', () => {
    const {c, elements, requests} = setup();
    c.todayStr = () => '2026-01-01';
    run(c, 'app/modules/bqm/static/main.js');
    c.todayStr = () => '2026-01-02';
    elements['view-bqm'] = {};
    c._bqmDatesLoaded = true;
    c._bqmCsvDates = c._bqmAvailableDates = new Set(['2026-01-02', '2026-01-01']);
    c.initBqmView();
    assert.equal(c.bqmDate, '2026-01-02');
    assert.deepEqual(requests, ['/api/bqm/data/2026-01-02']);
});
const deleteDialog = {title: 'Delete', confirmText: 'Delete', cancelText: 'Cancel', danger: true};
const deleteAll = {...deleteDialog, message: 'Delete all 3 BQM images?', requireText: 'DELETE', requireLabel: 'Type DELETE to confirm'};
for (const [label, range, answer, dialog, body, toast, stored] of [
    ['deletes the selected range', ['2026-01-01', '2026-01-02'], true,
        {...deleteDialog, message: 'Delete 2 images from 2026-01-01 to 2026-01-02?'}, {start: '2026-01-01', end: '2026-01-02'}, ['2 images deleted', 'success']],
    ['deletes all images after typed confirmation', [null, null], true, deleteAll, {all: true, confirm: 'DELETE_ALL'}, ['2 images deleted', 'success']],
    ['keeps the images when the dialog is cancelled', [null, null], false, deleteAll, null, null],
    ['reports a failed request', [null, null], 'fail', deleteAll, {all: true, confirm: 'DELETE_ALL'}, ['Delete failed: offline', 'error']],
    ['tells that a range without data has nothing to delete', ['2025-11-01', '2025-11-30'], true, null, null, ['No BQM data in this range', 'info']],
    ['tells that nothing is stored', [null, null], true, null, null, ['No BQM data in this range', 'info'], new Set()],
]) {
    test('image deletion ' + label, async () => {
        const {c} = setup();
        if (stored) c._bqmAvailableDates = stored;
        [c._bqmRangeStart, c._bqmRangeEnd] = range;
        const dialogs = [], toasts = [], calls = [];
        c.docsightConfirm = async options => { dialogs.push({...options}); return Boolean(answer); };
        c.showToast = (...args) => toasts.push(args);
        c.fetch = async (url, options = {}) => {
            calls.push([url, options.method, options.headers && {...options.headers}, options.body && JSON.parse(options.body)]);
            if (answer === 'fail') throw new Error('offline');
            return {json: async () => ({deleted: 2})};
        };
        c.deleteBqmImages();
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(dialogs, dialog ? [dialog] : []);
        assert.deepEqual(calls[0], body ? ['/api/bqm/images', 'DELETE', {'Content-Type': 'application/json'}, body] : undefined);
        assert.deepEqual(toasts, toast ? [toast] : []);
        const deleted = toast && toast[1] === 'success';
        assert.deepEqual(calls.slice(1).map(call => call[0]), deleted ? ['/api/bqm/data/dates'] : []);
        assert.deepEqual([c._bqmRangeStart, c._bqmRangeEnd], deleted ? [null, null] : range);
    });
}
test('image import shifts dates by the offset and summarizes readiness in both status lines', () => {
    const {c, elements} = setup();
    const add = (offset, ...names) => {
        elements['bqm-import-offset'].value = offset;
        c.handleBqmImportFiles(names.map(name => ({name, type: 'image/png'})));
    };
    const state = () => [Array.from(c._bqmImportFiles, entry => entry.date), elements['bqm-import-status'].textContent,
        elements['bqm-import-validation-state'].textContent, elements['bqm-import-validation-state'].className];
    add('0', 'bqm-2026-01-01.png');
    c._bqmImportFiles[0].date = '2025-06-01';
    // Without an offset, files added later leave dates edited by hand alone.
    add('', 'graph.png');
    assert.deepEqual(state(), [['2025-06-01', ''], '1 ready, 1 needs a date', '1 ready, 1 needs a date', 'import-validation-state is-warning']);
    add('2', '20260131.png');
    assert.deepEqual(state(), [['2026-01-03', '', '2026-02-02'], '2 ready, 1 needs a date', '2 ready, 1 needs a date', 'import-validation-state is-warning']);
    elements['bqm-import-offset'].value = '-1';
    c.applyBqmImportOffset();
    assert.deepEqual(state()[0], ['2025-12-31', '', '2026-01-30']);
    c._bqmImportFiles.splice(1, 1);
    c.renderBqmImportPreview();
    assert.deepEqual(state(), [['2025-12-31', '2026-01-30'], '2 ready', '2 ready', 'import-validation-state is-success']);
});
test('BQM axis uses dates for sparse ranges and retains time in tooltip labels', () => {
    let rendered;
    const c = vm.createContext({window: {}, document: {getElementById: id => ({id})}, T: require('./english-catalog')(),
        pad: n => String(n).padStart(2, '0'), bandPlugin() {}, zoomPlugin() {},
        renderChart(...args) { rendered = args; }});
    run(c, 'app/static/js/chart-engine.js');
    c.renderChart = (...args) => { rendered = args; };
    run(c, 'app/modules/bqm/static/js/bqm-chart.js');
    const payload = {data: {timestamps: ['2026-01-02T12:34:00'], latency_avg: [10], latency_min: [8], latency_max: [12], lost_polls: [0]}};
    for (const dates of [true, false]) {
        c.BQMChart.render('chart', payload, {dateAxis: dates});
        const opts = rendered[5];
        assert.equal(opts.xValueCallback(opts.xData[0]), dates ? '01-02' : '12:34');
        assert.equal(rendered[1][0], dates ? '01-02 12:34' : '12:34');
        assert.match(opts.tooltipLabelCallback({dataIndex: 0, dataset: {label: 'Avg Latency'}}), /10.00 ms/);
    }
});
