'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const NOW = Date.parse('2026-10-04T20:00:00Z');
const HOUR = 3600000;

/* Correlation range tabs as rendered in index.html. */
function correlationTabs() {
    return ['1h', '6h', '1d', '2d', '3d', '7d', '30d', '90d'].map(function(value) {
        const classes = new Set(value === '1d' ? ['active'] : []);
        return {
            value,
            getAttribute(name) { return name === 'data-value' ? value : null; },
            classList: {
                toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
                contains(name) { return classes.has(name); },
            },
        };
    });
}

function setup() {
    const tabs = correlationTabs();
    const c = vm.createContext({
        T: {},
        document: {
            querySelectorAll(selector) { return selector === '#correlation-tabs .trend-tab' ? tabs : []; },
            getElementById() { return null; },
        },
        location: {hash: ''},
    });
    c.window = c;
    c.switchView = function(view) {
        // Correlation reads the active pill synchronously when the view opens.
        c.opened = {view, active: tabs.filter(t => t.classList.contains('active')).map(t => t.value)};
    };
    vm.runInContext(fs.readFileSync('app/static/js/segment-utilization.js', 'utf8'), c);
    return c;
}

function iso(msAgo) { return new Date(NOW - msAgo).toISOString(); }

test('open in correlation activates the range tab that holds the event', () => {
    for (const [hours, expected] of [[24, '1d'], [48, '2d'], [72, '3d'], [168, '7d']]) {
        const c = setup();
        c._fritzCableOpenInCorrelation(hours);
        assert.deepEqual(c.opened, {view: 'correlation', active: [expected]}, `${hours}h`);
    }
});

test('saturation events pick the smallest correlation range that contains them', () => {
    const c = setup();
    const pick = (ageHours) => c._fritzCablePickCorrelationHours(iso(ageHours * HOUR), iso(ageHours * HOUR - 10 * 60000), NOW);
    assert.equal(pick(2), 24);
    assert.equal(pick(30), 48);
    assert.equal(pick(60), 72);
    assert.equal(pick(6 * 24), 168);
    assert.equal(pick(8 * 24), null);
});

test('every offered event range opens correlation with exactly one active tab', () => {
    for (const ageHours of [1, 23, 30, 47, 60, 71, 100, 166]) {
        const c = setup();
        const hours = c._fritzCablePickCorrelationHours(iso(ageHours * HOUR), iso(ageHours * HOUR), NOW);
        c._fritzCableOpenInCorrelation(hours);
        assert.equal(c.opened.active.length, 1, `${ageHours}h old event`);
    }
});
