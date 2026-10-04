'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const data = require('../../app/static/js/event-log-data.js');

const ev = (id, timestamp, eventType, severity = 'info', acknowledged = 0) =>
    ({id, timestamp, event_type: eventType, severity, acknowledged});

test('unknown severities count as info and the worst severity wins', () => {
    assert.equal(data.severity({severity: 'CRITICAL'}), 'critical');
    assert.equal(data.severity({severity: 'fatal'}), 'info');
    assert.equal(data.severity(null), 'info');
    assert.equal(data.worstSeverity([ev(1, '', 'x', 'info'), ev(2, '', 'x', 'critical'), ev(3, '', 'x', 'warning')]), 'critical');
    assert.equal(data.worstSeverity([]), 'info');
});

test('the day comes from the localized timestamp', () => {
    assert.equal(data.dayKey({timestamp: '2026-10-04T23:59:59'}), '2026-10-04');
    assert.equal(data.dayKey({timestamp: 'garbage'}), '');
});

test('consecutive events of one type on one day collapse into a run', () => {
    const days = data.buildTimeline([
        ev(9, '2026-10-04T18:00:00', 'health_change', 'warning'),
        ev(8, '2026-10-04T17:30:00', 'health_change', 'info', 1),
        ev(7, '2026-10-04T17:00:00', 'health_change', 'warning'),
        ev(6, '2026-10-04T16:00:00', 'error_spike', 'warning'),
        ev(5, '2026-10-04T15:00:00', 'health_change', 'info'),
    ]);

    assert.equal(days.length, 1);
    assert.equal(days[0].day, '2026-10-04');
    assert.equal(days[0].count, 5);
    const [run, spike, single] = days[0].items;
    assert.equal(run.kind, 'group');
    assert.equal(run.key, 'g9');
    assert.deepEqual(run.events.map(e => e.id), [9, 8, 7]);
    assert.equal(run.severity, 'warning');
    assert.equal(run.newest.id, 9);
    assert.equal(run.oldest.id, 7);
    assert.equal(run.unacknowledged, 2);
    // A different type in between ends the run; the later health change stays single.
    assert.deepEqual([spike.kind, spike.key], ['event', 'e6']);
    assert.deepEqual([single.kind, single.event.id], ['event', 5]);
});

test('runs never cross midnight', () => {
    const days = data.buildTimeline([
        ev(2, '2026-10-04T00:10:00', 'channel_change'),
        ev(1, '2026-10-03T23:50:00', 'channel_change'),
    ]);
    assert.deepEqual(days.map(d => d.day), ['2026-10-04', '2026-10-03']);
    assert.deepEqual(days.map(d => d.items[0].kind), ['event', 'event']);
    assert.deepEqual(data.buildTimeline(undefined), []);
});

test('acknowledgement bookkeeping only touches open events', () => {
    const events = [ev(1, '', 'x'), ev(2, '', 'x', 'info', 1), ev(3, '', 'x')];
    assert.deepEqual(data.unacknowledgedIds(events), [1, 3]);
    assert.equal(data.markAcknowledged(events, [2, 3, 99]), 1);
    assert.deepEqual(data.unacknowledgedIds(events), [1]);
    assert.equal(data.markAcknowledged(events, []), 0);
});
