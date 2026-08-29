'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const source = fs.readFileSync(
    path.join(__dirname, '../../app/modules/de_tkg_compensation/static/main.js'),
    'utf8'
);
const template = fs.readFileSync(
    path.join(__dirname, '../../app/modules/de_tkg_compensation/templates/tkg_tab.html'),
    'utf8'
);

test('TKG wizard routes every local API and generated link through docsightUrl', () => {
    assert.match(source, /fetch\(window\.docsightUrl\(path\)/);
    assert.match(source, /link\.href = window\.docsightUrl\(chunk\.url\)/);
    assert.match(source, /link\.href = window\.docsightUrl\('\/api\/de-tkg\/claims\//);
    assert.doesNotMatch(source, /fetch\(['"]\/api\//);
    assert.doesNotMatch(source, /https?:\/\//);
});

test('TKG wizard keeps five accessible steps and a live status region', () => {
    for (let step = 1; step <= 5; step += 1) {
        assert.match(template, new RegExp(`data-tkg-step="${step}"`));
    }
    assert.match(template, /role="status" aria-live="polite"/);
    assert.match(template, /id="tkg-letter"/);
    assert.match(template, /id="tkg-download"/);
    assert.match(source, /window\.initDeTkgCompensation/);
    assert.match(source, /window\.initDe_tkg_compensation/);
});

test('TKG wizard invalidates derived output after every claim-fact edit', () => {
    assert.match(source, /function invalidateDerivedState\(/);
    assert.match(source, /state\.calculation = null/);
    assert.match(source, /document\.getElementById\('tkg-letter'\)\.value = ''/);
    assert.match(source, /data-tkg-fact/);
});

test('TKG wizard uses server-local candidate values and never infers legal dates', () => {
    assert.match(source, /candidate\.window_from_local/);
    assert.match(source, /candidate\.window_to_local/);
    assert.doesNotMatch(source, /candidate\.window_from\.slice\(0, 10\)/);
    assert.doesNotMatch(source, /candidate\.window_to\.slice\(0, 10\)/);
    assert.doesNotMatch(source, /new Date\(value\)\.toISOString/);
});

test('TKG clipboard export feature-detects the API and has a user-gesture fallback', () => {
    assert.match(source, /navigator\.clipboard && typeof navigator\.clipboard\.writeText === 'function'/);
    assert.match(source, /document\.execCommand\('copy'\)/);
    assert.match(source, /status_copy_failed/);
});

test('prior-credit classifications are rendered through localized labels', () => {
    const localizedLabels = {
        goodwill: 'credit_goodwill',
        reduction: 'credit_reduction',
        compensation: 'credit_compensation',
        unclear: 'credit_unclear',
    };
    for (const [classification, localeKey] of Object.entries(localizedLabels)) {
        assert.match(
            source,
            new RegExp(`${classification}: t\\('${localeKey}'`)
        );
    }
    assert.match(source, /creditLabels\[result\.prior_credit\.classification\] \|\| creditLabels\.unclear/);
    assert.doesNotMatch(source, /result\.prior_credit\.classification \|\| t\('credit_unclear'/);
});

test('candidate actions have a specific accessible name', () => {
    assert.match(source, /candidate_use/);
    assert.match(source, /setAttribute\('aria-label'/);
    assert.doesNotMatch(source, /use\.textContent = t\('next'/);
});
