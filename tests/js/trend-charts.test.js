'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function engine() {
    const element = () => ({tagName: 'DIV', style: {}, offsetWidth: 600, offsetHeight: 300, closest: () => null});
    const elements = new Map();
    function Chart(options, data) { Object.assign(this, {options, data, destroy() {}}); }
    Chart.paths = {bars: () => () => {}, stepped: () => () => {}};
    const context = {
        document: {
            getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
            documentElement: {getAttribute: () => 'dark'},
        },
        uPlot: Chart, T: {}, setTimeout: fn => fn(),
        ResizeObserver: class { observe() {} disconnect() {} },
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/static/js/chart-engine.js', 'utf8'), context);
    return context;
}

const row = (timestamp, errors) => ({timestamp, ds_uncorrectable_errors: errors});

test('errors are counted per interval from the cumulative counter', () => {
    const e = engine();
    const buckets = e.docsightErrorBuckets([
        row('2026-10-07T08:05:00', 100),
        row('2026-10-07T08:20:00', 130),
        row('2026-10-07T08:50:00', 130),
        row('2026-10-07T09:10:00', null),
        row('2026-10-07T09:15:00', 180),
    ], '1d');
    assert.deepEqual(JSON.parse(JSON.stringify(buckets.map(b => [b.timestamp, b.errors]))), [
        ['2026-10-07T08:00:00', 30],
        ['2026-10-07T09:00:00', 50],
    ]);
});

test('a counter reset after a modem restart counts its new value, never a negative change', () => {
    const e = engine();
    const buckets = e.docsightErrorBuckets([
        row('2026-10-07T08:00:00', 5000),
        row('2026-10-07T09:00:00', 40),
        row('2026-10-07T10:00:00', 45),
    ], '1d');
    assert.deepEqual(Array.from(buckets, b => b.errors), [0, 40, 5]);
});

test('interval size follows the range and buckets follow wall-clock days', () => {
    const e = engine();
    assert.deepEqual(['1h', '6h', '1d', '2d', '3d', '7d', '30d', '90d'].map(e.docsightErrorBucketMinutes),
        [5, 15, 60, 120, 180, 360, 1440, 1440]);
    const days = e.docsightErrorBuckets([
        row('2026-10-06T23:50:00', 10),
        row('2026-10-07T00:10:00', 12),
    ], '30d');
    assert.deepEqual(Array.from(days, b => b.timestamp), ['2026-10-06T00:00:00', '2026-10-07T00:00:00']);
});

test('power and SNR bands cover their target ranges without gaps', () => {
    const e = engine();
    for (const zones of [e.DS_POWER_THRESHOLDS, e.DS_SNR_THRESHOLDS, e.US_POWER_THRESHOLDS]) {
        const bands = zones.filter(z => z.band).sort((a, b) => a.min - b.min);
        for (let i = 1; i < bands.length; i++) assert.equal(bands[i].min, bands[i - 1].max);
        const meta = zones.find(z => z.yMin !== undefined);
        assert.ok(bands[0].min <= meta.yMin && bands[bands.length - 1].max >= meta.yMax);
        assert.ok(bands.every(z => ['good', 'tolerated', 'marginal', 'critical'].includes(z.band)));
    }
});

test('dense charts use the full width and move the outer labels inward', () => {
    const e = engine();
    const labels = Array.from({length: 200}, (_, i) => `10/${String(i % 30 + 1).padStart(2, '0')}, 08:${String(i % 60).padStart(2, '0')} AM`);
    e.renderChart('chart', labels, [{label: 'x', data: labels.map((_, i) => i)}], null, e.DS_POWER_THRESHOLDS);
    const chart = e.charts.chart;
    const range = chart.options.scales.x.range();
    assert.ok(range[0] >= -2 && range[1] <= 201, `x range ${range}`);
    const splits = chart.options.axes[0].splits();
    assert.ok(splits[0] > 0 && splits[splits.length - 1] < 199, `splits ${splits}`);
});

test('sparse charts keep a label at every point', () => {
    const e = engine();
    const labels = ['Mon', 'Tue', 'Wed'];
    e.renderChart('chart', labels, [{label: 'x', data: [1, 2, 3]}]);
    assert.deepEqual(Array.from(e.charts.chart.options.axes[0].splits()), [0, 1, 2]);
});

test('intervals without readings stay empty instead of closing the gap', () => {
    const e = engine();
    const buckets = e.docsightErrorBuckets([
        row('2026-10-07T08:10:00', 10),
        row('2026-10-07T11:10:00', 14),
    ], '1d');
    assert.deepEqual(Array.from(buckets, b => [b.timestamp.slice(11, 16), b.errors]),
        [['08:00', 0], ['09:00', null], ['10:00', null], ['11:00', 4]]);
});

test('bars keep colors that already carry alpha', () => {
    const e = engine();
    assert.equal(e.barFill('#f44336'), '#f44336cc');
    assert.equal(e.barFill('rgba(248,149,141,0.8)'), 'rgba(248,149,141,0.8)');
});
