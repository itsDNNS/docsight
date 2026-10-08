'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load() {
    const context = {T: {}, document: {}, docsightParseTime: value => new Date(value)};
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
