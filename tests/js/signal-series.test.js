const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
    const requests = [];
    const context = {window: {}, queueMicrotask, docsightUrl: path => '/mounted' + path,
        fetch: url => new Promise((resolve, reject) => requests.push({url, resolve, reject}))};
    vm.runInNewContext(fs.readFileSync('app/static/js/signal-series.js', 'utf8'), context);
    return {series: context.window.DOCSightSignalSeries, requests};
}
const reply = (request, rows) => request.resolve({ok: true, json: async () => rows});

test('concurrent consumers and warm reads share one prefixed request', async () => {
    const {series, requests} = setup();
    const a = series.get(), b = series.get();
    assert.equal(a, b);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/mounted/api/trends/signal?range=1d');
    const rows = [{ds_power_avg: 0}];
    reply(requests[0], rows);
    assert.equal(await a, rows);
    assert.equal(await series.get(), rows);
    assert.equal(requests.length, 1);
});

test('invalidation rejects old success without fulfilling or evicting new promise', async () => {
    const {series, requests} = setup();
    const old = series.get();
    const rejected = assert.rejects(old, /Stale/);
    const generation = series.invalidate();
    const next = series.get();
    reply(requests[0], [{ds_power_avg: 1}]);
    await rejected;
    assert.equal(series.get(), next);
    reply(requests[1], [{ds_power_avg: 2}]);
    assert.equal((await next)[0].ds_power_avg, 2);
    assert.equal(series.isCurrent(generation), true);
    assert.equal(series.isCurrent(generation - 1), false);
});

test('old failure cannot clear current cache', async () => {
    const {series, requests} = setup();
    const old = series.get();
    const rejected = assert.rejects(old, /offline/);
    series.invalidate();
    const next = series.get();
    reply(requests[1], []);
    await next;
    requests[0].reject(new Error('offline'));
    await rejected;
    assert.equal(series.get(), next);
});

for (const failure of ['http', 'network', 'shape']) {
    test(`${failure} failure is retryable in the same generation`, async () => {
        const {series, requests} = setup();
        const first = series.get();
        const rejected = assert.rejects(first);
        if (failure === 'http') requests[0].resolve({ok: false, status: 503});
        if (failure === 'network') requests[0].reject(new Error('offline'));
        if (failure === 'shape') reply(requests[0], {});
        await rejected;
        const next = series.get();
        reply(requests[1], []);
        await next;
        assert.equal(requests.length, 2);
    });
}

test('public refresh calls in the same turn coalesce; later refresh is fresh', async () => {
    const {series} = setup();
    const first = series.refresh();
    assert.equal(series.refresh(), first);
    await Promise.resolve();
    assert.equal(series.refresh(), first + 1);
});
