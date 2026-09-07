'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function browser() {
    const ids = new Map(), requests = [];
    function element() {
        return {
            children: [], style: {}, textContent: '',
            set innerHTML(value) { this.children = []; this.html = value; },
            classList: { contains: () => true, toggle() {} },
            setAttribute() {}, appendChild(child) { this.children.push(child); },
        };
    }
    const context = {
        T: {}, URLSearchParams, setInterval() {}, escapeHtml: String, docsightUrl: url => url,
        document: {
            getElementById(id) {
                if (!ids.has(id)) ids.set(id, element());
                return ids.get(id);
            },
            querySelectorAll: () => [], createElement: element,
        },
        fetch: url => new Promise((resolve, reject) => requests.push({url, resolve, reject})),
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/events.js'), 'utf8'), context);
    return {
        context, requests, node: id => context.document.getElementById(id),
        async reply(index, data, ok = true) {
            requests[index].resolve({ok, json: async () => data});
            await new Promise(resolve => setImmediate(resolve));
        },
    };
}

function page(count, start = 0) {
    return {unacknowledged_count: count, events: Array.from({length: count}, (_, i) => ({
        id: start + i, timestamp: '2026-09-07T10:00:00Z', severity: 'info',
        event_type: 'health_change', message: 'Health changed',
    }))};
}

test('filter changes use the feed response for the badge and acknowledgement action', async () => {
    const b = browser();
    b.context.filterEventsBySeverity('warning');
    assert.equal(b.requests.length, 2); // Initial badge request, then one feed request.
    assert.match(b.requests[1].url, /severity=warning/);
    await b.reply(1, page(2));
    assert.equal(b.node('event-badge').textContent, 2);
    assert.equal(b.node('btn-ack-all').style.display, '');
    await b.reply(0, {count: 99});
    assert.equal(b.node('event-badge').textContent, 2);
});

test('a periodic badge refresh does not suppress the feed acknowledgement action', async () => {
    const b = browser();
    b.node('btn-ack-all').style.display = 'none';
    b.context.loadEvents();
    b.context.refreshEventBadge();
    await b.reply(2, {count: 3});
    await b.reply(1, page(2));
    assert.equal(b.node('event-badge').textContent, 3);
    assert.equal(b.node('btn-ack-all').style.display, '');
});

for (const staleOk of [true, false]) {
    test(`stale ${staleOk ? 'success' : 'failure'} cannot end the current loading state`, async () => {
        const b = browser();
        b.context.filterEventsBySeverity('warning');
        b.context.filterEventsBySeverity('critical');
        await b.reply(1, page(1), staleOk);
        assert.equal(b.node('events-loading').style.display, '');
        assert.equal(b.node('events-empty').style.display, 'none');
        assert.equal(b.node('events-feed').children.length, 0);
        await b.reply(2, page(2));
        assert.equal(b.node('events-loading').style.display, 'none');
        assert.equal(b.node('events-feed').children.length, 2);
    });
}

test('failed pagination retries the same offset and clears the error on success', async () => {
    const b = browser();
    b.context.loadEvents();
    await b.reply(1, page(50));
    b.context.loadMoreEvents();
    assert.match(b.requests[2].url, /offset=50/);
    assert.equal(b.node('events-show-more').style.display, 'none');
    await b.reply(2, {error: 'Service unavailable'}, false);
    assert.equal(b.node('events-feed').children.length, 50);
    assert.equal(b.node('events-empty').style.display, '');
    assert.equal(b.node('events-show-more').style.display, '');
    b.context.loadMoreEvents();
    assert.match(b.requests[3].url, /offset=50/);
    await b.reply(3, page(10, 50));
    assert.equal(b.node('events-feed').children.length, 60);
    assert.equal(b.node('events-empty').style.display, 'none');
    assert.equal(b.node('events-show-more').style.display, 'none');
});
