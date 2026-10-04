'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function summary() {
    const source = {
        attrs: {},
        setAttribute(name, value) { this.attrs[name] = value; },
        getAttribute(name) { return this.attrs[name]; },
    };
    const value = {textContent: ''};
    const elements = {'cm-source': source, 'cm-source-value': value};
    const listeners = {};
    let refresh;
    let response;
    const context = {
        document: {
            readyState: 'complete',
            addEventListener(type, callback) { listeners[type] = callback; },
            getElementById: id => elements[id],
        },
        location: {href: ''},
        docsightUrl: url => url,
        setInterval: callback => { refresh = callback; },
        fetch: async () => {
            if (response instanceof Error) throw response;
            return response;
        },
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/modules/connection_monitor/static/js/connection-monitor-summary.js', 'utf8'), context);
    return {
        location: context.location,
        state: () => source.attrs['data-cm-state'],
        health: () => source.attrs['data-cm-health'],
        text: () => value.textContent,
        click() {
            let prevented = false;
            listeners.click({target: {closest: selector => selector === '#cm-source' ? source : null}, preventDefault() { prevented = true; }});
            return prevented;
        },
        async update(data, status = 200) {
            response = data instanceof Error ? data : {ok: status === 200, json: async () => data};
            refresh();
            await new Promise(setImmediate);
        },
    };
}

const healthy = {enabled: true, sample_count: 12, avg_latency_ms: 20, packet_loss_pct: 0};
const unobserved = {enabled: true, sample_count: 0, avg_latency_ms: null, packet_loss_pct: null};

test('summarizes reachable targets and average latency', async () => {
    const view = summary();
    await view.update({1: healthy, 2: {...healthy, avg_latency_ms: 30}, 3: {...healthy, enabled: false}});
    assert.equal(view.text(), '2/2 OK · 25 ms');
    assert.equal(view.state(), 'active');
    assert.equal(view.health(), 'good');
});

for (const [loss, health, text] of [
    [50, 'warn', '0/1 OK · 20 ms · 50% Packet Loss'],
    [100, 'crit', '0/1 OK · 20 ms · 100% Packet Loss'],
]) {
    test(`reports ${loss}% loss as ${health}`, async () => {
        const view = summary();
        await view.update({1: {...healthy, packet_loss_pct: loss}});
        assert.equal(view.text(), text);
        assert.equal(view.health(), health);
    });
}

test('a target without samples is not counted as healthy', async () => {
    const view = summary();
    await view.update({1: healthy, 2: unobserved});
    assert.equal(view.text(), '1/2 OK · 20 ms');
    assert.equal(view.health(), 'muted');
});

for (const [name, data, status, text, state] of [
    ['no samples', {1: unobserved}, 200, 'Starting · Collecting first measurements…', 'starting'],
    ['disabled module', {}, 200, 'Off · Turn on in Settings', 'off'],
    ['network failure', new Error('offline'), 200, '–', 'unknown'],
    ['HTTP failure', {1: healthy}, 503, '–', 'unknown'],
]) {
    test(`replaces a previous reading on ${name}`, async () => {
        const view = summary();
        await view.update({1: healthy});
        await view.update(data, status);
        assert.equal(view.text(), text);
        assert.equal(view.state(), state);
        assert.equal(view.health(), 'muted');
    });
}

test('opens Settings only while the monitor is off', async () => {
    const view = summary();
    await view.update({1: healthy});
    assert.equal(view.click(), false);
    assert.equal(view.location.href, '');

    await view.update({});
    assert.equal(view.click(), true);
    assert.equal(view.location.href, '/settings#mod-docsight_connection_monitor');
});
