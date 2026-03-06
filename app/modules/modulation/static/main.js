/* ── Modulation Performance Module (v2) ── */

var _modDirection = 'us';
var _modDays = 7;
var _modCharts = [];
var _modIntradayCharts = [];

/* QAM color scheme */
var QAM_COLORS = {
    '4QAM':    '#ef4444',
    '16QAM':   '#f97316',
    '64QAM':   '#eab308',
    '256QAM':  '#22c55e',
    '1024QAM': '#10b981',
    '4096QAM': '#3b82f6',
    'OFDM':    '#8b5cf6',
    'OFDMA':   '#8b5cf6',
    'Unknown': '#6b7280'
};

/* ── Direction tabs ── */
var dirTabs = document.querySelectorAll('#modulation-direction-tabs .trend-tab');
dirTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _modDirection = this.getAttribute('data-dir');
        dirTabs.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-dir') === _modDirection);
        });
        updateModulation();
    });
});

/* ── Range tabs ── */
var rangeTabs = document.querySelectorAll('#modulation-range-tabs .trend-tab');
rangeTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _modDays = parseInt(this.getAttribute('data-days'), 10);
        rangeTabs.forEach(function(b) {
            b.classList.toggle('active', parseInt(b.getAttribute('data-days'), 10) === _modDays);
        });
        updateModulation();
    });
});

/* ── Init / Update ── */
function initModulation() {
    updateModulation();
}

function updateModulation() {
    var noData = document.getElementById('modulation-no-data');
    var overview = document.getElementById('modulation-overview');
    var intraday = document.getElementById('modulation-intraday');
    if (noData) noData.style.display = 'none';

    if (_modDays === 1) {
        if (overview) overview.style.display = 'none';
        if (intraday) intraday.style.display = '';
        fetchIntraday('');
    } else {
        if (overview) overview.style.display = '';
        if (intraday) intraday.style.display = 'none';
        fetchOverview();
    }
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
    fetch('/api/modulation/distribution?direction=' + _modDirection + '&days=' + _modDays)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var noData = document.getElementById('modulation-no-data');
            var kpis = document.getElementById('modulation-kpis');

            if (!data.protocol_groups || data.protocol_groups.length === 0) {
                if (noData) noData.style.display = 'block';
                if (kpis) kpis.style.display = 'none';
                destroyCharts();
                return;
            }
            if (kpis) kpis.style.display = '';
            updateOverviewKPIs(data);
            renderProtocolGroups(data);
            showDisclaimer(data.disclaimer);
        }).catch(function(err) {
            console.error('Modulation fetch error:', err);
            var noData = document.getElementById('modulation-no-data');
            if (noData) {
                noData.textContent = T['docsight.modulation.no_data'] || T.no_data || 'No modulation data available.';
                noData.style.display = 'block';
            }
        });
}

function updateOverviewKPIs(data) {
    var agg = data.aggregate || {};
    var hi = agg.health_index;
    var lq = agg.low_qam_pct || 0;
    var density = data.sample_density || 0;

    var hiEl = document.getElementById('mod-kpi-health');
    if (hiEl) {
        hiEl.textContent = hi !== null && hi !== undefined ? hi.toFixed(1) : '—';
        hiEl.className = 'modulation-kpi-value ' + healthClass(hi);
    }
    var hiDelta = document.getElementById('mod-kpi-health-delta');
    if (hiDelta) hiDelta.textContent = hi !== null ? '/100' : '';

    var lqEl = document.getElementById('mod-kpi-lowqam');
    if (lqEl) {
        lqEl.textContent = lq.toFixed(1) + '%';
        lqEl.className = 'modulation-kpi-value ' + lowQamClass(lq);
    }
    var lqHint = document.getElementById('mod-kpi-lowqam-hint');
    if (lqHint) lqHint.textContent = '\u2264 16QAM';

    var dEl = document.getElementById('mod-kpi-density');
    if (dEl) {
        dEl.textContent = (density * 100).toFixed(0) + '%';
        dEl.className = 'modulation-kpi-value ' + densityClass(density);
    }
    var dHint = document.getElementById('mod-kpi-density-hint');
    if (dHint) {
        dHint.textContent = data.sample_count + ' / ' + data.expected_samples +
            ' ' + (T['docsight.modulation.samples'] || T.samples || 'samples');
    }
}

function renderProtocolGroups(data) {
    destroyCharts();
    var container = document.getElementById('modulation-protocol-groups');
    if (!container) return;
    container.textContent = '';

    var groups = data.protocol_groups || [];
    groups.forEach(function(pg, idx) {
        var section = _el('div', 'mod-protocol-group');

        // Header
        var header = _el('div', 'mod-protocol-group-header');
        var dirLabel = _modDirection === 'us'
            ? (T['docsight.modulation.upstream'] || 'Upstream')
            : (T['docsight.modulation.downstream'] || 'Downstream');
        var titleText = dirLabel + ' DOCSIS ' + pg.docsis_version + ' (max ' + pg.max_qam + ')';
        header.appendChild(_el('h3', null, titleText));

        var chBadge = _el('span', 'mod-protocol-badge',
            pg.channel_count + ' ' + (T['docsight.modulation.channels_label'] || 'Channels'));
        header.appendChild(chBadge);

        if (pg.degraded_channel_count > 0) {
            var degBadge = _el('span', 'mod-protocol-badge degraded',
                pg.degraded_channel_count + ' ' + (T['docsight.modulation.degraded_channels'] || 'degraded'));
            header.appendChild(degBadge);
        }
        section.appendChild(header);

        // Mini KPIs
        var kpiRow = _el('div', 'mod-group-kpi-row');
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.health_index'] || 'Health Index',
            pg.health_index !== null ? pg.health_index.toFixed(1) : '\u2014',
            healthClass(pg.health_index)));
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.low_qam_pct'] || 'Low-QAM %',
            pg.low_qam_pct.toFixed(1) + '%',
            lowQamClass(pg.low_qam_pct)));
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.dominant_modulation'] || 'Dominant',
            pg.dominant_modulation || '\u2014', ''));
        kpiRow.appendChild(_buildMiniKPI(
            T['docsight.modulation.degraded_channels'] || 'Degraded',
            pg.degraded_channel_count + '/' + pg.channel_count,
            pg.degraded_channel_count > 0 ? 'critical' : 'good'));
        section.appendChild(kpiRow);

        // Charts grid
        var chartsGrid = _el('div', 'charts-grid');

        // Distribution bar chart card
        var barCard = _el('div', 'chart-card');
        var barHeader = _el('div', 'chart-card-header');
        var barContent = _el('div', 'chart-header-content');
        barContent.appendChild(_el('div', 'chart-label',
            T['docsight.modulation.distribution_chart'] || 'Modulation Distribution'));
        barHeader.appendChild(barContent);
        barCard.appendChild(barHeader);
        var barWrap = _el('div', 'modulation-chart-wrap');
        var barCanvas = document.createElement('canvas');
        barCanvas.id = 'mod-dist-chart-' + idx;
        barWrap.appendChild(barCanvas);
        barCard.appendChild(barWrap);
        chartsGrid.appendChild(barCard);

        // Trend line chart card
        var trendCard = _el('div', 'chart-card');
        var trendHeader = _el('div', 'chart-card-header');
        var trendContent = _el('div', 'chart-header-content');
        trendContent.appendChild(_el('div', 'chart-label',
            T['docsight.modulation.trend_chart'] || 'Health Trend'));
        trendHeader.appendChild(trendContent);
        trendCard.appendChild(trendHeader);
        var trendWrap = _el('div', 'modulation-chart-wrap');
        var trendCanvas = document.createElement('canvas');
        trendCanvas.id = 'mod-trend-chart-' + idx;
        trendWrap.appendChild(trendCanvas);
        trendCard.appendChild(trendWrap);
        chartsGrid.appendChild(trendCard);

        section.appendChild(chartsGrid);
        container.appendChild(section);

        renderGroupDistChart(pg, idx);
        renderGroupTrendChart(pg, idx);
    });

    var hint = document.getElementById('mod-click-hint');
    if (hint) hint.style.display = groups.length > 0 ? 'flex' : 'none';
}

function _buildMiniKPI(label, value, cls) {
    var kpi = _el('div', 'mod-group-kpi');
    kpi.appendChild(_el('div', 'mod-group-kpi-label', label));
    kpi.appendChild(_el('div', 'mod-group-kpi-value ' + cls, value));
    return kpi;
}

function renderGroupDistChart(pg, idx) {
    var ctx = document.getElementById('mod-dist-chart-' + idx);
    if (!ctx) return;

    var days = pg.days || [];
    var labels = days.map(function(d) { return d.date; });

    var allMods = {};
    days.forEach(function(d) {
        Object.keys(d.distribution || {}).forEach(function(k) { allMods[k] = true; });
    });
    var modKeys = Object.keys(allMods).sort(function(a, b) {
        return modSortOrder(a) - modSortOrder(b);
    });

    var datasets = modKeys.map(function(mod) {
        return {
            label: mod,
            data: days.map(function(d) { return (d.distribution || {})[mod] || 0; }),
            backgroundColor: QAM_COLORS[mod] || '#6b7280',
            borderWidth: 0,
            borderSkipped: false,
            borderRadius: 2
        };
    });

    var chart = new Chart(ctx, {
        type: 'bar',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onClick: function(evt, elements) {
                if (elements.length > 0) {
                    var index = elements[0].index;
                    modDrillIntoDay(labels[index]);
                }
            },
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, color: _cssVar('--text') || '#e5e7eb' } },
                tooltip: {
                    callbacks: {
                        label: function(c) { return c.dataset.label + ': ' + c.parsed.y.toFixed(1) + '%'; }
                    }
                }
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { display: false },
                    ticks: { color: _cssVar('--text-secondary') || '#9ca3af' }
                },
                y: {
                    stacked: true,
                    min: 0, max: 100,
                    ticks: {
                        callback: function(v) { return v + '%'; },
                        color: _cssVar('--text-secondary') || '#9ca3af'
                    },
                    grid: { color: 'rgba(255,255,255,0.06)' }
                }
            }
        }
    });
    _modCharts.push(chart);
}

function renderGroupTrendChart(pg, idx) {
    var ctx = document.getElementById('mod-trend-chart-' + idx);
    if (!ctx) return;

    var days = pg.days || [];
    var labels = days.map(function(d) { return d.date; });
    var textColor = _cssVar('--text-secondary') || '#9ca3af';

    var chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: T['docsight.modulation.health_index'] || 'Health Index',
                    data: days.map(function(d) { return d.health_index; }),
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34,197,94,0.1)',
                    fill: true, tension: 0.3, yAxisID: 'y', pointRadius: 3
                },
                {
                    label: T['docsight.modulation.low_qam_pct'] || 'Low-QAM %',
                    data: days.map(function(d) { return d.low_qam_pct; }),
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239,68,68,0.1)',
                    fill: true, tension: 0.3, yAxisID: 'y1', pointRadius: 3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, color: textColor } },
                tooltip: {
                    callbacks: {
                        label: function(c) {
                            var suffix = c.datasetIndex === 0 ? '/100' : '%';
                            var val = c.parsed.y;
                            return c.dataset.label + ': ' + (val !== null ? val.toFixed(1) : '\u2014') + suffix;
                        }
                    }
                }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: textColor } },
                y: {
                    type: 'linear', position: 'left', min: 0, max: 100,
                    title: { display: true, text: T['docsight.modulation.health_index'] || 'Health Index', color: textColor },
                    ticks: { color: textColor },
                    grid: { color: 'rgba(255,255,255,0.06)' }
                },
                y1: {
                    type: 'linear', position: 'right', min: 0,
                    title: { display: true, text: T['docsight.modulation.low_qam_pct'] || 'Low-QAM %', color: textColor },
                    ticks: { callback: function(v) { return v + '%'; }, color: textColor },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
    _modCharts.push(chart);
}

/* ── Intraday (single day) ── */
function modDrillIntoDay(dateStr) {
    var overview = document.getElementById('modulation-overview');
    var intraday = document.getElementById('modulation-intraday');
    if (overview) overview.style.display = 'none';
    if (intraday) intraday.style.display = '';
    fetchIntraday(dateStr);
}

function modBackToOverview() {
    var overview = document.getElementById('modulation-overview');
    var intraday = document.getElementById('modulation-intraday');
    if (overview) overview.style.display = '';
    if (intraday) intraday.style.display = 'none';
    destroyIntradayCharts();
    if (_modDays === 1) {
        _modDays = 7;
        rangeTabs.forEach(function(b) {
            b.classList.toggle('active', parseInt(b.getAttribute('data-days'), 10) === _modDays);
        });
    }
    fetchOverview();
}

function fetchIntraday(dateStr) {
    var url = '/api/modulation/intraday?direction=' + _modDirection;
    if (dateStr) url += '&date=' + dateStr;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            renderIntraday(data);
            showDisclaimer(data.disclaimer);
        }).catch(function(err) {
            console.error('Modulation intraday fetch error:', err);
        });
}

function renderIntraday(data) {
    destroyIntradayCharts();
    var titleEl = document.getElementById('mod-intraday-title');
    if (titleEl) {
        titleEl.textContent = (T['docsight.modulation.intraday_title'] || 'Channel Detail') +
            ' \u2014 ' + data.date;
    }

    var container = document.getElementById('modulation-intraday-content');
    if (!container) return;
    container.textContent = '';

    var groups = data.protocol_groups || [];
    if (groups.length === 0) {
        container.appendChild(_el('div', 'no-data-msg',
            T['docsight.modulation.no_data'] || 'No data for this day.'));
        return;
    }

    groups.forEach(function(pg) {
        var section = _el('div', 'mod-protocol-group');

        var dirLabel = _modDirection === 'us'
            ? (T['docsight.modulation.upstream'] || 'Upstream')
            : (T['docsight.modulation.downstream'] || 'Downstream');
        var header = _el('div', 'mod-protocol-group-header');
        header.appendChild(_el('h3', null,
            dirLabel + ' DOCSIS ' + pg.docsis_version + ' (max ' + pg.max_qam + ')'));
        section.appendChild(header);

        var channels = pg.channels || [];
        channels.forEach(function(ch) {
            var card = _el('div', 'mod-channel-summary' + (ch.degraded ? ' degraded' : ''));

            var chHeader = _el('div', 'mod-channel-summary-header');
            chHeader.appendChild(_el('strong', null, 'Ch ' + ch.channel_id));
            chHeader.appendChild(_el('span', 'mod-protocol-badge', ch.frequency + ' MHz'));
            var hiText = ch.health_index !== null ? ch.health_index.toFixed(1) + '/100' : '\u2014';
            chHeader.appendChild(_el('span', 'mod-protocol-badge ' + healthClass(ch.health_index), hiText));
            card.appendChild(chHeader);

            if (ch.summary) {
                card.appendChild(_el('div', 'mod-channel-summary-text', ch.summary));
            } else {
                card.appendChild(_el('div', 'mod-channel-summary-text',
                    T['docsight.modulation.no_degradation'] || 'No degradation observed'));
            }

            if (ch.timeline && ch.timeline.length > 1) {
                var chartWrap = _el('div', 'modulation-intraday-chart-wrap');
                var canvasId = 'mod-intraday-ch-' + pg.docsis_version.replace('.', '') + '-' + ch.channel_id;
                var canvas = document.createElement('canvas');
                canvas.id = canvasId;
                chartWrap.appendChild(canvas);
                card.appendChild(chartWrap);
                section.appendChild(card);
                renderChannelTimeline(canvasId, ch.timeline);
            } else {
                section.appendChild(card);
            }
        });

        container.appendChild(section);
    });
}

function renderChannelTimeline(canvasId, timeline) {
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;

    var labels = timeline.map(function(t) { return t.time; });
    var dataPoints = timeline.map(function(t) { return modSortOrder(t.modulation); });
    var bgColors = timeline.map(function(t) { return QAM_COLORS[t.modulation] || '#6b7280'; });

    var chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                data: dataPoints,
                borderColor: bgColors,
                backgroundColor: bgColors[0],
                segment: {
                    borderColor: function(c) { return bgColors[c.p0DataIndex] || '#6b7280'; }
                },
                stepped: true, fill: false, pointRadius: 4,
                pointBackgroundColor: bgColors, borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(c) { return timeline[c.dataIndex].modulation; }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: _cssVar('--text-secondary') || '#9ca3af', maxTicksLimit: 12 }
                },
                y: {
                    min: -0.5, max: 8.5,
                    ticks: {
                        callback: function(v) {
                            var l = ['4QAM', '16QAM', '64QAM', '256QAM', '1024QAM', '4096QAM', 'OFDM', 'OFDMA', 'Unknown'];
                            return l[v] || '';
                        },
                        stepSize: 1,
                        color: _cssVar('--text-secondary') || '#9ca3af'
                    },
                    grid: { color: 'rgba(255,255,255,0.04)' }
                }
            }
        }
    });
    _modIntradayCharts.push(chart);
}

/* ── Disclaimer ── */
function showDisclaimer(text) {
    var el = document.getElementById('mod-disclaimer');
    var textEl = document.getElementById('mod-disclaimer-text');
    if (el && textEl) {
        textEl.textContent = T['docsight.modulation.disclaimer'] || text || '';
        el.style.display = 'flex';
    } else if (el) {
        el.style.display = 'none';
    }
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
function densityClass(v) {
    if (v > 0.9) return 'good';
    if (v > 0.75) return 'warning';
    return 'critical';
}
function modSortOrder(mod) {
    var order = { '4QAM': 0, '16QAM': 1, '64QAM': 2, '256QAM': 3, '1024QAM': 4, '4096QAM': 5, 'OFDM': 6, 'OFDMA': 7, 'Unknown': 8 };
    return order[mod] !== undefined ? order[mod] : 9;
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
    var view = document.getElementById('view-mod-docsight-modulation');
    if (view && view.classList.contains('active')) {
        initModulation();
    }
})();
