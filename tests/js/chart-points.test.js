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
            test(`${mode} ${type}, ${count} samples: points are opt-in and bars always opt out`, () => {
                const b = browser();
                const data = Array.from({length: count}, (_, i) => i === 1 ? null : i);
                const datasets = [undefined, false, true].map(showPoints => ({
                    label: String(showPoints), data, showPoints,
                }));
                b.renderChart('chart', data.map(String), datasets, type, null, {tempData: data});
                if (mode === 'zoom') b.openChartZoom('chart');
                const chart = mode === 'zoom' ? b.zoomChart : b.charts.chart;
                assert.deepEqual(Array.from(chart.options.series.slice(1), s => s.points.show),
                    type === 'bar' ? [false, false, false] : [false, false, true, false]);
                assert.equal(chart.data[1], data);
                assert.equal(chart.options.series[1].spanGaps, false);
                assert.equal(chart.options.cursor.points.show, false);
                assert.ok(chart.options.plugins[0].hooks.setCursor);
            });
        }
    }
}
