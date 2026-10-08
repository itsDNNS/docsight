'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load() {
    const context = {T: {}, document: {getElementById: () => null}};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/modules/journal/static/js/journal-entry.js', 'utf8'), context);
    return context;
}

test('an entry is saved with trimmed text and its case as a number', () => {
    const entry = load().journalEntryPayload({date: '2026-10-08', title: '  Outage ', description: ' no sync\n', icon: 'phone', incident: '3'});
    assert.deepEqual({...entry}, {date: '2026-10-08', title: 'Outage', description: 'no sync', icon: 'phone', incident_id: 3});
});

test('without a case, icon or description the entry keeps empty values', () => {
    const entry = load().journalEntryPayload({date: '2026-10-08', title: 'Call', incident: ''});
    assert.deepEqual({...entry}, {date: '2026-10-08', title: 'Call', description: '', icon: '', incident_id: null});
});
