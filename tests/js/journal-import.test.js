'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load() {
    const context = {document: {getElementById: () => null, querySelectorAll: () => []}, T: {}};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/modules/journal/static/js/journal-import.js', 'utf8'), context);
    return context;
}

const rows = [
    {date: '2026-10-01', title: 'Outage', description: 'no sync'},
    {date: '2026-10-02', title: 'Call', duplicate: true},
    {date: null, title: 'Letter', skipped: true, raw_date: '32.13.2026'},
    {date: '2026-10-03', title: 'Fixed later', skipped: true},
];

test('rows count as ready, duplicate, or missing a date', () => {
    const summary = load().journalImportSummary(rows);
    assert.deepEqual({...summary}, {ready: 1, duplicates: 1, needsDate: 2});
});

test('only selected rows with a date are imported, with date, title and description', () => {
    const selected = load().journalImportRows(rows, [0, 2, 3, 9]);
    assert.deepEqual(JSON.parse(JSON.stringify(selected)), [
        {date: '2026-10-01', title: 'Outage', description: 'no sync'},
        {date: '2026-10-03', title: 'Fixed later'},
    ]);
});
