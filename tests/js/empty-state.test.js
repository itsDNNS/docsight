'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const emptyState = require('../../app/static/js/empty-state.js');

const tabs = (...flags) => flags.map((active, i) => ({label: `${i}d`, active}));

test('the longest range is offered unless it is already selected', () => {
    assert.equal(emptyState.widerRange(tabs(true, false, false)).label, '2d');
    assert.equal(emptyState.widerRange(tabs(false, true, false)).label, '2d');
    assert.equal(emptyState.widerRange(tabs(false, false, true)), null);
    assert.equal(emptyState.widerRange([]), null);
    assert.equal(emptyState.widerRange(undefined), null);
});
