'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const root = path.resolve(__dirname, '../..');

function browser(hash, view) {
    const writes = [];
    const context = {
        URLSearchParams, currentView: view,
        location: {hash},
        history: {replaceState(_state, _title, url) { writes.push(url); context.location.hash = url; }},
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(root, 'app/static/js/view-state.js'), 'utf8'), context);
    return {context, writes};
}

test('state is read only for the view the hash names', () => {
    const {context} = browser('#modulation?dir=ds&days=30', 'modulation');
    assert.deepEqual({...context.docsightReadViewState('modulation')}, {dir: 'ds', days: '30'});
    assert.deepEqual({...context.docsightReadViewState('trends')}, {});
    assert.deepEqual({...browser('#modulation', 'modulation').context.docsightReadViewState('modulation')}, {});
    assert.deepEqual({...browser('#mod?x=1', 'mod').context.docsightReadViewState('modulation')}, {});
});

test('writes skip empty values, other views and unchanged hashes', () => {
    const {context, writes} = browser('#events', 'events');
    context.docsightWriteViewState('events', {severity: 'warning', device: '', operational: null});
    assert.deepEqual(writes, ['#events?severity=warning']);
    context.docsightWriteViewState('events', {severity: 'warning'});
    assert.equal(writes.length, 1);
    context.docsightWriteViewState('trends', {range: '7d'});
    assert.equal(writes.length, 1);
    context.docsightWriteViewState('events', {});
    assert.deepEqual(writes, ['#events?severity=warning', '#events']);
});

test('values are encoded and decoded', () => {
    const {context, writes} = browser('#speedtest', 'speedtest');
    context.docsightWriteViewState('speedtest', {range: 'a b&c'});
    assert.deepEqual(writes, ['#speedtest?range=a+b%26c']);
    assert.equal(context.docsightReadViewState('speedtest').range, 'a b&c');
});
