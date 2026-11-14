'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync('app/static/js/trusted-html.js', 'utf8');

test('HTML goes through the one docsight policy where Trusted Types exist', () => {
    const created = [];
    const context = {trustedTypes: {createPolicy(name, rules) {
        created.push(name);
        return {createHTML: html => ({trusted: rules.createHTML(html)})};
    }}};
    context.window = context;
    vm.runInNewContext(source, context);
    assert.deepEqual(created, ['docsight']);
    assert.deepEqual(context.docsightHTML('<b>x</b>'), {trusted: '<b>x</b>'});
});

test('without Trusted Types the markup stays a string', () => {
    const context = {};
    context.window = context;
    vm.runInNewContext(source, context);
    assert.equal(context.docsightHTML('<b>x</b>'), '<b>x</b>');
});
