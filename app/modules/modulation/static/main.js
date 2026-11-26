/* ── Modulation Performance Module (v2) ── */

var _modDirection = 'us';
var _modDays = 7;
var _modCharts = [];
var _modIntradayCharts = [];

/* QAM color scheme */
var QAM_COLORS = {
    '4QAM':    '#ef4444',
    '8QAM':    '#fb7185',
    '16QAM':   '#f97316',
    '32QAM':   '#f59e0b',
    '64QAM':   '#eab308',
    '128QAM':  '#84cc16',
    '256QAM':  '#22c55e',
    '512QAM':  '#14b8a6',
    '1024QAM': '#06b6d4',
    '4096QAM': '#3b82f6',
    'OFDM':    '#8b5cf6',
    'OFDMA':   '#8b5cf6',
    'Unknown': '#6b7280'
};

/* US DOCSIS 3.1 upstream context coloring.
   In a max 1024QAM upstream group, 64QAM and below are Low-QAM (red family),
   128QAM is not Low-QAM but is not unambiguously healthy (amber/warning),
   256QAM and above read as healthy (green family).
   Other contexts keep the global QAM_COLORS palette unchanged. */
var QAM_COLORS_US_DOCSIS_31 = {
    'QPSK':    '#b91c1c',
    '4QAM':    '#b91c1c',
    '8QAM':    '#dc2626',
    '16QAM':   '#ef4444',
    '32QAM':   '#dc2626',
    '64QAM':   '#fb7185',
    '128QAM':  '#f59e0b',
    '256QAM':  '#86efac',
    '512QAM':  '#22c55e',
    '1024QAM': '#16a34a',
    '4096QAM': '#15803d',
    'OFDM':    '#22c55e',
    'OFDMA':   '#22c55e',
    'Unknown': '#6b7280'
};

/* US DOCSIS 3.0 upstream context coloring.
   In DOCSIS 3.0 upstream charts, 64QAM is the expected healthy maximum,
   32QAM is reduced/warning, and 16QAM and below are degraded.
   Downstream and non-DOCSIS 3.0 contexts keep the global palette unchanged. */
var QAM_COLORS_US_DOCSIS_30 = {
    'QPSK':    '#b91c1c',
    '4QAM':    '#b91c1c',
    '8QAM':    '#dc2626',
    '16QAM':   '#ef4444',
    '32QAM':   '#f59e0b',
    '64QAM':   '#22c55e',
    '128QAM':  '#84cc16',
    '256QAM':  '#22c55e',
    '512QAM':  '#14b8a6',
    '1024QAM': '#06b6d4',
    '4096QAM': '#3b82f6',
    'OFDM':    '#8b5cf6',
    'OFDMA':   '#8b5cf6',
    'Unknown': '#6b7280'
};

/* '3.1' or '3.0' for an upstream group of that DOCSIS version, '' otherwise. */
function usDocsisVersion(pg) {
    var version = pg && (pg._direction || pg.direction) === 'us' ? String(pg.docsis_version || '') : '';
    return version === '3.1' || version === '3.0' ? version : '';
}

function qamColorForContext(mod, pg) {
    var palette = {'3.1': QAM_COLORS_US_DOCSIS_31, '3.0': QAM_COLORS_US_DOCSIS_30}[usDocsisVersion(pg)];
    if (palette && Object.prototype.hasOwnProperty.call(palette, mod)) return palette[mod];
    return QAM_COLORS[mod] || '#6b7280';
}

function lowQamLegendHintForContext(pg) {
    var version = usDocsisVersion(pg);
    if (version === '3.1') {
        return T['docsight.modulation.low_qam_legend_hint_d31_us'] ||
            T.low_qam_legend_hint_d31_us;
    }
    if (version === '3.0') {
        return T['docsight.modulation.low_qam_legend_hint_d30_us'] ||
            T.low_qam_legend_hint_d30_us;
    }
    return '';
}

/* Day labels (day and month in the UI language), x data, x scale and x axis
   shared by the distribution and trend charts. */
function _modDayAxis(days, width) {
    var labels = days.map(function(d) { return docsightFormatAxisTime(d.date, 'monthday') || d.date.slice(5); });
    var splits = buildEvenIndexTicks(labels.length, calculateMaxXTicks(labels, width, 40, 8));
    return {
        labels: labels,
        xData: labels.map(function(_, i) { return i; }),
        scale: {time: false, range: function() { return [-0.5, labels.length - 0.5]; }},
        axis: {
            scale: 'x',
            splits: function() { return splits; },
            values: function(u, vals) { return vals.map(function(v) { return labels[v] || ''; }); },
            stroke: _cssVar('--text-secondary') || '#9ca3af',
            grid: {show: false},
            font: '12px system-ui',
            gap: 4
        }
    };
}

var MODULATION_LEVELS = [
    '4QAM',
    '8QAM',
    '16QAM',
    '32QAM',
    '64QAM',
    '128QAM',
    '256QAM',
    '512QAM',
    '1024QAM',
    '4096QAM',
    'OFDM',
    'OFDMA',
    'Unknown'
];

/* ── Direction tabs ── */
var dirTabs = document.querySelectorAll('#modulation-direction-tabs .segmented-option');
dirTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _modDirection = this.getAttribute('data-dir');
        syncSegments('modulation-direction-tabs', function(b) { return b.getAttribute('data-dir') === _modDirection; });
        _modWriteViewState();
        updateModulation();
    });
});

/* ── Range tabs ── */
var rangeTabs = document.querySelectorAll('#modulation-range-tabs .segmented-option');
rangeTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _modDays = parseInt(this.getAttribute('data-days'), 10);
        syncSegments('modulation-range-tabs', function(b) { return parseInt(b.getAttribute('data-days'), 10) === _modDays; });
        _modWriteViewState();
        updateModulation();
    });
});

/* ── Init / Update ── */
function _modWriteViewState() {
    docsightWriteViewState('modulation', {dir: _modDirection, days: _modDays});
}

function initModulation() {
    var state = docsightReadViewState('modulation');
    if (docsightSelectSegment('modulation-direction-tabs', 'data-dir', state.dir)) _modDirection = state.dir;
    if (docsightSelectSegment('modulation-range-tabs', 'data-days', state.days)) _modDays = parseInt(state.days, 10);
    updateModulation();
}

function updateModulation() {
    var noData = document.getElementById('modulation-no-data');
    var overview = document.getElementById('modulation-overview');
    var intraday = document.getElementById('modulation-intraday');
    DOCSightEmptyState.hide(noData);

    if (_modDays === 1) {
        overview.hidden = true;
        intraday.hidden = false;
        fetchIntraday('');
    } else {
        overview.hidden = false;
        intraday.hidden = true;
        fetchOverview();
    }
}

/* No modulation data in the selected range: offer the longest range. */
function _showModulationEmpty(el) {
    DOCSightEmptyState.showRange(el, {
        tabs: 'modulation-range-tabs',
        text: T['docsight.modulation.no_data'],
        glossary: 'modulation_performance'
    });
}

/* ── DOM helpers ── */
function _el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
}

function _cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name);
}

/* ── Overview (multi-day) ── */
function fetchOverview() {
    fetch(docsightUrl('/api/modulation/distribution?direction=' + _modDirection + '&days=' + _modDays))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var noData = document.getElementById('modulation-no-data');
            var kpis = document.getElementById('modulation-kpis');

            if (!data.protocol_groups || data.protocol_groups.length === 0) {
                _showModulationEmpty(noData);
                kpis.style.display = 'none';
                destroyCharts();
                return;
            }
            kpis.style.display = '';
            updateOverviewKPIs(data);
            updateCapacityHistory(data, rangeLabelForCapacity(data));
            renderProtocolGroups(data);
            showDisclaimer(data.disclaimer);
        }).catch(function(err) {
            console.error('Modulation fetch error:', err);
            DOCSightEmptyState.showError(document.getElementById('modulation-no-data'), {retry: fetchOverview});
        });
}

function updateOverviewKPIs(data) {
    var agg = data.aggregate || {};
    var hi = agg.health_index;
    var lq = agg.low_qam_pct || 0;

    var hiEl = document.getElementById('mod-kpi-health');
    hiEl.textContent = hi !== null && hi !== undefined ? hi.toFixed(1) : '—';
    hiEl.className = 'mod-kpi-item-value ' + healthClass(hi);
    document.getElementById('mod-kpi-health-delta').textContent = hi !== null ? '/100' : '';

    var lqEl = document.getElementById('mod-kpi-lowqam');
    lqEl.textContent = lq.toFixed(1) + '%';
    lqEl.className = 'mod-kpi-item-value ' + lowQamClass(lq);
    document.getElementById('mod-kpi-lowqam-hint').textContent = T['docsight.modulation.low_qam_denominator_hint'];

    document.getElementById('mod-kpi-samples').textContent = String(data.sample_count || 0);
}

function capacityUnitLabel() {
    return currentLang === 'de' ? 'Mbit/s' : 'Mbps';
}

function formatCapacityMbps(value) {
    if (value === null || value === undefined) return '\u2014';
    return Number(value).toFixed(1) + ' ' + capacityUnitLabel();
}

function rangeLabelForCapacity(data) {
    if (data && data.date) {
        return T['docsight.modulation.capacity_selected_day'] + ': ' + data.date;
    }
    if (_modDays === 1) {
        return T['docsight.modulation.capacity_today_period'];
    }
    var template = T['docsight.modulation.capacity_selected_days'];
    return template.replace('{days}', String(_modDays));
}

function capacityFamilyLabel(family) {
    var normalized = String(family || '').toLowerCase();
    var fallback = {
        ofdm: 'OFDM',
        ofdma: 'OFDMA',
        unknown: 'unsupported'
    }[normalized] || normalized || 'unsupported';
    return T['docsight.modulation.capacity_family_' + normalized] || fallback;
}

function unsupportedCapacityFamilies(summary) {
    var families = summary && summary.unsupported_channel_families ? summary.unsupported_channel_families : {};
    return Object.keys(families).filter(function(family) {
        return Number(families[family] || 0) > 0;
    }).sort().map(capacityFamilyLabel);
}

function capacityCoverageText(summary) {
    var calculated = summary ? (summary.calculated_channel_samples || 0) : 0;
    var total = summary ? (summary.total_channel_samples || 0) : 0;
    var pct = Number(summary && summary.coverage_pct || 0).toFixed(1);
    var template = T['docsight.modulation.capacity_coverage_detail'];
    return template
        .replace('{calculated}', String(calculated))
        .replace('{total}', String(total))
        .replace('{pct}', pct);
}

function capacityPartialCaveatText(summary) {
    if (!summary || !(summary.unsupported_channel_samples > 0)) return '';
    var families = unsupportedCapacityFamilies(summary);
    if (families.length > 0) {
        var template = T['docsight.modulation.capacity_partial_caveat'];
        return template.replace('{families}', families.join('/'));
    }
    return T['docsight.modulation.capacity_partial_caveat_generic'];
}

function capacityStatusText(summary) {
    if (!summary) return '\u2014';
    var key = 'docsight.modulation.capacity_status_' + summary.status;
    var fallback = {
        observed: 'Observed for selected period',
        unavailable: 'No calculated SC-QAM capacity in selected period'
    }[summary.status] || summary.status || '\u2014';
    var text = T[key] || fallback;
    if (summary.unsupported_channel_samples > 0) {
        text = T['docsight.modulation.capacity_partial_coverage'] + ' · ' + text;
    }
    return text;
}

function updateCapacityCard(direction, summary) {
    var prefix = direction === 'downstream' ? 'ds' : 'us';
    var card = document.getElementById(direction === 'downstream' ? 'mod-capacity-downstream' : 'mod-capacity-upstream');
    if (!card || !summary) return;

    card.className = 'mod-capacity-card mod-capacity-' + (summary.status || 'unavailable');

    function field(name) { return document.getElementById('mod-cap-' + prefix + '-' + name); }
    ['current', 'min', 'avg', 'max'].forEach(function(name) {
        field(name).textContent = formatCapacityMbps(summary['capacity_' + name + '_mbps']);
    });
    field('coverage').textContent = capacityCoverageText(summary);
    field('status').textContent = capacityStatusText(summary);
    var caveatText = capacityPartialCaveatText(summary);
    field('caveat').textContent = caveatText;
    field('caveat').hidden = !caveatText;
}

function updateCapacityHistory(data, rangeLabel) {
    var panel = document.getElementById('modulation-capacity-panel');
    var history = data && data.capacity_history;
    if (!history) {
        panel.hidden = true;
        return;
    }
    panel.hidden = false;
    document.getElementById('mod-capacity-range-label').textContent =
        rangeLabel || T['docsight.modulation.capacity_selected_period'];
    updateCapacityCard('downstream', history.downstream);
    updateCapacityCard('upstream', history.upstream);
}

function renderProtocolGroups(data) {
    destroyCharts();
    var container = document.getElementById('modulation-protocol-groups');
    container.textContent = '';

    var groups = data.protocol_groups || [];
    var renderDirection = data.direction || _modDirection;
    groups.forEach(function(pg, idx) {
        pg._direction = renderDirection;
        var section = _el('div', 'mod-protocol-group');
        section.setAttribute('data-direction', renderDirection);
        section.setAttribute('data-docsis-version', String(pg.docsis_version || ''));

        // Header
        var header = _modGroupHeader(renderDirection, pg);

        var chLabel = pg.channel_count === 1
            ? T['docsight.modulation.channel_label']
            : T['docsight.modulation.channels_label'];
        var chBadge = _el('span', 'mod-protocol-badge', pg.channel_count + ' ' + chLabel);
        header.appendChild(chBadge);

        if (pg.degraded_channel_count > 0) {
            var degBadge = _el('span', 'mod-protocol-badge degraded',
                pg.degraded_channel_count + ' ' + T['docsight.modulation.degraded_channels']);
            header.appendChild(degBadge);
        }
        section.appendChild(header);

        // Mini KPIs
        var kpiRow = _el('div', 'mod-group-kpi-row');
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.health_index'],
            pg.health_index !== null ? pg.health_index.toFixed(1) : '\u2014',
            healthClass(pg.health_index)));
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.low_qam_pct'],
            pg.low_qam_pct.toFixed(1) + '%',
            lowQamClass(pg.low_qam_pct)));
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.dominant_modulation'],
            pg.dominant_modulation || '\u2014', ''));
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.degraded_channels'],
            pg.degraded_channel_count + '/' + pg.channel_count,
            pg.degraded_channel_count > 0 ? 'critical' : 'good'));
        section.appendChild(kpiRow);

        // Charts grid
        var chartsGrid = _el('div', 'charts-grid');

        var barCard = _modChartCard(T['docsight.modulation.distribution_chart'],
            'mod-dist-chart-' + idx);
        var legendDiv = _el('div', 'modulation-custom-legend');
        legendDiv.id = 'mod-dist-legend-' + idx;
        barCard.appendChild(legendDiv);
        chartsGrid.appendChild(barCard);
        chartsGrid.appendChild(_modChartCard(T['docsight.modulation.trend_chart'],
            'mod-trend-chart-' + idx));

        section.appendChild(chartsGrid);
        container.appendChild(section);

        renderGroupDistChart(pg, idx);
        renderGroupTrendChart(pg, idx);
    });

    document.getElementById('mod-click-hint').hidden = groups.length === 0;
}

/* Group heading: direction, DOCSIS version and highest modulation. */
function _modGroupHeader(direction, pg) {
    var header = _el('div', 'mod-protocol-group-header');
    var dirLabel = direction === 'us'
        ? T['docsight.modulation.upstream']
        : T['docsight.modulation.downstream'];
    header.appendChild(_el('h3', null, dirLabel + ' DOCSIS ' + pg.docsis_version + ' (max ' + pg.max_qam + ')'));
    return header;
}

/* Chart container filling a wrapper of class `cls`. */
function _modChartWrap(cls, id) {
    var wrap = _el('div', cls);
    var chart = _el('div');
    chart.id = id;
    chart.style.width = '100%';
    chart.style.height = '100%';
    wrap.appendChild(chart);
    return wrap;
}

function _modChartCard(title, id) {
    var card = _el('div', 'chart-card');
    var header = _el('div', 'chart-card-header');
    var content = _el('div', 'chart-header-content');
    content.appendChild(_el('div', 'chart-label', title));
    header.appendChild(content);
    card.appendChild(header);
    card.appendChild(_modChartWrap('modulation-chart-wrap', id));
    return card;
}

function _buildMiniKPI(label, value, cls) {
    var kpi = _el('div', 'mod-group-kpi');
    kpi.appendChild(_el('div', 'mod-group-kpi-label', label));
    kpi.appendChild(_el('div', 'mod-group-kpi-value ' + cls, value));
    return kpi;
}

function renderGroupDistChart(pg, idx) {
    var container = document.getElementById('mod-dist-chart-' + idx);
    var days = pg.days || [];
    var allMods = {};
    days.forEach(function(d) {
        Object.keys(d.distribution || {}).forEach(function(k) { allMods[k] = true; });
    });
    var modKeys = Object.keys(allMods).sort(function(a, b) {
        return modSortOrder(a) - modSortOrder(b);
    });

    var barPaths = uPlot.paths.bars({size: [0.7, 50], gap: 1});

    /* uPlot stacked bars: cumulative sums for each modulation layer */
    var cumData = days.map(function() { return 0; });
    var layerData = [];
    var rawSeriesByMod = {};
    modKeys.forEach(function(mod) {
        var raw = days.map(function(d) { return (d.distribution || {})[mod] || 0; });
        rawSeriesByMod[mod] = raw;
        var stacked = raw.map(function(v, j) { cumData[j] += v; return cumData[j]; });
        layerData.push({ mod: mod, data: stacked });
    });

    renderDistributionLegend(document.getElementById('mod-dist-legend-' + idx), modKeys, pg);
    var w = container.offsetWidth || 400;
    var x = _modDayAxis(days, w);

    /* Render in reverse order: largest cumulative first, smallest on top */
    var uData = [x.xData];
    var uSeries = [{ label: 'X', value: function(u, v) { return x.labels[v] || ''; } }];
    for (var li = layerData.length - 1; li >= 0; li--) {
        var layer = layerData[li];
        var layerColor = qamColorForContext(layer.mod, pg);
        uData.push(layer.data);
        uSeries.push({
            label: layer.mod,
            stroke: layerColor,
            fill: layerColor,
            width: 0,
            paths: barPaths,
            points: { show: false }
        });
    }

    var chart = new uPlot({
        width: w,
        height: container.offsetHeight || 300,
        scales: {
            x: x.scale,
            y: { range: [0, 100] }
        },
        axes: [
            x.axis,
            {
                scale: 'y',
                stroke: x.axis.stroke,
                grid: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
                values: function(u, vals) { return vals.map(function(v) { return v + '%'; }); },
                font: '12px system-ui',
                size: docsightAxisSize(0)
            }
        ],
        series: uSeries,
        cursor: { show: true, x: true, y: false, points: { show: false } },
        legend: { show: false, live: false },
        plugins: [tooltipPlugin(x.labels, function(ctx) {
            var mod = ctx.dataset.label;
            var rawSeries = rawSeriesByMod[mod] || [];
            var raw = rawSeries[ctx.dataIndex] || 0;
            return mod + ': ' + raw.toFixed(1) + '%';
        }), touchScrubPlugin()]
    }, uData, container);
    attachModulationDayClick(chart, container, days);
    _modCharts.push(chart);
}

function attachModulationDayClick(chart, container, days) {
    if (!chart || !container || !days || !days.length) return;
    container.classList.add('modulation-clickable-chart');
    container.setAttribute(
        'title',
        T['docsight.modulation.click_day_hint']
    );
    container.addEventListener('click', function(evt) {
        var rect = chart.over.getBoundingClientRect();
        var left = evt.clientX - rect.left;
        if (left < 0 || left > rect.width) return;
        var xVal = chart.posToVal(left, 'x');
        var idx = Math.round(xVal);
        if (idx < 0 || idx >= days.length) return;
        var day = days[idx];
        if (day && day.date) {
            modDrillIntoDay(day.date);
        }
    });
}

function renderGroupTrendChart(pg, idx) {
    var container = document.getElementById('mod-trend-chart-' + idx);
    var days = pg.days || [];
    var w = container.offsetWidth || 400;
    var x = _modDayAxis(days, w);
    var chart = new uPlot({
        width: w,
        height: container.offsetHeight || 300,
        scales: {
            x: x.scale,
            health: { range: [0, 100] },
            lowqam: { range: [0, 100] }
        },
        axes: [
            x.axis,
            {
                scale: 'health',
                side: 3,
                stroke: '#22c55e',
                grid: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
                font: '12px system-ui',
                size: docsightAxisSize(0)
            },
            {
                scale: 'lowqam',
                side: 1,
                stroke: '#ef4444',
                grid: { show: false },
                values: function(u, vals) { return vals.map(function(v) { return v.toFixed(0) + '%'; }); },
                font: '12px system-ui',
                size: docsightAxisSize(0)
            }
        ],
        series: [
            { label: 'X', value: function(u, v) { return x.labels[v] || ''; } },
            {
                label: T['docsight.modulation.health_index'],
                stroke: '#22c55e',
                fill: 'rgba(34,197,94,0.1)',
                width: 2,
                scale: 'health',
                points: { show: false }
            },
            {
                label: T['docsight.modulation.low_qam_pct'],
                stroke: '#ef4444',
                fill: 'rgba(239,68,68,0.1)',
                width: 2,
                scale: 'lowqam',
                points: { show: false }
            }
        ],
        cursor: { show: true, x: true, y: false, points: { show: false } },
        legend: { show: true, live: false },
        plugins: [tooltipPlugin(x.labels), touchScrubPlugin()]
    }, [
        x.xData,
        days.map(function(d) { return d.health_index; }),
        days.map(function(d) { return d.low_qam_pct; })
    ], container);
    _modCharts.push(chart);
}

/* ── Intraday (single day) ── */
function modDrillIntoDay(dateStr) {
    document.getElementById('modulation-overview').hidden = true;
    document.getElementById('modulation-intraday').hidden = false;
    fetchIntraday(dateStr);
}

function modBackToOverview() {
    document.getElementById('modulation-overview').hidden = false;
    document.getElementById('modulation-intraday').hidden = true;
    destroyIntradayCharts();
    if (_modDays === 1) {
        _modDays = 7;
        syncSegments('modulation-range-tabs', function(b) { return parseInt(b.getAttribute('data-days'), 10) === _modDays; });
        _modWriteViewState();
    }
    fetchOverview();
}

function fetchIntraday(dateStr) {
    var url = docsightUrl('/api/modulation/intraday?direction=' + _modDirection);
    if (dateStr) url += '&date=' + dateStr;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            renderIntraday(data);
            updateCapacityHistory(data, rangeLabelForCapacity(data));
            showDisclaimer(data.disclaimer);
        }).catch(function(err) {
            console.error('Modulation intraday fetch error:', err);
            DOCSightEmptyState.showError(document.getElementById('modulation-no-data'), {
                retry: function() { fetchIntraday(dateStr); }
            });
        });
}

function renderIntraday(data) {
    destroyIntradayCharts();
    document.getElementById('mod-intraday-title').textContent =
        T['docsight.modulation.intraday_title'] + ' \u2014 ' + data.date;

    var container = document.getElementById('modulation-intraday-content');
    container.textContent = '';

    var groups = data.protocol_groups || [];
    if (groups.length === 0) {
        var empty = _el('div', 'view-empty');
        container.appendChild(empty);
        _showModulationEmpty(empty);
        return;
    }

    groups.forEach(function(pg) {
        var section = _el('div', 'mod-protocol-group');
        section.appendChild(_modGroupHeader(data.direction || _modDirection, pg));

        var channels = pg.channels || [];
        channels.forEach(function(ch) {
            var card = _el('div', 'mod-channel-summary' + (ch.degraded ? ' degraded' : ''));

            var chHeader = _el('div', 'mod-channel-summary-header');
            chHeader.appendChild(_el('strong', null, 'Ch ' + ch.channel_id));
            chHeader.appendChild(_el('span', 'mod-protocol-badge', ch.frequency + ' MHz'));
            var hiText = ch.health_index !== null ? ch.health_index.toFixed(1) + '/100' : '\u2014';
            chHeader.appendChild(_el('span', 'mod-protocol-badge ' + healthClass(ch.health_index), hiText));
            card.appendChild(chHeader);

            if (ch.degraded_events && ch.degraded_events.length) {
                card.appendChild(buildIntradayInsights(ch));
                card.appendChild(buildIntradayEventList(ch.degraded_events));
            } else {
                card.appendChild(_el('div', 'mod-channel-summary-text',
                    T['docsight.modulation.no_degradation']));
            }

            section.appendChild(card);
            if (ch.timeline && ch.timeline.length > 1) {
                var canvasId = 'mod-intraday-ch-' + pg.docsis_version.replace('.', '') + '-' + ch.channel_id;
                card.appendChild(_modChartWrap('modulation-intraday-chart-wrap', canvasId));
                renderChannelTimeline(canvasId, ch.timeline);
            }
        });
        container.appendChild(section);
    });
}

function buildIntradayInsights(ch) {
    var wrap = _el('div', 'mod-channel-insights');
    wrap.appendChild(_el(
        'span',
        'mod-channel-insight warning',
        ch.degraded_events.length + ' ' + T['docsight.modulation.degraded_windows']
    ));
    wrap.appendChild(_el(
        'span',
        'mod-channel-insight',
        T['docsight.modulation.affected_samples'] + ' ' + (ch.degraded_sample_pct || 0) + '%'
    ));
    if (ch.worst_modulation) {
        wrap.appendChild(_el(
            'span',
            'mod-channel-insight critical',
            T['docsight.modulation.worst_modulation'] + ' ' + ch.worst_modulation
        ));
    }
    return wrap;
}

function buildIntradayEventList(events) {
    var wrap = _el('div', 'mod-event-list');
    var visibleCount = Math.min(events.length, 4);
    var hiddenRows = [];
    for (var i = 0; i < events.length; i++) {
        var row = buildIntradayEvent(events[i]);
        if (i >= visibleCount) {
            row.style.display = 'none';
            hiddenRows.push(row);
        }
        wrap.appendChild(row);
    }

    if (hiddenRows.length > 0) {
        var expanded = false;
        var toggle = _el('button', 'mod-event-toggle');
        toggle.type = 'button';

        function syncToggleLabel() {
            if (expanded) {
                toggle.textContent = T['docsight.modulation.show_fewer_windows'];
                toggle.classList.add('open');
            } else {
                toggle.textContent = '+' + hiddenRows.length + ' ' +
                    T['docsight.modulation.more_windows'];
                toggle.classList.remove('open');
            }
        }

        toggle.addEventListener('click', function() {
            expanded = !expanded;
            hiddenRows.forEach(function(row) {
                row.style.display = expanded ? '' : 'none';
            });
            syncToggleLabel();
        });

        syncToggleLabel();
        wrap.appendChild(toggle);
    }
    return wrap;
}

function buildIntradayEvent(evt) {
    var row = _el('div', 'mod-event-row');
    var timeText = evt.point_in_time ? evt.start : (evt.start + ' - ' + evt.end);
    row.appendChild(_el('div', 'mod-event-time', timeText));

    var detail = _el('div', 'mod-event-detail');
    detail.appendChild(_el('div', 'mod-event-modulation', evt.label));
    detail.appendChild(_el('div', 'mod-event-duration', formatIntradayEventDuration(evt)));
    row.appendChild(detail);

    var impact = _el('div', 'mod-event-impact');
    impact.appendChild(_el('strong', 'mod-event-share', evt.pct + '%'));
    impact.appendChild(_el('span', 'mod-event-share-label',
        T['docsight.modulation.of_samples']));
    row.appendChild(impact);
    return row;
}

function formatIntradayEventDuration(evt) {
    if (evt.point_in_time) {
        if (evt.count && evt.count > 1) {
            return evt.count + ' ' + sampleUnit(evt.count);
        }
        return T['docsight.modulation.brief_dip'];
    }

    var minutes = evt.duration_minutes || 0;
    if (minutes <= 0) {
        return evt.count + ' ' + sampleUnit(evt.count);
    }
    if (minutes < 60) {
        return minutes + ' min';
    }

    var hours = Math.floor(minutes / 60);
    var remainder = minutes % 60;
    if (remainder === 0) {
        return hours + 'h';
    }
    return hours + 'h ' + remainder + 'm';
}

function sampleUnit(count) {
    return count === 1
        ? T['docsight.modulation.sample_singular']
        : T['docsight.modulation.sample_plural'];
}

function renderChannelTimeline(canvasId, timeline) {
    var container = document.getElementById(canvasId);
    if (!container) return;
    container.textContent = '';

    var labels = timeline.map(function(t) { return t.time; });
    var dataPoints = timeline.map(function(t) { return modSortOrder(t.modulation); });
    var n = labels.length;
    var textColor = _cssVar('--text-secondary') || '#9ca3af';
    var qamLabels = MODULATION_LEVELS;

    var xData = [];
    for (var i = 0; i < n; i++) xData.push(i);

    var w = container.offsetWidth || 400;
    var h = container.offsetHeight || 120;
    var chart = new uPlot({
        width: w,
        height: h,
        scales: {
            x: { time: false, range: function() { return [-0.5, n - 0.5]; } },
            y: { range: [-0.5, qamLabels.length - 0.5] }
        },
        axes: [
            {
                scale: 'x',
                splits: function() { return xData; },
                filter: function(u, splits) {
                    var max = Math.min(12, n);
                    var step = Math.ceil(n / max);
                    return splits.filter(function(v) { return v % step === 0; });
                },
                values: function(u, vals) { return vals.map(function(v) { return labels[v] || ''; }); },
                stroke: textColor,
                grid: { show: false },
                font: '12px system-ui',
                gap: 2
            },
            {
                scale: 'y',
                stroke: textColor,
                grid: { stroke: 'rgba(255,255,255,0.04)', width: 1 },
                splits: function() {
                    return qamLabels.map(function(_, idx) { return idx; });
                },
                values: function(u, vals) { return vals.map(function(v) { return qamLabels[v] || ''; }); },
                font: '12px system-ui',
                size: docsightAxisSize(0)
            }
        ],
        series: [
            { label: 'X', value: function(u, v) { return labels[v] || ''; } },
            {
                label: 'Modulation',
                stroke: '#ffab40',
                width: 2,
                paths: uPlot.paths.stepped({ align: -1 }),
                points: { show: false }
            }
        ],
        cursor: { show: true, x: true, y: false, points: { show: false } },
        legend: { show: false },
        plugins: [tooltipPlugin(labels), touchScrubPlugin()]
    }, [xData, dataPoints], container);
    _modIntradayCharts.push(chart);
}

/* ── Disclaimer ── */
function showDisclaimer(text) {
    document.getElementById('mod-disclaimer-text').textContent = T['docsight.modulation.disclaimer'] || text || '';
    document.getElementById('mod-disclaimer').hidden = false;
}

/* ── Helpers ── */
function healthClass(v) {
    if (v === null || v === undefined) return '';
    if (v > 75) return 'good';
    if (v > 50) return 'warning';
    return 'critical';
}
function lowQamClass(v) {
    if (v < 5) return 'good';
    if (v < 15) return 'warning';
    return 'critical';
}
function modSortOrder(mod) {
    var i = MODULATION_LEVELS.indexOf(mod);
    return i < 0 ? MODULATION_LEVELS.length - 1 : i;
}

function renderDistributionLegend(container, modKeys, pg) {
    modKeys.forEach(function(mod) {
        var item = _el('div', 'modulation-custom-legend-item');
        var swatch = _el('span', 'modulation-custom-legend-swatch');
        swatch.style.background = qamColorForContext(mod, pg);
        item.appendChild(swatch);
        item.appendChild(_el('span', 'modulation-custom-legend-label', mod));
        container.appendChild(item);
    });

    var hintText = lowQamLegendHintForContext(pg);
    if (hintText) {
        var hint = _el('div', 'modulation-custom-legend-hint', hintText);
        container.appendChild(hint);
    }
}

function destroyCharts() {
    _modCharts.forEach(function(c) { if (c) c.destroy(); });
    _modCharts = [];
}
function destroyIntradayCharts() {
    _modIntradayCharts.forEach(function(c) { if (c) c.destroy(); });
    _modIntradayCharts = [];
}

/* ── Exports ── */
window.initModulation = initModulation;
window.modDrillIntoDay = modDrillIntoDay;
window.modBackToOverview = modBackToOverview;

/* ── Auto-init ── */
(function() {
    var view = document.getElementById('view-modulation');
    if (view && view.classList.contains('active')) {
        initModulation();
    }
})();
