'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
    path.join(__dirname, '../../app/static/js/url-contract.js'),
    'utf8'
);

function loadUrlContract(bootstrapText, hasElement = true) {
    const window = {};
    vm.runInNewContext(source, {
        window,
        document: {
            getElementById(id) {
                if (!hasElement || id !== 'docsight-url-bootstrap') return null;
                return {textContent: bootstrapText};
            }
        },
        Object,
        JSON,
        TypeError,
        Error,
        encodeURIComponent,
        parseInt
    });
    return window.docsightUrl;
}

test('docsightUrl preserves root behavior and applies a validated mount prefix once', () => {
    const root = loadUrlContract('{"basePath":""}');
    const prefixed = loadUrlContract('{"basePath":"/docsight"}');

    assert.equal(root('/api/poll?q=a%20b#status'), '/api/poll?q=a%20b#status');
    assert.equal(prefixed('/api/poll?q=a%20b#status'), '/docsight/api/poll?q=a%20b#status');
    assert.equal(prefixed('/docsight/api/poll'), '/docsight/api/poll');
});

test('docsightUrl rejects unsafe paths without weakening the production contract', () => {
    const docsightUrl = loadUrlContract('{"basePath":"/docsight"}');
    for (const unsafe of [
        null,
        '',
        'api/poll',
        '//evil.test/path',
        'https://evil.test/',
        '/api/../secret',
        '/api/%2e%2e/secret',
        '/api/%252fsecret',
        '/api\\poll',
        '/api/%GG'
    ]) {
        assert.throws(() => docsightUrl(unsafe), /safe root-relative internal URL/);
    }
});

test('url bootstrap fails closed when absent, malformed, or the wrong shape', () => {
    for (const [text, present] of [
        ['{', true],
        ['null', true],
        ['{}', true],
        ['{"basePath":"//evil"}', true],
        ['{"basePath":"","token":"secret"}', true],
        ['', false]
    ]) {
        assert.throws(() => loadUrlContract(text, present), /URL contract is unavailable/);
    }
});
