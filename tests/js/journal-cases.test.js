'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load() {
    const context = {T: {}, document: {}};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/modules/journal/static/js/journal-cases.js', 'utf8'), context);
    return context;
}

test('the overview shows open cases first, then the newest start, at most six', () => {
    const cases = [
        {id: 1, status: 'resolved', start_date: '2026-09-01'},
        {id: 2, status: 'open', start_date: '2026-07-08'},
        {id: 3, status: 'resolved', start_date: '2026-09-21'},
        {id: 4, status: 'open', start_date: '2026-10-01'},
        {id: 5, status: 'escalated', start_date: null},
        {id: 6, status: 'resolved', start_date: '2026-01-01'},
        {id: 7, status: 'resolved', start_date: '2025-12-01'},
    ];
    const order = load().journalCaseOrder(cases).map(c => c.id);
    assert.deepEqual(order, [4, 2, 3, 1, 6, 7]);
    assert.deepEqual(Array.from(load().journalCaseOrder(null)), []);
});

test('evidence counts leave the report out and name the first missing and stale source', () => {
    const evidence = load().journalCaseEvidence({items: [
        {key: 'report', status: 'missing'},
        {key: 'speedtest', status: 'present'},
        {key: 'bqm', status: 'stale'},
        {key: 'notes', status: 'missing'},
        {key: 'smokeping', status: 'missing'},
        {key: 'bnetz', status: 'not_applicable'},
    ]});
    assert.deepEqual([evidence.ready, evidence.stale, evidence.missing], [1, 1, 2]);
    assert.equal(evidence.items.length, 5);
    assert.equal(evidence.firstMissing.key, 'notes');
    assert.equal(evidence.firstStale.key, 'bqm');
    assert.equal(load().journalCaseEvidence({}).firstMissing, null);
});
