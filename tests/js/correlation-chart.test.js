'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const chart = require('../../app/static/js/correlation-chart.js');

const HOUR = 3600000;
const T0 = Date.UTC(2026, 9, 7, 0, 0);
const at = h => new Date(T0 + h * HOUR).toISOString();
const parseTime = s => new Date(s);
const ALL = {snr: true, txPower: true, dsPower: true, download: true, upload: true, events: true, errors: true,
    signalState: true, temperature: true, segmentDs: true, segmentUs: false, reachability: true};
const colors = chart.colors((prop, fallback) => fallback);

function modem(h, values) {
    return Object.assign({source: 'modem', timestamp: at(h), ds_power_avg: 3, us_power_avg: 42, ds_snr_min: 38,
        ds_uncorrectable_errors: 0, health: 'good'}, values);
}

function build(data, options = {}) {
    const visible = Object.assign({}, ALL, options.visible);
    const prep = chart.prepare({data, weather: options.weather, segment: options.segment, targets: options.targets, visible});
    const st = chart.scales(prep, Object.assign({
        width: 800, visible, selectedRange: {startMs: T0, endMs: T0 + 24 * HOUR},
        measure: text => text.length * 7, parseTime, colors,
    }, options.scales));
    return {prep, st};
}

/* Records what draw() does with the context. */
function recorder() {
    const calls = [];
    const ctx = new Proxy({calls}, {
        get(target, name) {
            if (name in target) return target[name];
            return (...args) => { calls.push([name, ...args]); };
        },
        set(target, name, value) { calls.push(['set', name, value]); target[name] = value; return true; },
    });
    return ctx;
}

const LABELS = {state: 'state', errors: 'errors', speed: 'speed', segment: 'segment', events: 'events', reachability: 'reach'};

test('only sources with data and a visible series get a lane, in display order', () => {
    const data = [modem(1, {ds_uncorrectable_errors: 0}), modem(2, {ds_uncorrectable_errors: 40}),
        {source: 'speedtest', timestamp: at(3), download_mbps: 900, upload_mbps: 40}];
    const shown = chart.prepare({data, visible: ALL});
    assert.deepEqual(shown.layout.order, ['state', 'errors', 'speed']);
    assert.equal(shown.empty, false);

    const hidden = chart.prepare({data, visible: Object.assign({}, ALL, {download: false, upload: false, errors: false})});
    assert.deepEqual(hidden.layout.order, ['state']);
    assert.ok(hidden.layout.height < shown.layout.height);

    assert.equal(chart.prepare({data: [{source: 'event', timestamp: at(1)}], visible: ALL}).empty, true);
});

test('DS and US power share one axis two units beyond the values; hidden power leaves the SNR scale', () => {
    const {st} = build([modem(1, {ds_power_avg: -1.2, us_power_avg: 44.5}), modem(2, {ds_power_avg: 2, us_power_avg: 46})]);
    assert.deepEqual([st.txMin, st.txMax], [-4, 48]);
    assert.equal(st.yTx, st.yDsPower);
    assert.equal(st.yTx(st.txMin), st.layout.main.y + st.layout.main.height);
    assert.equal(st.yTx(st.txMax), st.layout.main.y);
    assert.deepEqual([st.snrMin, st.snrMax], [36, 40]);
    assert.equal(st.show.snr, true);
});

test('the time axis spans the selected range, or the zoom, between the paddings', () => {
    const {st} = build([modem(1), modem(2)]);
    assert.equal(st.xScale(T0), st.pad.left);
    assert.equal(st.xScale(T0 + 24 * HOUR), st.pad.left + st.plotW);
    assert.equal(st.plotW, 800 - st.pad.left - st.pad.right);

    const zoomed = build([modem(1), modem(2)], {scales: {zoom: {tMin: T0 + HOUR, tMax: T0 + 2 * HOUR}}}).st;
    assert.equal(zoomed.xScale(T0 + HOUR), zoomed.pad.left);
    assert.equal(zoomed.tMinFull, T0);

    const none = chart.scales(chart.prepare({data: [], visible: ALL}),
        {width: 800, visible: ALL, measure: () => 0, parseTime, colors});
    assert.equal(none, null);
});

test('SNR and temperature each widen the right padding; Fahrenheit converts the band', () => {
    const weather = [{timestamp: at(1), temperature: 10}, {timestamp: at(2), temperature: 20}];
    const plain = build([modem(1), modem(2)], {visible: {snr: false}}).st;
    const withSnr = build([modem(1), modem(2)]).st;
    const withBoth = build([modem(1), modem(2)], {weather}).st;
    assert.ok(withSnr.pad.right > plain.pad.right);
    assert.ok(withBoth.pad.right > withSnr.pad.right);
    assert.deepEqual([withBoth.tempMin, withBoth.tempMax, withBoth.tempUnit], [8, 22, '°C']);

    const f = build([modem(1), modem(2)], {weather, scales: {fahrenheit: true}}).st;
    assert.deepEqual([f.tempMin, f.tempMax, f.tempUnit], [48, 70, '°F']);
    assert.equal(f.yTemp(20), f.bandY(68, 48, 70));
});

test('drawing fills one background per lane and marks events by severity', () => {
    const data = [modem(1), modem(2, {ds_uncorrectable_errors: 40}),
        {source: 'speedtest', timestamp: at(3), download_mbps: 900, upload_mbps: 40},
        {source: 'event', timestamp: at(4), severity: 'critical'},
        {source: 'event', timestamp: at(5), severity: 'warning'},
        {source: 'event', timestamp: at(6), severity: 'info'}];
    const {st} = build(data);
    const ctx = recorder();
    chart.draw(ctx, st, {visible: ALL, events: st.events, labels: LABELS, parseTime, axisLabel: t => String(t)});

    const laneFills = ctx.calls.filter(c => c[0] === 'fillRect' && c[3] === st.plotW);
    assert.deepEqual(laneFills.map(c => c[2]), st.layout.order.map(key => st.layout.lanes[key].y));
    // Critical is a filled diamond; warning and info are outlines.
    const shapes = ctx.calls.filter(c => c[0] === 'fill' || c[0] === 'stroke' || c[0] === 'closePath' || c[0] === 'arc')
        .map(c => c[0]);
    assert.ok(shapes.join(' ').includes('closePath fill closePath stroke arc stroke'), shapes.join(' '));
    // Speedtests are stems and heads: one arc per measured direction.
    const heads = ctx.calls.filter(c => c[0] === 'arc' && c[3] === st.speedMarks[0].headRadius);
    assert.equal(heads.length, 2);
    // The time axis has one label per 80 px, at most nine.
    const axisLabels = ctx.calls.filter(c => c[0] === 'fillText' && c[3] === st.layout.axisY + 14);
    assert.equal(axisLabels.length, Math.min(8, Math.floor(st.plotW / 80)) + 1);
});

test('hidden speed directions draw no marks', () => {
    const data = [modem(1), {source: 'speedtest', timestamp: at(3), download_mbps: 900, upload_mbps: 40}];
    const {st} = build(data);
    const ctx = recorder();
    chart.drawSpeedMarks(ctx, st.speedMarks, st.yDl(0), colors, {download: true, upload: false});
    assert.equal(ctx.calls.filter(c => c[0] === 'arc').length, 1);
});

test('the nearest point respects skipped items, and a dot is a filled circle with a ring', () => {
    const items = [{timestamp: at(1)}, {timestamp: at(2)}, {timestamp: at(5)}];
    assert.equal(chart.nearestIndex(items, T0 + 2.2 * HOUR, parseTime), 1);
    assert.equal(chart.nearestIndex(items, T0 + 2.2 * HOUR, parseTime, i => i === 1), 0);
    assert.equal(chart.nearestIndex([], T0, parseTime), -1);

    const ctx = recorder();
    chart.drawDot(ctx, 10, 20, 5, 'red');
    assert.deepEqual(ctx.calls.map(c => c[0] === 'set' ? c[1] + '=' + c[2] : c[0]),
        ['beginPath', 'arc', 'fillStyle=red', 'fill', 'strokeStyle=#fff', 'lineWidth=2', 'stroke']);
});
