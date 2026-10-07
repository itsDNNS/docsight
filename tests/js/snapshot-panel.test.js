'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function panel() {
    const context = {T: {}, document: {readyState: 'complete', getElementById: () => null}, addEventListener() {}};
    context.window = context;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/snapshot-panel.js'), 'utf8'), context);
    return context.DOCSightSnapshotPanel;
}

test('new uncorrectable errors are the counter change since the snapshot before', () => {
    const p = panel();
    assert.equal(p.newErrors({ds_uncorrectable_errors: 140}, 100), 40);
    // A modem restart reset the counter: its new value is what is new.
    assert.equal(p.newErrors({ds_uncorrectable_errors: 12}, 5000), 12);
    assert.equal(p.newErrors({ds_uncorrectable_errors: 140}, null), null);
    assert.equal(p.newErrors({ds_uncorrectable_errors: null}, 100), null);
});

test('the weakest channels come first: worst health, then lowest SNR', () => {
    const p = panel();
    const channels = [
        {channel_id: 1, health: 'good', snr: 34},
        {channel_id: 2, health: 'critical', snr: 38},
        {channel_id: 3, health: 'good', snr: 31},
        {channel_id: 4, health: 'marginal', snr: 36},
        {channel_id: 5, health: 'good', snr: null},
        {channel_id: 6, health: 'good', snr: 40},
    ];
    assert.deepEqual(Array.from(p.weakestChannels(channels), c => c.channel_id), [2, 4, 3, 1]);
    assert.deepEqual(Array.from(p.weakestChannels(undefined)), []);
});
