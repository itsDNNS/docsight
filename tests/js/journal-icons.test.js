'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const CATEGORIES = ['phone', 'technician', 'outage', 'mail', 'complaint', 'contract',
    'measurement', 'authority', 'billing', 'hardware', 'documentation', 'legal'];

// Mirrors /api/journal/icon-keywords: the UI language plus English and German.
function keywordsFor(lang) {
    const keywords = {};
    for (const category of CATEGORIES) keywords[category] = [];
    for (const code of [...new Set([lang, 'en', 'de'])]) {
        const catalog = JSON.parse(fs.readFileSync(path.join(root, `app/modules/journal/i18n/${code}.json`), 'utf8'));
        for (const category of CATEGORIES) {
            for (const word of catalog[`icon_keywords_${category}`].split(',')) {
                const keyword = word.trim().toLowerCase();
                if (keyword && !keywords[category].includes(keyword)) keywords[category].push(keyword);
            }
        }
    }
    return keywords;
}

function journal(lang) {
    const context = {
        window: {}, T: {}, document: {getElementById: () => null, querySelector: () => null, addEventListener() {}, documentElement: {lang}},
        localStorage: {getItem: () => null, setItem() {}},
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(root, 'app/modules/journal/static/main.js'), 'utf8'), context);
    context._iconKeywords = keywordsFor(lang);
    return context;
}

function label(context, title, description) {
    const match = context.detectIcon(title, description);
    return match ? match.label : null;
}

test('journal icons are detected from keywords in the UI language, English and German', () => {
    assert.equal(label(journal('en'), 'Technician visit'), 'technician');
    assert.equal(label(journal('fr'), 'Visite du technicien'), 'technician');
    assert.equal(label(journal('pl'), 'Wizyta technika'), 'technician');
    assert.equal(label(journal('bg'), 'Обадих се на поддръжката'), 'phone');
    assert.equal(label(journal('fr'), 'Techniker war da'), 'technician');
    assert.equal(label(journal('it'), 'Router replaced'), 'hardware');
});

test('everyday words do not trigger a category', () => {
    const en = journal('en');
    assert.notEqual(label(en, 'Intermittent packet loss', 'Noticed buffering on video calls'), 'phone');
    assert.notEqual(label(en, 'Baseline', 'Signal within the expected range'), 'phone');
    assert.equal(label(en, 'Called the hotline'), 'phone');
    assert.notEqual(label(journal('hu'), 'Magas csomagvesztés este'), 'contract');
    assert.notEqual(label(journal('cs'), 'Opravdu pomalé'), 'technician');
    assert.equal(label(journal('bg'), 'Съдържание на страницата'), null);
});

test('long keywords match inside words, short ones only at a word start', () => {
    const de = journal('de');
    assert.equal(label(de, 'Stromausfall seit heute Morgen'), 'outage');
    assert.equal(label(de, 'Fax an den Anbieter'), 'mail');
    assert.equal(label(de, 'Infaxdienst'), null);
    assert.equal(label(de, '', 'Bitte Geld zurück'), 'billing');
});

test('the entry dialog and the journal list pick the same icon', () => {
    const de = journal('de');
    for (const title of ['Tarifwechsel beantragt', 'Stromausfall', 'Neuer Router', 'Ohne Treffer']) {
        const entry = {title, description: ''};
        const match = de.detectIcon(entry.title, entry.description);
        const listIcon = de._getEntryIcon(entry);
        if (match) assert.equal(listIcon, match.icon, title);
        else assert.match(listIcon, /^<svg/, title);
    }
});
