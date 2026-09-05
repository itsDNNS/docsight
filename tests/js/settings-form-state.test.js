'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const state = require('../../app/static/js/settings/form-state.js');
const field = (overrides = {}) => state.record({name: 'field', type: 'text', value: 'old', ...overrides});

test('identity preserves type, repeated controls and delimiter-containing names', () => {
    const records = [field(), field({type: 'hidden'}), field({index: 1}),
        field({name: 'a:b', id: 'c'}), field({name: 'a', id: 'b:c'})];
    assert.equal(new Set(records.map(r => r.key)).size, records.length);
    assert.equal(state.dirty(records, [...records].reverse()), false);
});

test('manual projection uses record classification including hidden companions', () => {
    const baseline = [field(), field({name: 'font_family', type: 'hidden', instant: true})];
    const current = [baseline[0], field({name: 'font_family', type: 'hidden', instant: true, value: 'new'})];
    assert.equal(state.dirty(current, baseline), true);
    assert.equal(state.dirty(current, baseline, true), false);
    assert.equal(state.dirty([field({value: 'later'}), current[1]], baseline, true), true);
});

test('config acknowledgement leaves modules pending and preserves subsequent edits', () => {
    const module = field({name: 'toggle', owner: 'module', instant: true});
    const baseline = [field(), module];
    const sent = [field({value: 'sent'}), {...module, value: '1'}];
    const acknowledged = state.acknowledge(baseline, sent, 'config');
    assert.equal(state.dirty(sent, acknowledged), true);
    assert.equal(state.dirty(sent, acknowledged, true), false);
    assert.equal(state.dirty(sent, state.acknowledge(acknowledged, sent, 'module')), false);
    assert.equal(state.dirty([field({value: 'later'}), sent[1]], acknowledged, true), true);
    assert.equal(baseline[0].value, 'old');
});

test('all secrets exclude actual values and compare monotonically increasing edit versions', () => {
    const initial = field({secret: true, value: 'initial-unsaved-secret'});
    const sent = field({secret: true, value: 'first-secret', secretEditVersion: 1});
    const later = field({secret: true, value: 'second-secret', secretEditVersion: 2});
    assert.equal(JSON.stringify([initial, sent, later]).includes('secret"'), false);
    assert.equal('value' in initial, false);
    assert.equal(state.dirty([sent], [initial]), true);
    const baseline = state.acknowledge([initial], [sent], 'config');
    assert.equal(state.dirty([later], baseline), true);
    assert.equal(state.dirty([field({secret: true, secretEditVersion: 1})], baseline), false);
});

test('removed fields, module reversions and multiple selections remain distinguishable', () => {
    assert.equal(state.dirty([], [field()]), true);
    assert.equal(state.dirty([field({value: ['a', 'b']})], [field({value: ['a\u0000b']})]), true);
    const module = field({owner: 'module', value: '0'});
    const saved = state.acknowledge([module], [{...module, value: '1'}], 'module');
    assert.equal(state.dirty([module], saved), true);
});
