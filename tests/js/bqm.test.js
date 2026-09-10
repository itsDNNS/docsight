'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const run = (c, file) => vm.runInContext(fs.readFileSync(file, 'utf8'), c);
function setup() {
    const elements = {};
    function element(id) {
        const classes = new Set();
        return elements[id] = {id, style: {}, attrs: {}, children: [],
            classList: {toggle(n, on) { on ? classes.add(n) : classes.delete(n); }, add(n) { classes.add(n); }, contains(n) { return classes.has(n); }},
            setAttribute(n, v) { this.attrs[n] = v; }, addEventListener(n, fn) { this[n] = fn; },
            appendChild(el) { this.children.push(el); }};
    }
    for (const id of ['today', 'yesterday', '7d', '30d']) element('bqm-' + id + '-btn');
    element('bqm-calendar-grid'); element('bqm-month-label');
    element('bqm-view-toggle'); element('bqm-range-label');
    const requests = [];
    class FixedDate extends Date {
        constructor(...args) { super(...(args.length ? args : ['2026-01-02T12:00:00'])); }
    }
    const c = vm.createContext({document: {getElementById: id => elements[id], createElement: () => element('cell')},
        Date: FixedDate,
        T: {}, todayStr: () => '2026-01-02', pad: n => String(n).padStart(2, '0'),
        formatDateDE: s => s, clearTimeout() {}, docsightUrl: s => s,
        fetch: async url => { requests.push(url); return {json: async () => ({points: 1, data: {}})}; },
        BQMChart: {render(...args) { c.rendered = args; }}});
    c.window = c;
    run(c, 'app/modules/bqm/static/main.js');
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

        assert.equal(c._bqmLiveTimer, null);
        assert.equal(elements['bqm-view-toggle'].style.display, 'flex');
        assert.deepEqual(requests, ['/api/bqm/data/' + date]);
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
test('BQM axis uses dates for sparse ranges and retains time in tooltip labels', () => {
    let rendered;
    const c = vm.createContext({window: {}, document: {getElementById: id => ({id})}, T: {},
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
