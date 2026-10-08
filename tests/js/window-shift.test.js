'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const contracts = require('../../app/static/js/browser-contracts.js');

function windowShift(timeZone, elements, clock) {
    const context = {
        DOCSightBrowserContracts: contracts,
        DOCSIGHT_TIME_ZONE: timeZone,
        formatDocsightTime: (ms) => new Date(ms).toISOString().slice(0, 16),
        document: {getElementById: (id) => (elements || {})[id] || null},
        Date: clock ? class extends Date { static now() { return clock.now; } } : Date
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/window-shift.js'), 'utf8'), context);
    return context.DOCSightWindowShift;
}

function element() {
    const listeners = {};
    return {
        hidden: true, disabled: true, textContent: '',
        addEventListener: (type, fn) => { listeners[type] = fn; },
        click: () => listeners.click()
    };
}

test('the end travels as wall-clock time in DOCSight\'s zone, also across a DST change', () => {
    const shift = windowShift('Europe/Berlin');
    // 20:00 in Berlin is 18:00 UTC in summer time and 19:00 UTC after the change.
    assert.equal(new Date(shift.fromParam('2026-10-03T20:00')).toISOString(), '2026-10-03T18:00:00.000Z');
    assert.equal(new Date(shift.fromParam('2026-10-30T20:00')).toISOString(), '2026-10-30T19:00:00.000Z');
    assert.equal(shift.toParam(Date.parse('2026-10-30T19:00:00Z')), '2026-10-30T20:00');
    assert.equal(shift.fromParam('2026-10-30'), null);
    assert.equal(shift.fromParam('soon'), null);
});

test('the arrows step by the window length; reaching now ends the past window', () => {
    const ids = ['earlier', 'later', 'past', 'range', 'now', 'hint'];
    const elements = Object.fromEntries(ids.map((id) => ['t-window-' + id, element()]));
    let changes = 0;
    const shift = windowShift('UTC', elements).create('t', {hours: () => 6, onChange: () => { changes++; }});

    shift.restore('2026-10-03T20:00');
    assert.equal(shift.param(), '2026-10-03T20:00');
    assert.equal(elements['t-window-past'].hidden, false);
    assert.equal(elements['t-window-later'].disabled, false);
    assert.equal(elements['t-window-range'].textContent, '2026-10-03T14:00 – 2026-10-03T20:00');

    elements['t-window-earlier'].click();
    assert.equal(shift.param(), '2026-10-03T14:00');
    elements['t-window-later'].click();
    elements['t-window-later'].click();
    assert.equal(shift.param(), '2026-10-04T02:00');
    assert.equal(changes, 3);

    elements['t-window-now'].click();
    assert.equal(shift.param(), null);
    assert.equal(elements['t-window-past'].hidden, true);
    assert.equal(elements['t-window-later'].disabled, true);
    // At now there is nothing later.
    assert.equal(shift.step(1), false);

    // A deep link to the future is a window that ends now.
    shift.restore('2999-01-01T00:00');
    assert.equal(shift.param(), null);
});


test('stepping forward to where the window left now is now again, also minutes later', () => {
    const ids = ['earlier', 'later', 'past', 'range', 'now', 'hint'];
    const elements = Object.fromEntries(ids.map((id) => ['t-window-' + id, element()]));
    const clock = {now: Date.parse('2026-10-08T10:24:50Z')};
    const shift = windowShift('UTC', elements, clock).create('t', {hours: () => 24, onChange: () => {}});

    elements['t-window-earlier'].click();
    assert.equal(shift.param(), '2026-10-07T10:24');
    clock.now += 5 * 60 * 1000;
    elements['t-window-later'].click();
    assert.equal(shift.param(), null);
    assert.equal(elements['t-window-past'].hidden, true);

    // Two steps back and one forward stays in the past.
    elements['t-window-earlier'].click();
    elements['t-window-earlier'].click();
    elements['t-window-later'].click();
    assert.equal(shift.param(), '2026-10-07T10:29');
});
