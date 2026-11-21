'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load() {
    const context = {T: require('./english-catalog')(), document: {}, docsightParseTime: value => new Date(value)};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/modules/journal/static/js/journal-timeline.js', 'utf8'), context);
    return context;
}

const HOUR = 3600000;
const T0 = Date.UTC(2026, 9, 1);
const point = (h, values) => Object.assign({timestamp: new Date(T0 + h * HOUR).toISOString()}, values);

test('the case chart spans its points, SNR two dB beyond the readings, speed a tenth above the fastest', () => {
    const sc = load().journalTimelineScales([
        point(0, {source: 'modem', ds_snr_min: 33.4}),
        point(6, {source: 'modem', ds_snr_min: 38.2}),
        point(12, {source: 'speedtest', download_mbps: 250}),
        point(24, {source: 'event', severity: 'warning'}),
    ], 800, 280);
    assert.deepEqual([sc.tMin, sc.tMax], [T0, T0 + 24 * HOUR]);
    assert.deepEqual([sc.snrMin, sc.snrMax], [31, 41]);
    assert.deepEqual([sc.speedMax, sc.speedStep], [275, 50]);
    assert.equal(sc.xScale(T0), 60);
    assert.equal(sc.xScale(T0 + 24 * HOUR), 800 - 60);
    assert.equal(sc.ySnr(sc.snrMin), 280 - 40);
    assert.equal(sc.yDl(sc.speedMax), 20);
});

test('a single moment spans a day; missing readings fall back to fixed scales', () => {
    const sc = load().journalTimelineScales([point(5, {source: 'speedtest', download_mbps: 3})], 600, 280);
    assert.equal(sc.tMax - sc.tMin, 24 * HOUR);
    assert.deepEqual([sc.snrMin, sc.snrMax], [20, 45]);
    // Below 10 Mbps the axis keeps a readable 0–100 scale.
    assert.deepEqual([sc.speedMax, sc.speedStep], [100, 25]);
});

test('the case chart SNR line skips a missing value and plots a measured 0 at its position', () => {
    const context = load();
    const calls = [];
    const ctx = new Proxy({}, {
        get: (_target, name) => (...args) => calls.push([name, ...args]),
        set: (_target, name, value) => calls.push(['set', name, value]),
    });
    Object.assign(context, {
        getComputedStyle: () => ({getPropertyValue: () => ''}),
        docsightFormatAxisTime: () => '',
    });
    context.document = {
        documentElement: {},
        getElementById: () => ({getContext: () => ctx, style: {}, parentElement: {getBoundingClientRect: () => ({width: 800})}}),
    };
    const data = [[0, 36], [6, null], [12, 36], [18, 0]].map(([h, snr]) => point(h, {source: 'modem', ds_snr_min: snr}));
    context._renderTimelineChart(data);

    const sc = context.journalTimelineScales(data, 800, 280);
    const start = calls.findIndex(c => c[0] === 'set' && c[1] === 'strokeStyle' && c[2] === '#a855f7');
    const snrPath = calls.slice(start, calls.findIndex((c, i) => i > start && c[0] === 'stroke'));
    assert.equal(sc.snrMin, -2);
    assert.deepEqual(snrPath.filter(c => c[0] === 'moveTo' || c[0] === 'lineTo'), [['moveTo', sc.xScale(T0), sc.ySnr(36)],
        ['lineTo', sc.xScale(T0 + 12 * HOUR), sc.ySnr(36)], ['lineTo', sc.xScale(T0 + 18 * HOUR), sc.ySnr(0)]]);
});

test('a failed case PDF shows the server message, else the generic error', async () => {
    for (const [reply, message] of [
        [{ok: false, json: async () => ({error: 'Reading stored data failed.'})}, 'Reading stored data failed.'],
        [{ok: false, json: async () => { throw new SyntaxError('not JSON'); }}, 'Network error'],
    ]) {
        const context = load(), toasts = [];
        Object.assign(context, {
            URLSearchParams, docsightUrl: url => url, fetch: async () => reply,
            showToast: (text, kind) => toasts.push([text, kind]),
        });
        context.document = {querySelector: () => null, getElementById: () => null};
        await context.downloadIncidentPdf(7, 'Outage');
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(toasts, [[message, 'error']]);
    }
});
