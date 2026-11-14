'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function browser() {
    const ids = new Map(), requests = [];
    // Enough of the DOM for the feed, which inserts and replaces its day sections.
    function section(html, parent) {
        return {
            html, parent,
            getAttribute: name => (html.match(new RegExp(name + '="([^"]*)"')) || [])[1] || null,
            get nextElementSibling() { return parent.nodes[parent.nodes.indexOf(this) + 1] || null; },
            get previousElementSibling() { return parent.nodes[parent.nodes.indexOf(this) - 1] || null; },
            insertAdjacentHTML(_position, markup) { parent.nodes.splice(parent.nodes.indexOf(this), 0, section(markup, parent)); },
            remove() { parent.nodes.splice(parent.nodes.indexOf(this), 1); },
            querySelectorAll: () => [],
        };
    }
    function element() {
        return {
            children: [], nodes: [], style: {}, textContent: '', hidden: false, markup: '',
            get html() { return this.nodes.length ? this.nodes.map(node => node.html).join('') : this.markup; },
            set innerHTML(value) { this.markup = value; },
            get innerHTML() { return this.html; },
            get firstElementChild() { return this.nodes[0] || null; },
            get lastElementChild() { return this.nodes[this.nodes.length - 1] || null; },
            insertAdjacentHTML(_position, markup) { this.nodes.push(section(markup, this)); },
            classList: { contains: () => true, toggle() {} },
            setAttribute() {}, appendChild(child) { this.children.push(child); },
            querySelectorAll: () => [], querySelector: () => null,
        };
    }
    // Records which empty state events.js asks for; the component has its own tests.
    const emptyState = {
        show(el, options) { el.hidden = false; el.empty = {kind: 'show', ...options}; },
        showError(el, options) { el.hidden = false; el.empty = {kind: 'error', ...options}; },
        hide(el) { el.hidden = true; el.empty = null; },
    };
    const context = {
        DOCSightEmptyState: emptyState, T: {}, URLSearchParams, setInterval() {},
        location: {hash: '#events'}, history: {replaceState(_state, _title, url) { context.location.hash = url; }}, currentView: 'events', escapeHtml: String, formatDocsightTime: String, docsightUrl: url => url,
        document: {
            getElementById(id) {
                if (id === 'home-events-list') return null; // Events view only, no Home list.
                if (!ids.has(id)) ids.set(id, element());
                return ids.get(id);
            },
            querySelectorAll: () => [], createElement: element, addEventListener() {},
        },
        fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    };
    context.window = context;
    for (const file of ['view-state.js', 'event-log-data.js', 'events.js']) {
        vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../app/static/js', file), 'utf8'), context);
    }
    return {
        context, requests, node: id => context.document.getElementById(id),
        rows: () => (context.document.getElementById('events-feed').html.match(/data-event-id="/g) || []).length,
        async reply(index, data, ok = true) {
            requests[index].resolve({ok, json: async () => data});
            await new Promise(resolve => setImmediate(resolve));
        },
    };
}

function page(count, start = 1, acknowledged = 0) {
    return {unacknowledged_count: acknowledged ? 0 : count, events: Array.from({length: count}, (_, i) => ({
        id: start + i, timestamp: '2026-09-07T10:00:00', severity: 'info', acknowledged,
        event_type: 'health_change', message: 'Health changed',
    }))};
}

test('the badge counts attention events and ignores the log filters', async () => {
    const b = browser();
    assert.match(b.requests[0].url, /^\/api\/events\/count\?scope=attention&t=\d+$/);
    b.context.filterEventsBySeverity('warning');
    assert.match(b.requests[1].url, /severity=warning/);
    await b.reply(1, page(2));
    assert.equal(b.node('event-badge').textContent, '');
    await b.reply(0, {count: 3});
    assert.equal(b.node('event-badge').textContent, 3);
});

test('the visible acknowledgement action follows the loaded events', async () => {
    const b = browser();
    b.context.loadEvents();
    await b.reply(1, page(2));
    assert.equal(b.node('btn-ack-visible').hidden, false);
    assert.equal(b.node('btn-ack-selected').hidden, true);
    b.context.loadEvents();
    await b.reply(2, page(2, 1, 1));
    assert.equal(b.node('btn-ack-visible').hidden, true);
});

test('acknowledging visible events posts their ids, marks the rows and refreshes the badge', async () => {
    const b = browser();
    b.context.loadEvents();
    await b.reply(1, page(3));
    b.context.acknowledgeVisibleEvents();
    const post = b.requests[2];
    assert.equal(post.url, '/api/events/acknowledge');
    assert.equal(post.options.method, 'POST');
    assert.deepEqual(JSON.parse(post.options.body), {ids: [1, 2, 3]});
    await b.reply(2, {success: true, count: 3});
    assert.equal((b.node('events-feed').html.match(/ev-acked/g) || []).length, 4); // three rows and their run
    assert.equal(b.node('btn-ack-visible').hidden, true);
    assert.match(b.requests[3].url, /scope=attention/);
});

test('a failed acknowledgement leaves the rows open', async () => {
    const b = browser();
    b.context.loadEvents();
    await b.reply(1, page(1));
    b.context.acknowledgeVisibleEvents();
    await b.reply(2, {error: 'nope'}, false);
    assert.doesNotMatch(b.node('events-feed').html, /ev-acked/);
    assert.equal(b.node('btn-ack-visible').hidden, false);
    assert.equal(b.requests.length, 3);
});

for (const staleOk of [true, false]) {
    test(`stale ${staleOk ? 'success' : 'failure'} cannot end the current loading state`, async () => {
        const b = browser();
        b.context.filterEventsBySeverity('warning');
        b.context.filterEventsBySeverity('critical');
        await b.reply(1, page(1), staleOk);
        assert.equal(b.node('events-loading').hidden, false);
        assert.equal(b.node('events-empty').hidden, true);
        assert.equal(b.rows(), 0);
        await b.reply(2, page(2));
        assert.equal(b.node('events-loading').hidden, true);
        assert.equal(b.rows(), 2);
    });
}

test('failed pagination retries the same offset and clears the error on success', async () => {
    const b = browser();
    b.context.loadEvents();
    await b.reply(1, page(50));
    b.context.loadMoreEvents();
    assert.match(b.requests[2].url, /offset=50/);
    assert.equal(b.node('events-show-more').hidden, true);
    await b.reply(2, {error: 'Service unavailable'}, false);
    assert.equal(b.rows(), 50);
    assert.equal(b.node('events-empty').empty.kind, 'error');
    assert.equal(b.node('events-show-more').hidden, false);
    b.context.loadMoreEvents();
    assert.match(b.requests[3].url, /offset=50/);
    await b.reply(3, page(10, 51));
    assert.equal(b.rows(), 60);
    assert.equal(b.node('events-empty').hidden, true);
    assert.equal(b.node('events-show-more').hidden, true);
});

test('rows shifted onto the next page by new events are not shown twice', async () => {
    const b = browser();
    b.context.T.event_count_shown = '{count} events shown';
    b.context.loadEvents();
    await b.reply(1, page(50));
    b.context.loadMoreEvents();
    await b.reply(2, page(50, 49)); // two new events pushed ids 49 and 50 onto page two
    assert.equal(b.rows(), 98);
    assert.match(b.node('events-summary').textContent, /98/);
});

test('event numbers follow the page language', () => {
    const b = browser();
    const spike = {event_type: 'error_spike', message: '', details: {prev: 0, current: 1072.25, delta: 1072.25}};
    b.context.currentLang = 'de';
    assert.match(b.context.formatEventMessage(spike), /\+1\.072,3<\/span>/);
    b.context.currentLang = 'en';
    assert.match(b.context.formatEventMessage(spike), /\+1,072\.3<\/span>/);
});

test('an empty log explains itself: filters can be reset, otherwise notifications are offered', async () => {
    const b = browser();
    b.context.loadEvents();
    await b.reply(1, {events: [], unacknowledged_count: 0});
    let empty = b.node('events-empty').empty;
    assert.equal(empty.icon, 'bell');
    assert.equal(empty.action.href, '/settings#notifications');
    assert.equal(empty.glossary, 'event_log');

    b.context.filterEventsBySeverity('critical');
    await b.reply(2, {events: [], unacknowledged_count: 0});
    empty = b.node('events-empty').empty;
    assert.equal(empty.icon, 'sliders-horizontal');
    empty.action.onClick();
    assert.doesNotMatch(b.requests[3].url, /severity=/);
});

test('a failed first load offers a retry of the same request', async () => {
    const b = browser();
    b.context.loadEvents();
    await b.reply(1, {error: 'down'}, false);
    const empty = b.node('events-empty').empty;
    assert.equal(empty.kind, 'error');
    empty.retry();
    assert.match(b.requests[2].url, /offset=0/);
});

test('showing more keeps the newer days and only rebuilds the days that changed', async () => {
    const b = browser();
    const dated = (data, day) => ({...data, events: data.events.map(ev => ({...ev, timestamp: day + 'T10:00:00'}))});
    const first = dated(page(25), '2026-09-07');
    first.events.push(...dated(page(25, 26), '2026-09-06').events);
    b.context.loadEvents();
    await b.reply(1, first);
    const feed = b.node('events-feed');
    const [newest, partial] = feed.nodes;
    b.context.loadMoreEvents();
    const second = dated(page(5, 51), '2026-09-06');
    second.events.push(...dated(page(5, 56), '2026-09-05').events);
    await b.reply(2, second);
    assert.deepEqual(feed.nodes.map(node => node.getAttribute('data-day')), ['2026-09-07', '2026-09-06', '2026-09-05']);
    assert.equal(feed.nodes[0], newest);
    assert.notEqual(feed.nodes[1], partial);
    assert.equal(b.rows(), 60);
});
