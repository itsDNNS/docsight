'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load() {
    const context = {};
    vm.runInNewContext(fs.readFileSync('app/static/js/utils.js', 'utf8'), context);
    return context;
}

test('escapeHtml also escapes quotes, so attribute values cannot break out', () => {
    const {escapeHtml} = load();
    assert.equal(escapeHtml(`x" onfocus='y' <b>&`), 'x&quot; onfocus=&#39;y&#39; &lt;b&gt;&amp;');
    assert.equal(escapeHtml(42), '42');
    assert.equal(escapeHtml(null), 'null');
});
