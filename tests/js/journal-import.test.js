'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load() {
    const context = {document: {getElementById: () => null, querySelectorAll: () => []}, T: {}};
    context.window = context;
    // The dialog sends its requests through the journal's request helper in journal-entry.js.
    for (const file of ['journal-entry.js', 'journal-import.js']) {
        vm.runInNewContext(fs.readFileSync('app/modules/journal/static/js/' + file, 'utf8'), context);
    }
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

test('the upload sends the UI language and frees the picker so the same file can be retried', async () => {
    let url;
    const status = {};
    const context = load();
    Object.assign(context, {
        document: {documentElement: {lang: 'de'}, getElementById: () => status},
        docsightUrl: (route) => route,
        FormData: class { append() {} },
        fetch: async (route) => { url = route; return {status: 400, json: async () => ({error: 'Unlesbar'})}; },
    });
    const input = {files: [{name: 'journal.csv', size: 10}], value: 'journal.csv'};
    context.handleImportFile(input);
    await new Promise(setImmediate);
    assert.equal(url, '/api/journal/import/preview?lang=de');
    assert.equal(input.value, '');
    assert.equal(status.textContent, 'Unlesbar');
});
