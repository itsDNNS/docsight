'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function charts({storedShowSpikes = null} = {}) {
    const rendered = [];
    const storage = new Map(storedShowSpikes === null ? [] : [['docsight.connectionMonitor.showSpikes', storedShowSpikes]]);
    const toggle = {
        dataset: {}, hidden: true, classes: new Set(), attrs: {},
        classList: {toggle(name, on) { if (on) toggle.classes.add(name); else toggle.classes.delete(name); }},
        setAttribute(name, value) { toggle.attrs[name] = value; },
        addEventListener(type, handler) { toggle.onclick = handler; },
    };
    const context = {
        document: {getElementById: id => (id === 'cm-spikes-toggle' ? toggle : null)},
        renderChart: (id, labels, datasets, type, zones, opts) => rendered.push({labels, datasets, zones, opts}),
        bandPlugin: (lo, hi, color) => ({band: [lo, hi, color]}),
        charts: {},
        docsightFormatXAxisLabels: timestamps => timestamps.map(String),
        localStorage: {
            getItem: key => (storage.has(key) ? storage.get(key) : null),
            setItem: (key, value) => storage.set(key, value),
        },
    };
    context.window = context;
    vm.runInNewContext(
        fs.readFileSync('app/modules/connection_monitor/static/js/connection-monitor-charts.js', 'utf8') +
        '\nwindow.CMCharts = CMCharts;',
        context,
    );
    const last = () => rendered[rendered.length - 1];
    return {
        api: context.CMCharts,
        render: data => context.CMCharts.renderCombinedChart('chart', data, 604800),
        yMax: () => last().zones[last().zones.length - 1].yMax,
        spikeMarkers: () => last().opts.plugins[1],
        last,
        rendered,
        toggle,
        storage,
    };
}

function rawTarget(values, id = 1) {
    return {
        target: {id, label: 'Target ' + id, host: '192.0.2.' + id},
        samples: values.map((latency, i) => ({timestamp: 1000 + i * 5, latency_ms: latency})),
    };
}

const typicalWithOneSpike = [...Array(200).fill(20), 550];

test('latency axis follows typical latency instead of the highest spike', () => {
    const {api} = charts();
    assert.equal(api.latencyAxisMax([...Array(200).fill(20), 550], 550, false), 40);
    assert.equal(api.latencyAxisMax(Array(10).fill(80), 80, false), 96);
    assert.equal(api.latencyAxisMax([20, 20], 550, true), 633);
    // Typical scale never exceeds the full scale.
    assert.equal(api.latencyAxisMax([90], 70, false), 84);
    assert.equal(api.latencyAxisMax([], 0, false), 40);
});

test('a single raw spike no longer flattens the chart and is marked instead', () => {
    const view = charts();
    view.render([rawTarget(typicalWithOneSpike), rawTarget(Array(201).fill(1.3), 2)]);
    assert.equal(view.yMax(), 40);
    assert.ok(view.spikeMarkers().hooks.draw, 'spike markers are drawn');
    assert.equal(view.toggle.hidden, false);
    assert.equal(view.toggle.attrs['aria-pressed'], 'false');
});

test('per-bucket maxima do not drive the axis but are marked when clipped', () => {
    const view = charts();
    const samples = Array.from({length: 50}, (_, i) => ({
        timestamp: 1000 + i * 600, latency_ms: 20, min_latency_ms: 15, max_latency_ms: i === 10 ? 550 : 25,
    }));
    view.render([{target: {id: 1, label: 'Google DNS', host: '8.8.8.8'}, samples}]);
    assert.equal(view.yMax(), 40);
    assert.ok(view.spikeMarkers().hooks.draw);
    const [line, min, max] = view.last().datasets;
    assert.equal(line.hideInLegend, undefined);
    assert.equal(min.hideInLegend, true);
    assert.equal(max.hideInLegend, true);
});

test('show spikes toggle rescales to the full range and is remembered', () => {
    const view = charts();
    view.render([rawTarget(typicalWithOneSpike)]);
    view.toggle.onclick();
    assert.equal(view.rendered.length, 2, 'toggle re-renders the last data');
    assert.equal(view.yMax(), 633);
    assert.equal(view.spikeMarkers().hooks, undefined, 'nothing is clipped at full scale');
    assert.equal(view.toggle.hidden, false, 'toggle stays visible to switch back');
    assert.equal(view.toggle.attrs['aria-pressed'], 'true');
    assert.ok(view.toggle.classes.has('active'));
    assert.equal(view.storage.get('docsight.connectionMonitor.showSpikes'), '1');

    const reloaded = charts({storedShowSpikes: '1'});
    reloaded.render([rawTarget(typicalWithOneSpike)]);
    assert.equal(reloaded.yMax(), 633);
});

test('toggle stays hidden when nothing is clipped', () => {
    const view = charts();
    view.render([rawTarget(Array(100).fill(20))]);
    assert.equal(view.yMax(), 40);
    assert.equal(view.spikeMarkers().hooks, undefined);
    assert.equal(view.toggle.hidden, true);
});


// The drawn axis must honour the typical-latency maximum even when the plotted line spikes
// (chart-engine would otherwise grow the range to the highest data point).
function withRealEngine() {
    const element = () => ({tagName: 'DIV', style: {}, offsetWidth: 800, offsetHeight: 400, closest: () => null});
    const elements = new Map();
    const toggle = {dataset: {}, hidden: true, classList: {toggle() {}}, setAttribute() {}, addEventListener(t, h) { toggle.onclick = h; }};
    function Chart(options, data) { Object.assign(this, {options, data, destroy() {}}); }
    Chart.paths = {bars: () => () => {}, stepped: () => () => {}};
    const context = {
        document: {getElementById(id) {
            if (id === 'cm-spikes-toggle') return toggle;
            if (!elements.has(id)) elements.set(id, element());
            return elements.get(id);
        }, documentElement: {getAttribute: () => 'dark'}},
        uPlot: Chart, T: {}, setTimeout: fn => fn(), requestAnimationFrame: fn => fn(),
        ResizeObserver: class {observe() {} disconnect() {}},
        DOCSightModal: {open() {}, close() {}},
        docsightFormatXAxisLabels: timestamps => timestamps.map(String),
        localStorage: {getItem: () => null, setItem() {}},
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/static/js/chart-engine.js', 'utf8'), context);
    vm.runInNewContext(
        fs.readFileSync('app/modules/connection_monitor/static/js/connection-monitor-charts.js', 'utf8') +
        '\nwindow.CMCharts = CMCharts;',
        context,
    );
    return {
        render: data => context.CMCharts.renderCombinedChart('cm-combined-chart', data, 86400),
        yRange: (dmin, dmax) => Array.from(context.charts['cm-combined-chart'].options.scales.y.range({}, dmin, dmax)),
        toggle,
    };
}

test('drawn axis stays at typical latency when a raw line sample spikes', () => {
    const view = withRealEngine();
    view.render([rawTarget(typicalWithOneSpike)]);
    assert.deepEqual(view.yRange(0, 550), [0, 40]);
    view.toggle.onclick();
    assert.deepEqual(view.yRange(0, 550), [0, 633]);
});
