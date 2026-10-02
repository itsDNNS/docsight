'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function card() {
    function element() {
        return {
            children: [], text: '', className: '', style: {setProperty() {}},
            set textContent(value) { this.text = value; this.children = []; },
            get textContent() { return this.text + this.children.map(c => c.textContent).join(''); },
            appendChild(child) { this.children.push(child); },
        };
    }
    const ids = ['latency', 'avg', 'badge', 'mod-row', 'range', 'range-context'];
    const elements = Object.fromEntries(ids.map(id => ['cm-card-' + id, element()]));
    const listeners = {};
    const views = [];
    elements['connection-monitor-card'] = {
        attrs: {},
        setAttribute(name, value) { this.attrs[name] = value; },
        getAttribute(name) { return this.attrs[name]; },
        addEventListener(type, callback) { listeners[type] = callback; },
    };
    let refresh;
    let response;
    const context = {
        document: {
            readyState: 'complete', addEventListener() {},
            getElementById: id => elements[id], createElement: element,
        },
        location: {href: ''},
        switchView: view => views.push(view),
        docsightUrl: url => url,
        setInterval: callback => { refresh = callback; },
        fetch: async () => {
            if (response instanceof Error) throw response;
            return response;
        },
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/modules/connection_monitor/static/js/connection-monitor-card.js', 'utf8'), context);
    return {
        elements,
        views,
        location: context.location,
        state: () => elements['connection-monitor-card'].attrs['data-cm-state'],
        click: () => listeners.click(),
        async update(data, status = 200) {
            response = data instanceof Error ? data : {ok: status === 200, json: async () => data};
            refresh();
            await new Promise(setImmediate);
        },
        text: id => elements['cm-card-' + id].textContent,
    };
}

const healthy = {enabled: true, sample_count: 12, avg_latency_ms: 20, min_latency_ms: 10, max_latency_ms: 30, packet_loss_pct: 0};
const unobserved = {enabled: true, sample_count: 0, avg_latency_ms: null, min_latency_ms: null, max_latency_ms: null, packet_loss_pct: null};

test('card reports observed latency, loss and range without inventing jitter', async () => {
    const view = card();
    await view.update({1: healthy});
    assert.equal(view.text('latency'), '20ms');
    assert.equal(view.text('avg'), 'Avg · 1/1 OK');
    assert.equal(view.text('badge'), 'Good');
    assert.equal(view.text('mod-row'), 'Packet Loss 0%');
    assert.equal(view.text('range-context'), '10 – 30 ms');
});

for (const [name, data, status, badge, hint, state] of [
    ['no samples', {1: unobserved}, 200, 'Starting', 'Collecting first measurements…', 'starting'],
    ['disabled target', {1: {...healthy, enabled: false}}, 200, 'Off', 'Turn on in Settings', 'off'],
    ['disabled module', {}, 200, 'Off', 'Turn on in Settings', 'off'],
    ['network failure', new Error('offline'), 200, '–', '', 'unknown'],
    ['HTTP failure', {1: healthy}, 503, '–', '', 'unknown'],
]) {
    test(`card clears previous healthy readings on ${name}`, async () => {
        const view = card();
        await view.update({1: healthy});
        assert.equal(view.state(), 'active');
        await view.update(data, status);
        assert.equal(view.text('latency'), '–');
        assert.equal(view.text('badge'), badge);
        assert.equal(view.text('avg'), hint);
        assert.equal(view.state(), state);
        assert.equal(view.text('mod-row'), '');
        assert.equal(view.text('range-context'), '–');
        assert.equal(view.elements['cm-card-latency'].style.color, 'var(--muted)');
        await view.update({1: healthy});
        assert.equal(view.text('badge'), 'Good');
    });
}

for (const [loss, badge, okCount] of [[0, 'Partial', 1], [50, 'Marginal', 0], [100, 'Critical', 0]]) {
    test(`missing target neither counts as healthy nor dilutes ${loss}% observed loss`, async () => {
        const view = card();
        await view.update({1: {...healthy, packet_loss_pct: loss}, 2: unobserved});
        assert.equal(view.text('avg'), `Avg · ${okCount}/2 OK`);
        assert.equal(view.text('badge'), badge);
        assert.equal(view.text('mod-row'), `Packet Loss ${loss}%`);
    });
}

test('card opens Settings while the monitor is off and the detail view otherwise', async () => {
    const view = card();
    await view.update({});
    view.click();
    assert.equal(view.location.href, '/settings#mod-docsight_connection_monitor');
    assert.deepEqual(view.views, []);

    view.location.href = '';
    await view.update({1: healthy});
    view.click();
    assert.equal(view.location.href, '');
    assert.deepEqual(view.views, ['connection-monitor']);
});
