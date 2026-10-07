'use strict';

/* Event messages rendered by events.js. These ran as one Node process per
   case from Python; loading events.js once here keeps them off slow process
   starts on busy Windows runners. */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const context = {
    T: {},
    escapeHtml: s => String(s),
    docsightUrl: url => url,
    document: {getElementById: () => null, querySelectorAll: () => [], addEventListener() {}},
    fetch: () => ({then: () => ({then: () => ({catch() {}})})}),
    setInterval() {},
    console,
};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/events.js'), 'utf8'), context);

const snrChange = affected => context.formatEventMessage({
    id: 1, timestamp: '2026-01-01T00:00:00', severity: 'warning', event_type: 'snr_change', message: 'snr drop',
    details: {threshold: 'warning', prev: 36.0, current: 31.0, affected_channels: affected},
});

test('modulation changes name the channel type, DOCSIS version and frequency', () => {
    const html = context.formatEventMessage({
        id: 1, timestamp: '2026-01-01T00:00:00', severity: 'critical', event_type: 'modulation_change',
        message: 'Modulation dropped on 1 channel(s)',
        details: {direction: 'downgrade', changes: [{
            channel: 5, direction: 'US', prev: 'qam_64', current: 'qam_8', rank_drop: 3,
            docsis_version: '3.0', channel_type: 'SC-QAM', frequency: '37 MHz',
        }]},
    });
    for (const part of ['US Ch 5', 'SC-QAM', 'DOCSIS 3.0', '37 MHz', 'qam_64', 'qam_8']) assert.ok(html.includes(part), part);
});

test('SNR changes skip malformed affected entries and keep the valid one', () => {
    const html = snrChange([null, 'not-an-object', 42, true, {channel: 5, prev: 36.0, current: 31.0, delta: -5.0}]);
    assert.ok(html.includes('Ch 5'));
    assert.ok(!html.includes('TypeError'));
});

test('SNR changes render when every affected entry is malformed', () => {
    assert.equal(typeof snrChange([null, null, 'x', 0]), 'string');
});

for (const malformed of ['not-an-array', 42, true, {channel: 5, current: 30.0}]) {
    test(`SNR changes keep their summary when affected_channels is ${JSON.stringify(malformed)}`, () => {
        const html = snrChange(malformed);
        assert.ok(html.includes('<span class="ev-val">36</span>'));
        assert.ok(html.includes('<span class="ev-val ev-warn">31</span> dB'));
        assert.ok(!html.includes('TypeError'));
    });
}
