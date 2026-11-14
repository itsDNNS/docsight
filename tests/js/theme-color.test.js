'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

test('theme colors are resolved once per mode and theme styles', () => {
    let mode = 'dark';
    const colors = {dark: 'rgb(10, 20, 30)', light: 'rgb(200, 210, 220)'};
    let reads = 0;
    const context = {
        document: {
            body: {appendChild() {}},
            documentElement: {lang: 'en', getAttribute: () => mode},
            styleSheets: {length: 3},
            createElement: () => ({style: {}}),
            getElementById: () => null,
        },
        getComputedStyle() { reads += 1; return {color: colors[mode]}; },
        T: {},
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/static/js/chart-engine.js', 'utf8'), context);

    assert.equal(context.docsightThemeColor('--text-secondary', 0.35), 'rgba(10,20,30,0.35)');
    assert.equal(context.docsightThemeColor('--text-secondary', 1), 'rgba(10,20,30,1)');
    assert.equal(reads, 1);

    mode = 'light';
    assert.equal(context.docsightThemeColor('--text-secondary', 1), 'rgba(200,210,220,1)');
    context.document.styleSheets.length = 4;
    context.docsightThemeColor('--text-secondary', 1);
    assert.equal(reads, 3);
});
