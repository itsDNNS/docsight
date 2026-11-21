'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const CARD_TEMPLATE = fs.readFileSync('app/modules/connection_monitor/templates/connection_monitor_card.html', 'utf8');
const SETTINGS = '/settings#mod-docsight_connection_monitor';

/* Loads the real delegated actions and the Home script against a small DOM in
   which events bubble from the target to the document. */
function home(kind) {
    class Element {
        constructor(id, attrs = {}) {
            Object.assign(this, {id, attrs, listeners: {}, children: [], text: '', className: ''});
            this.style = {setProperty: (name, value) => { this.style[name] = value; }};
        }
        set textContent(value) { this.text = value; this.children = []; }
        get textContent() { return this.text + this.children.map(c => c.textContent).join(''); }
        appendChild(child) { this.children.push(child); }
        setAttribute(name, value) { this.attrs[name] = String(value); }
        getAttribute(name) { return this.attrs[name] ?? null; }
        hasAttribute(name) { return name in this.attrs; }
        addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
        closest(selector) {
            if (selector === '.view.active') return document.activeView ? {} : null;
            const action = selector.startsWith('[data-action]') && this.hasAttribute('data-action');
            return action || selector === '#' + this.id ? this : null;
        }
        matches(selector) { return this.closest(selector) === this; }
        dispatch(type, key) {
            const event = {type, key, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
            for (const node of new Set([this, document])) (node.listeners[type] || []).forEach(callback => callback(event));
            return event.defaultPrevented;
        }
        click() { return this.dispatch('click'); }
    }
    const document = Object.assign(new Element('document'), {
        readyState: 'complete', hidden: false, activeView: true,
        getElementById: id => elements[id], createElement: () => new Element(),
    });
    const elements = {};
    if (kind === 'card') {
        const tag = CARD_TEMPLATE.match(/<div [^>]*id="connection-monitor-card"[^>]*>/)[0];
        const attrs = Object.fromEntries([...tag.matchAll(/([\w-]+)=(?:"([^"]*)"|'([^']*)')/g)].map(m => [m[1], m[2] ?? m[3]]));
        for (const [, id] of CARD_TEMPLATE.matchAll(/id="([^"]+)"/g)) elements[id] = new Element(id, id === attrs.id ? attrs : {});
    } else {
        for (const id of ['cm-source', 'cm-source-value']) elements[id] = new Element(id);
    }
    const views = [];
    const navigations = [];
    let refresh;
    let response;
    let requests = 0;
    const context = {
        Element, document,
        T: JSON.parse(fs.readFileSync('app/i18n/en.json', 'utf8')),
        location: {set href(url) { navigations.push(url); }},
        switchView: view => views.push(view),
        docsightUrl: url => url,
        setInterval: callback => { refresh = callback; },
        fetch: async () => {
            requests += 1;
            if (response instanceof Error) throw response;
            return response;
        },
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('app/static/js/actions.js', 'utf8'), context);
    vm.runInNewContext(fs.readFileSync('app/modules/connection_monitor/static/js/connection-monitor-summary.js', 'utf8'), context);
    const el = elements[kind === 'card' ? 'connection-monitor-card' : 'cm-source'];
    const text = id => elements[id].textContent;
    return {
        document, elements, el, views, navigations,
        requests: () => requests,
        async update(data, status = 200) {
            response = data instanceof Error ? data : {ok: status === 200, json: async () => data};
            refresh();
            await new Promise(setImmediate);
        },
        read() {
            if (kind === 'source') {
                return {state: el.getAttribute('data-cm-state'), health: el.getAttribute('data-cm-health'), text: text('cm-source-value')};
            }
            const range = elements['cm-card-range'].style;
            return {
                state: el.getAttribute('data-cm-state'),
                latency: text('cm-card-latency'),
                color: elements['cm-card-latency'].style.color,
                avg: text('cm-card-avg'),
                badge: text('cm-card-badge'),
                badgeClass: elements['cm-card-badge'].className,
                modRow: text('cm-card-mod-row'),
                range: ['marker', 'span-start', 'span-width'].map(name => parseFloat(range['--metric-' + name])).concat(range['--metric-range-accent']),
                context: text('cm-card-range-context'),
            };
        },
    };
}

const healthy = {enabled: true, sample_count: 12, avg_latency_ms: 20, min_latency_ms: 10, max_latency_ms: 30, packet_loss_pct: 0};
const unobserved = {enabled: true, sample_count: 0, avg_latency_ms: null, min_latency_ms: null, max_latency_ms: null, packet_loss_pct: null};

function active(health, ok, total, loss, extra = {}) {
    const color = `var(--${health})`;
    return {
        state: 'active', latency: '20ms', color, avg: `Avg · ${ok}/${total} OK`,
        badge: {good: 'Good', warn: 'Marginal', crit: 'Critical', muted: 'Partial'}[health],
        badgeClass: 'badge badge-' + (health === 'muted' ? 'info' : health),
        modRow: `Packet Loss ${loss}%`, range: [13.3, 6.7, 13.3, color], context: '10 – 30 ms', ...extra,
    };
}

function idle(state, badge, hint, badgeClass) {
    return {
        state, latency: '–', color: 'var(--muted)', avg: hint, badge, badgeClass: 'badge badge-' + badgeClass,
        modRow: '', range: [0, 0, 0, 'var(--muted)'], context: '–',
    };
}

const HEALTHY = {source: {state: 'active', health: 'good', text: '1/1 OK · 20 ms'}, card: active('good', 1, 1, 0)};

for (const [name, data, status, source, card] of [
    ['two reachable targets and a disabled one', {1: healthy, 2: {...healthy, avg_latency_ms: 30, max_latency_ms: 40}, 3: {...healthy, enabled: false}}, 200,
        {state: 'active', health: 'good', text: '2/2 OK · 25 ms'},
        active('good', 2, 2, 0, {latency: '25ms', range: [16.7, 6.7, 20, 'var(--good)'], context: '10 – 40 ms'})],
    ['a target without samples', {1: healthy, 2: unobserved}, 200,
        {state: 'active', health: 'muted', text: '1/2 OK · 20 ms'}, active('muted', 1, 2, 0)],
    ['50% loss next to a target without samples', {1: {...healthy, packet_loss_pct: 50}, 2: unobserved}, 200,
        {state: 'active', health: 'warn', text: '0/2 OK · 20 ms · 50% Packet Loss'}, active('warn', 0, 2, 50)],
    ['100% loss next to a target without samples', {1: {...healthy, packet_loss_pct: 100}, 2: unobserved}, 200,
        {state: 'active', health: 'crit', text: '0/2 OK · 20 ms · 100% Packet Loss'}, active('crit', 0, 2, 100)],
    ['no samples', {1: unobserved}, 200,
        {state: 'starting', health: 'muted', text: 'Starting · Collecting first measurements…'},
        idle('starting', 'Starting', 'Collecting first measurements…', 'info')],
    ['disabled target', {1: {...healthy, enabled: false}}, 200,
        {state: 'off', health: 'muted', text: 'Off · Turn on in Settings'}, idle('off', 'Off', 'Turn on in Settings', 'muted')],
    ['disabled module', {}, 200,
        {state: 'off', health: 'muted', text: 'Off · Turn on in Settings'}, idle('off', 'Off', 'Turn on in Settings', 'muted')],
    ['network failure', new Error('offline'), 200, {state: 'unknown', health: 'muted', text: '–'}, idle('unknown', '–', '', 'info')],
    ['HTTP failure', {1: healthy}, 503, {state: 'unknown', health: 'muted', text: '–'}, idle('unknown', '–', '', 'info')],
]) {
    for (const [kind, expected] of Object.entries({source, card})) {
        test(`${kind} replaces a healthy reading on ${name} and recovers`, async () => {
            const view = home(kind);
            await view.update({1: healthy});
            assert.deepEqual(view.read(), HEALTHY[kind]);
            await view.update(data, status);
            assert.deepEqual(view.read(), expected);
            await view.update({1: healthy});
            assert.deepEqual(view.read(), HEALTHY[kind]);
        });
    }
}

for (const [kind, input] of [['source', 'click'], ['card', 'click'], ['card', 'Enter'], ['card', ' ']]) {
    test(`${kind} acts once per ${input === ' ' ? 'Space' : input}: Settings while off, the detail view otherwise`, async () => {
        const view = home(kind);
        const opened = [];
        for (const data of [{}, {1: healthy}]) {
            await view.update(data);
            const prevented = input === 'click' ? view.el.click() : view.el.dispatch('keydown', input);
            opened.push({state: view.read().state, navigations: view.navigations.splice(0), views: view.views.splice(0), prevented});
        }
        // Keys are always taken; a click is only held back to leave the source link for Settings.
        assert.deepEqual(opened, [
            {state: 'off', navigations: [SETTINGS], views: [], prevented: input !== 'click' || kind === 'source'},
            {state: 'active', navigations: [], views: kind === 'card' ? ['connection-monitor'] : [], prevented: input !== 'click'},
        ]);
    });
}

for (const kind of ['source', 'card']) {
    test(`${kind} polls only while on screen and catches up when the tab returns`, async () => {
        const view = home(kind);
        await new Promise(setImmediate);
        const initial = view.requests();
        view.document.hidden = true;
        await view.update({1: healthy});
        view.document.hidden = false;
        view.document.activeView = false;
        await view.update({1: healthy});
        assert.equal(view.requests(), initial);
        view.document.activeView = true;
        view.document.dispatch('visibilitychange');
        await new Promise(setImmediate);
        assert.equal(view.requests(), initial + 1);
    });
}

test('a reading whose Home section a refresh removed during the request is dropped', async () => {
    const view = home('card');
    await view.update({});
    const pending = view.update({1: healthy});
    for (const id in view.elements) delete view.elements[id];
    await pending;
    assert.equal(view.el.getAttribute('data-cm-state'), 'off');
});
