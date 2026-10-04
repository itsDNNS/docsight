'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const data = require('../../app/static/js/correlation-data.js');

test('range strings map to hours with a one-day fallback', () => {
    assert.equal(data.rangeHours('6h'), 6);
    assert.equal(data.rangeHours('7d'), 168);
    assert.equal(data.rangeHours('3'), 3);
    assert.equal(data.rangeHours(undefined), 24);
    assert.equal(data.rangeHours('week'), 24);
});

test('unknown or missing severities count as info', () => {
    assert.equal(data.normalizeSeverity({severity: 'CRITICAL'}), 'critical');
    assert.equal(data.normalizeSeverity({severity: 'fatal'}), 'info');
    assert.equal(data.normalizeSeverity(null), 'info');
});

test('only finite non-negative numbers are measurements', () => {
    assert.equal(data.measurement(0), 0);
    assert.equal(data.measurement(812.4), 812.4);
    for (const value of [-1, NaN, Infinity, '12', null, undefined]) assert.equal(data.measurement(value), null);
});

test('sample coverage uses the bucket width, else the target poll interval', () => {
    assert.deepEqual(data.sampleInterval({timestamp: 10, bucket_seconds: 60}, {}), {startMs: 10000, endMs: 70000});
    assert.deepEqual(data.sampleInterval({timestamp: 10}, {poll_interval_ms: 5000}), {startMs: 10000, endMs: 15000});
    assert.equal(data.sampleInterval({timestamp: 10}, {}), null);
    assert.equal(data.sampleInterval({timestamp: 'x', bucket_seconds: 60}, {}), null);
});

const target = (id, samples) => ({target: {id, label: `T${id}`, poll_interval_ms: 1000}, samples});

test('reachability buckets weight loss by samples and keep gaps unknown', () => {
    const buckets = data.bucketReachability([
        target(1, [{timestamp: 0, bucket_seconds: 10, packet_loss_pct: 0, sample_count: 3}]),
        target(2, [{timestamp: 0, bucket_seconds: 10, packet_loss_pct: 40, sample_count: 1}]),
    ], 0, 20000, 2);

    assert.equal(buckets.length, 2);
    assert.equal(buckets[0].state, 'degraded');
    assert.equal(buckets[0].lossPct, 10);
    assert.equal(buckets[0].sampleCount, 4);
    assert.equal(buckets[0].targetScope, 'T1 | T2');
    assert.equal(buckets[1].state, 'unknown');
    assert.equal(buckets[1].lossPct, null);
});

test('reachability is down only when every observed sample lost everything', () => {
    const down = data.bucketReachability([target(1, [{timestamp: 0, bucket_seconds: 10, packet_loss_pct: 100}])], 0, 10000, 1);
    const ok = data.bucketReachability([target(1, [{timestamp: 0, bucket_seconds: 10, packet_loss_pct: 0}])], 0, 10000, 1);
    assert.equal(down[0].state, 'down');
    assert.equal(ok[0].state, 'ok');
});

test('reachability ignores invalid loss and caps the bucket count', () => {
    const invalid = data.bucketReachability([target(1, [{timestamp: 0, bucket_seconds: 10, packet_loss_pct: 140}])], 0, 10000, 1);
    assert.equal(invalid[0].state, 'unknown');
    assert.equal(data.bucketReachability([], 0, 1000000, 5000).length, 300);
    assert.deepEqual(data.bucketReachability([], 10, 10, 5), []);
});

const parse = ts => new Date(ts);
const identity = value => value;

test('speed marks stay discrete and only separate download and upload when there is room', () => {
    const marks = data.buildSpeedMarks([
        {timestamp: '2026-10-01T00:00:00Z', download_mbps: 200, upload_mbps: 40},
        {timestamp: '2026-10-01T00:00:01Z', download_mbps: 210, upload_mbps: null},
        {timestamp: '2026-10-02T00:00:00Z', download_mbps: 220, upload_mbps: 41},
    ], ms => ms / 1000, identity, Date.parse('2026-09-30T00:00:00Z'), Date.parse('2026-10-03T00:00:00Z'),
    {download: true, upload: true}, parse);

    assert.deepEqual(marks.map(mark => mark.visible), [true, true, true]);
    // The first two tests are one second apart: thin stems, no separation.
    assert.equal(marks[0].offset, 0);
    assert.equal(marks[0].stemWidth, 1);
    assert.equal(marks[1].hasUpload, false);
    // The last test has room, so download and upload sit side by side.
    assert.ok(marks[2].offset > 0);
    assert.equal(marks[2].downloadX < marks[2].uploadX, true);
    assert.equal(marks[2].headRadius, 3.5);
});

test('a single visible speedtest gets a larger head and hidden tests stay hidden', () => {
    const marks = data.buildSpeedMarks([
        {timestamp: '2026-10-01T00:00:00Z', download_mbps: 200, upload_mbps: 40},
        {timestamp: '2026-11-01T00:00:00Z', download_mbps: 200, upload_mbps: 40},
    ], ms => ms / 1000, identity, Date.parse('2026-09-30T00:00:00Z'), Date.parse('2026-10-03T00:00:00Z'),
    {download: true, upload: true}, parse);

    assert.equal(marks[0].headRadius, 4.5);
    assert.equal(marks[1].visible, false);
});

test('CSV cells neutralize formulas and quote separators', () => {
    assert.equal(data.encodeCSVCell('=SUM(A1)'), "'=SUM(A1)");
    assert.equal(data.encodeCSVCell('  +1'), "'  +1");
    assert.equal(data.encodeCSVCell('a,b'), '"a,b"');
    assert.equal(data.encodeCSVCell('say "hi"'), '"say ""hi"""');
    assert.equal(data.encodeCSVCell(null), '');
    assert.equal(data.encodeCSVCell(42), 42);
});

test('CSV rows hold timeline entries and reachability buckets under one header', () => {
    const rows = data.csvRows(
        [{timestamp: '2026-10-01T00:00:00Z', source: 'modem', health: 'good', message: '=evil'}],
        [{startMs: 0, endMs: 60000, state: 'degraded', lossPct: 12.345678, sampleCount: 4, targetScope: 'T1'}],
    );
    const header = rows[0].split(',');

    assert.equal(rows.length, 3);
    assert.deepEqual(header.slice(0, 3), ['timestamp', 'source', 'health']);
    assert.ok(header.includes('target_scope'));
    assert.ok(rows[1].includes("'=evil"));
    assert.ok(rows[2].startsWith('1970-01-01T00:00:00.000Z,connection_monitor,'));
    assert.ok(rows[2].includes('degraded,12.3457,4,'));
});
