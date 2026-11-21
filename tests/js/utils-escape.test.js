'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load(globals = {}) {
    const context = {...globals};
    vm.runInNewContext(fs.readFileSync('app/static/js/utils.js', 'utf8'), context);
    return context;
}

test('escapeHtml also escapes quotes, so attribute values cannot break out', () => {
    const {escapeHtml} = load();
    assert.equal(escapeHtml(`x" onfocus='y' <b>&`), 'x&quot; onfocus=&#39;y&#39; &lt;b&gt;&amp;');
    assert.equal(escapeHtml(42), '42');
    assert.equal(escapeHtml(null), 'null');
});

test('docsightJson resolves the JSON answer and rejects failed requests and non-2xx answers', async () => {
    const answers = [{ok: true, json: async () => ({id: 1})}, {ok: false, status: 503}, new Error('offline')];
    const calls = [];
    const {docsightJson} = load({
        docsightUrl: path => '/base' + path,
        fetch: async (url, options) => {
            calls.push([url, options]);
            const answer = answers.shift();
            if (answer instanceof Error) throw answer;
            return answer;
        },
    });
    assert.deepEqual(await docsightJson('/api/x', {method: 'POST'}), {id: 1});
    assert.deepEqual(calls[0], ['/base/api/x', {method: 'POST'}]);
    await assert.rejects(docsightJson('/api/x'), /503/);
    await assert.rejects(docsightJson('/api/x'), /offline/);
});
