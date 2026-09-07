'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const root = path.resolve(__dirname, '../..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const catalog = JSON.parse(read('app/modules/modulation/i18n/en.json'));
const levels = ['4QAM', '8QAM', '16QAM', '32QAM', '64QAM', '128QAM', '256QAM',
    '512QAM', '1024QAM', '4096QAM', 'Unknown', 'unrecognized', 'OFDM', 'OFDMA', 'QPSK'];

function browser(lang = 'en', translations = {}) {
    const ids = new Map(), charts = [], requests = [];
    function element(attrs = {}) {
        const classes = new Set(), listeners = {};
        return {
            children: [], style: {}, className: '', hidden: false, offsetWidth: 400, offsetHeight: 300,
            set id(value) { ids.set(value, this); },
            set textContent(value) { this.text = value; this.children = []; },
            get textContent() { return (this.text || '') + this.children.map(e => e.textContent).join(''); },
            classList: {add: c => classes.add(c), contains: c => classes.has(c),
                toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }},
            setAttribute(k, v) { attrs[k] = v; }, getAttribute: k => attrs[k],
            appendChild(e) { this.children.push(e); },
            addEventListener(k, fn) { listeners[k] = fn; },
            click(event = {}) { listeners.click.call(this, event); },
            getBoundingClientRect: () => ({left: 10, width: 400}),
        };
    }
    for (const match of read('app/modules/modulation/templates/modulation_tab.html').matchAll(/id="([^"]+)"/g)) {
        ids.set(match[1], element());
    }
    for (const dir of ['ds', 'us']) {
        for (const field of ['current', 'min', 'avg', 'max', 'coverage', 'status', 'caveat']) {
            ids.set(`mod-cap-${dir}-${field}`, element());
        }
    }
    ids.set('mod-capacity-downstream', element());
    ids.set('mod-capacity-upstream', element());
    const directions = ['us', 'ds'].map(dir => element({'data-dir': dir}));
    const ranges = [1, 7, 30].map(days => element({'data-days': String(days)}));
    function Chart(options, data, container) {
        Object.assign(this, {options, data, container, over: element(), destroyed: false});
        this.posToVal = pos => pos / 100;
        this.destroy = () => { this.destroyed = true; };
        charts.push(this);
    }
    Chart.paths = {bars: () => () => {}, stepped: () => () => {}};
    const context = {
        document: {getElementById: id => ids.get(id), createElement: () => element(),
            querySelectorAll: selector => selector.includes('direction') ? directions : ranges},
        getComputedStyle: () => ({getPropertyValue: () => ''}), uPlot: Chart,
        tooltipPlugin: () => ({}), T: translations, currentLang: lang,
        docsightUrl: url => '/docsight' + url, console: {error: (...args) => assert.fail(args.join(' '))},
        fetch: url => new Promise(resolve => requests.push({url, resolve})),
    };
    context.window = context;
    vm.runInNewContext(read('app/modules/modulation/static/main.js'), context);
    return {ids, charts, requests, directions, ranges, context, init: () => context.initModulation(),
        async reply(data, index = requests.length - 1) {
            requests[index].resolve({json: async () => data});
            await new Promise(resolve => setImmediate(resolve));
        }};
}

function overview(direction = 'us', version = '3.1', count = 7) {
    return {direction, sample_count: count,
        aggregate: {health_index: 80, low_qam_pct: 12}, protocol_groups: [{
            docsis_version: version, max_qam: '1024QAM', channel_count: 1,
            health_index: 80, low_qam_pct: 12, degraded_channel_count: 1,
            days: Array.from({length: count}, (_, i) => ({date: `2026-03-${String(i + 1).padStart(2, '0')}`,
                distribution: Object.fromEntries(levels.map(mod => [mod, 100 / levels.length])),
                health_index: 80, low_qam_pct: 12})),
        }]};
}

const red = new Set(['#ef4444', '#dc2626', '#b91c1c', '#f87171', '#fb7185']);
for (const count of [1, 30]) {
    test(`${count} observed polls display as a count, without inferred completeness`, async () => {
        const b = browser();
        b.init();
        const data = overview();
        data.sample_count = count;
        await b.reply(data);
        assert.equal(b.ids.get('mod-kpi-samples').textContent, String(count));
        assert.equal(b.ids.get('mod-kpi-samples').className.includes('good'), false);
        assert.equal(b.ids.has('mod-kpi-density'), false);
        assert.equal(b.ids.has('mod-cap-ds-tariff'), false);
    });
}

const amber = new Set(['#f59e0b', '#fbbf24', '#d97706', '#f97316']);
const green = new Set(['#22c55e', '#16a34a', '#15803d', '#86efac', '#14b8a6']);
for (const [direction, version] of [['us', '3.1'], ['us', '3.0'], ['ds', '3.0'], ['ds', '3.1'], ['us', 'other']]) {
    test(`distribution colors, legend and percent axis: ${direction} ${version}`, async () => {
        const b = browser();
        b.init();
        await b.reply(overview(direction, version));
        const [distribution, trend] = b.charts;
        const colors = Object.fromEntries(distribution.options.series.slice(1).map(s => [s.label, s.fill]));
        const contextual = direction === 'us' && ['3.0', '3.1'].includes(version);
        if (contextual) {
            for (const mod of levels.slice(0, version === '3.1' ? 5 : 3)) assert.ok(red.has(colors[mod]), mod);
            assert.ok(amber.has(colors[version === '3.1' ? '128QAM' : '32QAM']));
            for (const mod of version === '3.1' ? levels.slice(6, 10) : ['64QAM']) assert.ok(green.has(colors[mod]), mod);
            if (version === '3.1') {
                assert.ok(['#dc2626', '#b91c1c'].includes(colors['32QAM']));
                assert.ok(['#fb7185', '#f87171', '#ef4444'].includes(colors['64QAM']));
            }
            assert.notEqual(colors['32QAM'], colors['64QAM']);
            for (let i = 1; i < 5; i++) assert.notEqual(colors[levels[i - 1]], colors[levels[i]]);
        } else {
            assert.deepEqual(levels.slice(0, 10).map(m => colors[m]), ['#ef4444', '#fb7185', '#f97316',
                '#f59e0b', '#eab308', '#84cc16', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6']);
        }
        assert.equal(colors.OFDM, contextual && version === '3.1' ? '#22c55e' : '#8b5cf6');
        assert.equal(colors.OFDMA, colors.OFDM);
        assert.ok(contextual ? red.has(colors.QPSK) : colors.QPSK === '#6b7280');
        assert.equal(colors.Unknown, '#6b7280');
        assert.equal(colors.unrecognized, colors.Unknown);
        const legend = b.ids.get('mod-dist-legend-0');
        for (const item of legend.children.filter(e => e.children.length === 2)) {
            assert.equal(item.children[0].style.background, colors[item.children[1].textContent]);
        }
        assert.equal(legend.textContent.includes('US DOCSIS'), contextual);
        if (contextual) assert.ok(legend.textContent.includes(version === '3.1' ? '64QAM and below' : '64QAM is the healthy maximum'));
        const scale = trend.options.series.find(s => s.label === 'Low-QAM %').scale;
        assert.deepEqual(Array.from(trend.options.scales[scale].range), [0, 100]);
        assert.deepEqual(Array.from(trend.options.axes.find(a => a.scale === scale).values(null, [0, 50, 100])), ['0%', '50%', '100%']);
        assert.equal(b.ids.get('mod-kpi-lowqam-hint').textContent, 'Unknown samples stay in the total');
    });
}

test('controls request fresh ranges and day bars drill into the selected date', async () => {
    const b = browser();
    b.init();
    assert.equal(b.requests[0].url, '/docsight/api/modulation/distribution?direction=us&days=7');
    await b.reply(overview());
    const old = b.charts[0];
    b.directions[1].click();
    assert.equal(b.requests.at(-1).url, '/docsight/api/modulation/distribution?direction=ds&days=7');
    await b.reply(overview('ds'));
    assert.equal(old.destroyed, true);
    b.ranges[2].click();
    assert.equal(b.requests.at(-1).url, '/docsight/api/modulation/distribution?direction=ds&days=30');
    await b.reply(overview('ds', '3.0', 30));
    assert.equal(b.charts.at(-2).data[0].length, 30);
    const container = b.ids.get('mod-dist-chart-0');
    assert.equal(container.classList.contains('modulation-clickable-chart'), true);
    const before = b.requests.length;
    for (const clientX of [0, 411]) container.click({clientX});
    assert.equal(b.requests.length, before);
    container.click({clientX: 110});
    assert.equal(b.requests.at(-1).url, '/docsight/api/modulation/intraday?direction=ds&date=2026-03-02');
    await b.reply({date: '2026-03-02', protocol_groups: []});
    assert.equal(b.ids.get('modulation-overview').style.display, 'none');
    assert.equal(b.ids.get('modulation-intraday').style.display, '');
    assert.ok(b.ids.get('mod-intraday-title').textContent.includes('2026-03-02'));
});

for (const version of ['3.0', '3.1']) {
    test(`a delayed ${version} response owns its palette and legend after direction changes`, async () => {
        const b = browser();
        b.init();
        b.directions[1].click();
        await b.reply(overview('us', version), 0);
        assert.ok((version === '3.1' ? red : green).has(b.charts[0].options.series.find(s => s.label === '64QAM').fill));
        assert.ok(b.ids.get('mod-dist-legend-0').textContent.includes(version === '3.1' ? '64QAM and below' : '64QAM is the healthy maximum'));
        const section = b.ids.get('modulation-protocol-groups').children[0];
        assert.equal(section.getAttribute('data-direction'), 'us');
        assert.equal(section.getAttribute('data-docsis-version'), version);
        await b.reply(overview('ds'), 1);
        assert.equal(b.charts.at(-2).options.series.find(s => s.label === '64QAM').fill, '#eab308');
    });
}

for (const lang of ['en', 'de']) {
    test(`capacity range, units, localization, coverage and caveats: ${lang}`, async () => {
        const T = Object.fromEntries(Object.entries(catalog).map(([key, value]) => ['docsight.modulation.' + key, value]));
        T['docsight.modulation.capacity_selected_days'] = 'Period {days}';
        T['docsight.modulation.capacity_partial_caveat'] = 'Excluded: {families}';
        T['docsight.modulation.capacity_coverage_detail'] = 'Coverage {calculated}/{total} = {pct}%';
        T['docsight.modulation.low_qam_denominator_hint'] = 'Translated denominator';
        T['docsight.modulation.low_qam_legend_hint_d31_us'] = 'Translated context';
        const b = browser(lang, T), data = overview();
        const summary = {status: 'observed', capacity_current_mbps: 123.45,
            capacity_min_mbps: 100, capacity_avg_mbps: 120, capacity_max_mbps: 140,
            calculated_channel_samples: 3, total_channel_samples: 4, coverage_pct: 75,
            unsupported_channel_samples: 1, unsupported_channel_families: {ofdm: 1, ofdma: 0},
            capacity_sample_count: 2};
        data.capacity_history = {downstream: summary, upstream: {...summary, status: 'observed', unsupported_channel_samples: 0}};
        b.init();
        await b.reply(data);
        const text = id => b.ids.get(id).textContent;
        assert.equal(text('mod-capacity-range-label'), 'Period 7');
        for (const [field, value] of [['current', '123.5'], ['min', '100.0'], ['avg', '120.0'], ['max', '140.0']]) {
            assert.equal(text('mod-cap-ds-' + field), value + (lang === 'de' ? ' Mbit/s' : ' Mbps'));
        }
        assert.equal(text('mod-cap-ds-coverage'), 'Coverage 3/4 = 75.0%');
        assert.equal(text('mod-cap-ds-caveat'), 'Excluded: OFDM');
        assert.equal(b.ids.get('mod-cap-ds-caveat').hidden, false);
        assert.equal(b.ids.get('mod-cap-us-caveat').hidden, true);
        assert.equal(text('mod-cap-us-status'), catalog.capacity_status_observed);
        assert.ok(b.ids.get('mod-capacity-downstream').className.includes('mod-capacity-observed'));
        assert.equal(text('mod-kpi-lowqam-hint'), 'Translated denominator');
        assert.ok(text('mod-dist-legend-0').includes('Translated context'));
        b.ranges[2].click();
        await b.reply(data);
        assert.equal(text('mod-capacity-range-label'), 'Period 30');
        b.ranges[0].click();
        assert.equal(b.requests.at(-1).url, '/docsight/api/modulation/intraday?direction=us');
        await b.reply({date: '2026-03-03', protocol_groups: [], capacity_history: data.capacity_history});
        assert.equal(text('mod-capacity-range-label'), 'Selected day: 2026-03-03');
        summary.unsupported_channel_families = {};
        summary.capacity_current_mbps = null;
        delete T['docsight.modulation.capacity_status_observed'];
        b.ranges[1].click();
        await b.reply(data);
        assert.equal(text('mod-cap-us-status'), 'Observed for selected period');
        assert.equal(text('mod-cap-ds-current'), '—');
        assert.equal(text('mod-cap-ds-caveat'), catalog.capacity_partial_caveat_generic);
        b.ranges[1].click();
        await b.reply(overview());
        assert.equal(b.ids.get('modulation-capacity-panel').style.display, 'none');
    });
}

for (const direction of ['us', 'ds']) {
    for (const count of [7, 30]) {
        test(`${direction} ${count}d modulation curves have no persistent points`, async () => {
            const b = browser();
            b.init();
            await b.reply(overview(direction, '3.0', count));
            assert.equal(b.charts.length, 2);
            for (const chart of b.charts) {
                for (const series of chart.options.series.slice(1)) {
                    assert.equal(series.points.show, false, series.label);
                }
            }
        });
    }
}

test('intraday stepped modulation curve has no persistent points', () => {
    const b = browser();
    b.context.renderChannelTimeline('modulation-intraday-content', [
        {time: '12:00', modulation: '64QAM'}, {time: '12:05', modulation: '16QAM'},
    ]);
    const chart = b.charts[0];
    assert.equal(chart.options.series[1].points.show, false);
    assert.equal(typeof chart.options.series[1].paths, 'function');
    assert.equal(chart.options.cursor.show, true);
});
