'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function browser() {
    const elements = new Map();
    const element = () => ({tagName: 'DIV', style: {}, offsetWidth: 800,
        offsetHeight: 400, closest: () => null});
    function Chart(options, data) {
        Object.assign(this, {options, data, destroy() {}});
    }
    Chart.paths = {bars: () => () => {}, stepped: () => () => {}};
    const context = {
        document: {getElementById(id) {
            if (!elements.has(id)) elements.set(id, element());
            return elements.get(id);
        }, documentElement: {getAttribute: () => 'dark'}},
        uPlot: Chart, T: {}, setTimeout: fn => fn(),
        ResizeObserver: class {observe() {} disconnect() {}},
        DOCSightModal: {open() {}, close() {}},
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/static/js/chart-engine.js', 'utf8'), context);
    return context;
}

for (const count of [1, 30, 31, 100]) {
    for (const type of ['line', 'bar']) {
        for (const mode of ['normal', 'zoom']) {
            test(`${mode} ${type}, ${count} samples: points are opt-in (a single sample shows as a dot) and bars always opt out`, () => {
                const b = browser();
                b._tempOverlayVisible = true;
                const data = Array.from({length: count}, (_, i) => i === 1 ? null : i);
                const datasets = [undefined, false, true].map(showPoints => ({
                    label: String(showPoints), data, showPoints,
                }));
                b.renderChart('chart', data.map(String), datasets, type, null, {tempData: data});
                if (mode === 'zoom') b.openChartZoom('chart');
                const chart = mode === 'zoom' ? b.zoomChart : b.charts.chart;
                assert.deepEqual(Array.from(chart.options.series.slice(1), s => s.points.show),
                    type === 'bar' ? [false, false, false] : [count === 1, false, true, false]);
                assert.equal(chart.data[1], data);
                assert.equal(chart.options.series[1].spanGaps, false);
                assert.equal(chart.options.cursor.points.show, false);
                assert.ok(chart.options.plugins[0].hooks.setCursor);
            });
        }
    }
}

for (const mode of ['normal', 'zoom']) {
    test(`${mode}: helper series marked hideInLegend get the hidden legend class`, () => {
        const b = browser();
        const data = [1, 2, 3];
        b.renderChart('chart', ['a', 'b', 'c'], [
            {label: 'Target', data},
            {label: '_max_0', data, show: false, hideInLegend: true},
        ], 'line', null, {});
        if (mode === 'zoom') b.openChartZoom('chart');
        const chart = mode === 'zoom' ? b.zoomChart : b.charts.chart;
        assert.deepEqual(Array.from(chart.options.series.slice(1), s => s.class),
            [undefined, 'docsight-legend-hidden']);
    });
}

test('compact axis labels keep close ticks distinct', () => {
    const b = browser();
    assert.deepEqual(Array.from(b.fmtKTicks([35080, 35100, 35120])), ['35.08k', '35.10k', '35.12k']);
    assert.deepEqual(Array.from(b.fmtKTicks([0, 200000, 400000])), ['0', '200k', '400k']);
    assert.deepEqual(Array.from(b.fmtKTicks([1000, 1500, 2000])), ['1.0k', '1.5k', '2.0k']);
    assert.deepEqual(Array.from(b.fmtKTicks([1000000, 2000000])), ['1M', '2M']);
    // Steps that would need three decimals fall back to the full number.
    assert.deepEqual(Array.from(b.fmtKTicks([35054, 35055, 35056])), ['35,054', '35,055', '35,056']);
    // Tooltips and other single values keep the short form.
    assert.equal(b.fmtK(35100), '35.1k');
    assert.equal(b.fmtK(638000), '638k');
});

test('large error counts get step-aware compact y labels', () => {
    const b = browser();
    const data = [35080, 35090, 35120];
    b.renderChart('chart', data.map(String), [{label: 'errors', data}], 'line', null, {});
    const axis = b.charts.chart.options.axes[1];
    assert.deepEqual(Array.from(axis.values(null, [35080, 35100, 35120])), ['35.08k', '35.10k', '35.12k']);
});
