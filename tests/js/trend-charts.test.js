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

test('before/after periods count errors per slot from their own start', () => {
    const e = engine();
    const rows = [
        {timestamp: '2026-03-08T00:10:00Z', uncorr_errors: 100},
        {timestamp: '2026-03-08T00:40:00Z', uncorr_errors: 120},
        {timestamp: '2026-03-08T02:20:00Z', uncorr_errors: 15},
        {timestamp: '2026-03-08T02:50:00Z', uncorr_errors: null},
        {timestamp: '2026-03-09T00:00:00Z', uncorr_errors: 40},
    ];
    const start = Date.parse('2026-03-08T00:00:00Z');
    assert.deepEqual(Array.from(e.docsightErrorSlots(rows, start, 4, 60)), [20, null, 15, null]);
});

test('the interval follows the compared span like the range presets', () => {
    const e = engine();
    assert.deepEqual([30, 360, 1439, 1440 * 7, 1440 * 30, 1440 * 365].map(e.docsightErrorBucketMinutesForSpan),
        [5, 15, 60, 360, 1440, 1440]);
    assert.equal(e.docsightErrorsTitle(360), 'Uncorrectable errors per 6 hours');
});

test('axis labels on short dense series keep one even gap that fits a label', () => {
    for (const n of [7, 9, 12, 17, 25, 50, 200, 1440]) {
        const e = engine();
        const labels = Array.from({length: n}, (_, i) => `0${i % 10}:${String(i % 60).padStart(2, '0')} PM`);
        e.renderChart('chart', labels, [{label: 'x', data: labels.map((_, i) => i)}]);
        const splits = Array.from(e.charts.chart.options.axes[0].splits());
        const gaps = splits.slice(1).map((value, i) => value - splits[i]);
        const evenGaps = gaps.slice(0, -1);
        assert.ok(evenGaps.every(gap => gap === evenGaps[0]), `n=${n} gaps ${gaps}`);
        // 600 px wide stub minus the 58 px axis and padding; "00:00 PM" is about 60 px plus 18 px of air.
        const pxPerPoint = (600 - 58 - 24) / (n - 1);
        assert.ok(gaps.every(gap => gap * pxPerPoint >= 60 + 18 - 0.01), `n=${n} gaps ${gaps}`);
    }
});

test('a pause much longer than the poll interval breaks the series and is reported as a gap', () => {
    const e = engine();
    const times = [0, 60, 120, 1000, 1060];
    const series = e.docsightTimeSeries(['a', 'b', 'c', 'd', 'e'], [{data: [1, 2, 3, 4, 5]}], times, null);
    assert.equal(series.interval, 60);
    assert.deepEqual(Array.from(series.labels), ['a', 'b', 'c', null, 'd', 'e']);
    assert.deepEqual(Array.from(series.data[0]), [1, 2, 3, null, 4, 5]);
    assert.deepEqual(Array.from(series.original), [0, 1, 2, null, 3, 4]);
    assert.deepEqual(JSON.parse(JSON.stringify(series.gaps)), [{start: 120, end: 1000}]);
    // The break point sits inside the gap, so the line ends at the last reading.
    assert.ok(series.times[3] > 120 && series.times[3] < 1000);
    // Regular polls have no gap.
    assert.deepEqual(Array.from(e.docsightTimeSeries(['a', 'b', 'c'], [{data: [1, 2, 3]}], [0, 60, 150], null).gaps), []);
});

test('runs of empty intervals are gaps in regular series such as the error bars', () => {
    const e = engine();
    const times = [0, 10, 20, 30, 40, 50, 60];
    assert.deepEqual(JSON.parse(JSON.stringify(e.docsightNullRunGaps(times, [1, null, null, null, 2, null, 3]))), [{start: 0, end: 40}]);
    // Short runs and runs at the ends are not gaps.
    assert.deepEqual(Array.from(e.docsightNullRunGaps(times, [1, null, 2, 3, 4, 5, 6])), []);
    assert.deepEqual(Array.from(e.docsightNullRunGaps(times, [null, null, null, null, 2, 3, 4])), []);
});

test('time axis labels stay a label apart however unevenly the points are spaced', () => {
    const e = engine();
    // Two stretches of polls with a long pause between them.
    const times = [];
    for (let t = 0; t <= 6000; t += 300) times.push(t);
    for (let t = 20000; t <= 26000; t += 300) times.push(t);
    const labels = times.map((_, i) => `0${i % 10}:00 PM`);
    const range = [-150, 26150];
    const splits = Array.from(e.buildTimeSplits(times, labels, range, 500, 60));
    const px = splits.map(t => (t - range[0]) / (range[1] - range[0]) * 500);
    assert.ok(px.every((x, i) => i === 0 || x - px[i - 1] >= 78), `splits ${splits}`);
    assert.ok(px.every(x => x >= 26 && x <= 474), `inset ${px}`);
    assert.ok(splits.some(t => t <= 6000) && splits.some(t => t >= 20000), 'both stretches are labelled');
});

test('charts with times place points by time and map clicks back to the caller', () => {
    const e = engine();
    const times = [0, 60, 120, 1000, 1060];
    e.renderChart('chart', ['a', 'b', 'c', 'd', 'e'], [{label: 'x', data: [1, 2, 3, 4, 5]}], null, null, {times});
    const chart = e.charts.chart;
    assert.equal(chart.data[0].length, 6);
    assert.equal(chart.data[0][4], 1000);
    assert.deepEqual(Array.from(chart._docsightOriginal), [0, 1, 2, null, 3, 4]);
    assert.equal(e.docsightGapLabel(880).title, 'No data');
    assert.equal(e.docsightGapLabel(880).duration, '15 min');
    assert.equal(e.docsightGapLabel(6 * 3600 + 900).duration, '6 h 15 min');
    assert.equal(e.docsightGapLabel(29 * 3600).duration, '1 d 5 h');
});

test('a single point on a time axis stays in view as a dot with its label', () => {
    const e = engine();
    e.renderChart('chart', ['06:23 AM'], [{label: 'x', data: [4.5]}], null, null, {times: [1791440580]});
    const chart = e.charts.chart;
    const [min, max] = chart.options.scales.x.range();
    assert.ok(min < 1791440580 && max > 1791440580, `range ${min}..${max}`);
    assert.deepEqual(Array.from(chart.options.axes[0].splits()), [1791440580]);
    assert.equal(chart.options.series[1].points.show, true);
});
