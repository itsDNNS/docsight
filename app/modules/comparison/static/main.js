/* -- Before/After Comparison Module -- */

var _cmpInitialized = false;
var _cmpLastResult = null;
var _cmpPreset = 'yesterday_today';
var _cmpCases = [];
var _CMP_LINKABLE_PRESETS = ['yesterday_today', 'last_this_week', 'peak_offpeak', 'custom'];

/* ── Preset Definitions ── */
function _cmpPresetDates(preset) {
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var yesterday = new Date(today.getTime() - 86400000);

    switch (preset) {
        case 'yesterday_today':
            return {
                fromA: _cmpFmtDT(yesterday, 0, 0),
                toA: _cmpFmtDT(yesterday, 23, 59),
                fromB: _cmpFmtDT(today, 0, 0),
                toB: _cmpFmtDT(now)
            };
        case 'last_this_week': {
            var dow = today.getDay() || 7; // Mon=1 ... Sun=7
            var thisMonday = new Date(today.getTime() - (dow - 1) * 86400000);
            var lastMonday = new Date(thisMonday.getTime() - 7 * 86400000);
            var lastSunday = new Date(thisMonday.getTime() - 86400000);
            return {
                fromA: _cmpFmtDT(lastMonday, 0, 0),
                toA: _cmpFmtDT(lastSunday, 23, 59),
                fromB: _cmpFmtDT(thisMonday, 0, 0),
                toB: _cmpFmtDT(now)
            };
        }
        case 'peak_offpeak':
            return {
                fromA: _cmpFmtDT(today, 18, 0),
                toA: _cmpFmtDT(today, 22, 0),
                fromB: _cmpFmtDT(today, 2, 0),
                toB: _cmpFmtDT(today, 6, 0)
            };
        default:
            return null;
    }
}

/* datetime-local value ("YYYY-MM-DDTHH:MM") in the browser's local time */
function _cmpFmtDT(date, hours, minutes) {
    var d = new Date(date);
    if (hours !== undefined) d.setHours(hours);
    if (minutes !== undefined) d.setMinutes(minutes);
    function pad(n) { return String(n).padStart(2, '0'); }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
        'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

/* Local datetime-local value to a UTC timestamp for the API */
function _cmpToISO(dtLocal) {
    if (!dtLocal) return '';
    var d = new Date(dtLocal);
    if (isNaN(d.getTime())) return '';
    return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/* "Around a case": Period A is the week before the case, Period B the case window. */
function _cmpCaseDates() {
    var select = document.getElementById('comparison-case');
    var incident = _cmpCases.find(function(c) { return String(c.id) === (select && select.value); });
    if (!incident) return null;
    var start = new Date(String(incident.start_date).slice(0, 10) + 'T00:00');
    var end = incident.end_date ? new Date(String(incident.end_date).slice(0, 10) + 'T23:59') : new Date();
    if (isNaN(start.getTime()) || isNaN(end.getTime())) return null;
    if (end > new Date()) end = new Date();
    return {
        fromA: _cmpFmtDT(new Date(start.getTime() - 7 * 86400000)),
        toA: _cmpFmtDT(start),
        fromB: _cmpFmtDT(start),
        toB: _cmpFmtDT(end)
    };
}

/* "Mon, 10/05, 00:00 – 23:59" in the UI language; the second date only when the day changes. */
function _cmpRangeText(from, to) {
    var a = new Date(from), b = new Date(to);
    if (isNaN(a.getTime()) || isNaN(b.getTime())) return '';
    var lang = document.documentElement.lang || undefined;
    var day = {weekday: 'short', month: '2-digit', day: '2-digit'};
    var time = {hour: '2-digit', minute: '2-digit'};
    var start = a.toLocaleDateString(lang, day) + ', ' + a.toLocaleTimeString(lang, time);
    var end = (a.toDateString() === b.toDateString() ? '' : b.toLocaleDateString(lang, day) + ', ') + b.toLocaleTimeString(lang, time);
    return start + ' \u2013 ' + end;
}

function _cmpUpdatePeriodText() {
    document.getElementById('comparison-period-a-text').textContent = _cmpRangeText(
        document.getElementById('comparison-from-a').value, document.getElementById('comparison-to-a').value);
    document.getElementById('comparison-period-b-text').textContent = _cmpRangeText(
        document.getElementById('comparison-from-b').value, document.getElementById('comparison-to-b').value);
}

/* ── UI Handlers ── */
/* Chips (and the select on phones) pick the comparison; only "Custom" shows the date fields. */
function _cmpSetPreset(preset) {
    _cmpPreset = preset;
    syncSegments('comparison-preset-tabs', function(b) { return b.dataset.value === preset; });
    document.getElementById('comparison-preset').value = preset;
    document.getElementById('comparison-custom').hidden = preset !== 'custom';
    document.getElementById('comparison-periods').hidden = preset === 'custom';
    document.getElementById('comparison-case-row').hidden = preset !== 'case';
}

function _cmpApplyPreset() {
    var dates = _cmpPreset === 'case' ? _cmpCaseDates() : _cmpPresetDates(_cmpPreset);
    if (!dates) return false;
    document.getElementById('comparison-from-a').value = dates.fromA;
    document.getElementById('comparison-to-a').value = dates.toA;
    document.getElementById('comparison-from-b').value = dates.fromB;
    document.getElementById('comparison-to-b').value = dates.toB;
    _cmpUpdatePeriodText();
    return true;
}

function _cmpChoosePreset(preset) {
    _cmpSetPreset(preset);
    docsightWriteViewState('comparison', {preset: _CMP_LINKABLE_PRESETS.indexOf(preset) !== -1 ? preset : ''});
    // Custom keeps the current times to edit; every other choice compares right away.
    if (preset !== 'custom' && _cmpApplyPreset()) _cmpRunComparison();
}

function comparisonPresetSelected() {
    _cmpChoosePreset(getPillValue('comparison-preset-tabs') || 'yesterday_today');
}
window.comparisonPresetSelected = comparisonPresetSelected;

function _cmpOnDateChange() {
    _cmpSetPreset('custom');
}

function _cmpAdjustTimes() {
    _cmpChoosePreset('custom');
    document.getElementById('comparison-from-a').focus();
}

/* Cases with a start date, open ones first, for the "Around a case" chip. */
function _cmpLoadCases() {
    return fetch(docsightUrl('/api/incidents'))
        .then(function(r) { return r.ok ? r.json() : []; })
        .then(function(data) {
            var list = Array.isArray(data) ? data : (data && data.incidents) || [];
            _cmpCases = list.filter(function(c) { return c.start_date; }).sort(function(a, b) {
                var open = (a.status === 'open' ? 0 : 1) - (b.status === 'open' ? 0 : 1);
                return open || String(b.start_date).localeCompare(String(a.start_date));
            });
            var select = document.getElementById('comparison-case');
            select.textContent = '';
            _cmpCases.forEach(function(c) {
                var option = document.createElement('option');
                var start = formatDocsightTime(c.start_date, 'date');
                var end = c.end_date ? formatDocsightTime(c.end_date, 'date') : (T.incident_duration_ongoing || 'ongoing');
                option.value = String(c.id);
                option.textContent = c.name + ' \u00b7 ' + start + ' \u2013 ' + end;
                select.appendChild(option);
            });
            var hasCases = _cmpCases.length > 0;
            document.querySelector('#comparison-preset-tabs [data-value="case"]').hidden = !hasCases;
            var option = document.querySelector('#comparison-preset option[value="case"]');
            option.hidden = !hasCases;
            option.disabled = !hasCases;
        })
        .catch(function() { _cmpCases = []; });
}

function _cmpRunComparison() {
    var fromA = document.getElementById('comparison-from-a').value;
    var toA = document.getElementById('comparison-to-a').value;
    var fromB = document.getElementById('comparison-from-b').value;
    var toB = document.getElementById('comparison-to-b').value;

    if (!fromA || !toA || !fromB || !toB) return;

    var placeholder = document.getElementById('comparison-placeholder');
    DOCSightEmptyState.hide(placeholder);
    document.getElementById('comparison-charts').hidden = true;
    document.getElementById('comparison-delta').hidden = true;
    document.getElementById('comparison-loading').hidden = false;

    var url = docsightUrl('/api/comparison?from_a=' + encodeURIComponent(_cmpToISO(fromA)) +
        '&to_a=' + encodeURIComponent(_cmpToISO(toA)) +
        '&from_b=' + encodeURIComponent(_cmpToISO(fromB)) +
        '&to_b=' + encodeURIComponent(_cmpToISO(toB)));

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('comparison-loading').hidden = true;
            if (data.error) {
                DOCSightEmptyState.showError(placeholder, {text: data.error, retry: _cmpRunComparison});
                document.getElementById('comparison-health').hidden = true;
                _cmpLastResult = null;
                window.__docsightComparisonResult = null;
                return;
            }
            _cmpLastResult = data;
            window.__docsightComparisonResult = data;
            _cmpRenderCharts(data);
            _cmpRenderHealthDistribution(data);
            _cmpRenderDeltaTable(data);
        })
        .catch(function(err) {
            document.getElementById('comparison-loading').hidden = true;
            DOCSightEmptyState.showError(placeholder, {retry: _cmpRunComparison});
            document.getElementById('comparison-health').hidden = true;
            _cmpLastResult = null;
            window.__docsightComparisonResult = null;
        });
}

/* ── Time Normalization ── */
function _cmpNormalize(timeseries, periodStart) {
    var startMs = new Date(periodStart).getTime();
    return timeseries.map(function(pt) {
        var ms = new Date(pt.timestamp).getTime();
        var hours = (ms - startMs) / 3600000;
        return { hours: Math.round(hours * 10) / 10, pt: pt };
    });
}

function _cmpMergeHourLabels(normA, normB) {
    var set = {};
    normA.forEach(function(n) { set[n.hours] = true; });
    normB.forEach(function(n) { set[n.hours] = true; });
    var hours = Object.keys(set).map(Number).sort(function(a, b) { return a - b; });
    return hours;
}

function _cmpMapToLabels(normalized, hourLabels) {
    var map = {};
    normalized.forEach(function(n) { map[n.hours] = n.pt; });
    return hourLabels.map(function(h) { return map[h] || null; });
}

function _cmpBuildTimeLabels(hourLabels, period) {
    var periodStartMs = new Date(period.from).getTime();
    var periodEndMs = new Date(period.to).getTime();
    var rangeSeconds = Math.max(Math.round((periodEndMs - periodStartMs) / 1000), 0);
    // Before/after charts align both periods by relative offset. Axis text uses
    // Period B's timeline as the visible time anchor so labels stay absolute.
    return hourLabels.map(function(h) {
        return docsightFormatXAxisLabel(periodStartMs + (h * 3600000), String(rangeSeconds) + 's');
    });
}

/* ── Chart Rendering ── */
function _cmpPeriodSupportsDocsisErrors(period) {
    if (!period) return false;
    if (period.uncorr_errors_supported === true) return true;
    return period.total && period.total.uncorr_errors != null || !!(period.timeseries && period.timeseries.some(function(pt) {
        return pt && pt.uncorr_errors != null;
    }));
}

function _cmpSetErrorsChartVisible(visible) {
    var card = document.getElementById('comparison-errors-card');
    if (card) card.style.display = visible ? '' : 'none';
    if (!visible && charts['cmp-chart-errors']) {
        charts['cmp-chart-errors'].destroy();
        delete charts['cmp-chart-errors'];
    }
}

function _cmpRenderCharts(data) {
    var pa = data.period_a;
    var pb = data.period_b;
    var labelA = T['docsight.comparison.period_a'] || T.period_a || 'Period A';
    var labelB = T['docsight.comparison.period_b'] || T.period_b || 'Period B';

    var normA = _cmpNormalize(pa.timeseries, pa.from);
    var normB = _cmpNormalize(pb.timeseries, pb.from);
    var hourLabels = _cmpMergeHourLabels(normA, normB);
    var mappedA = _cmpMapToLabels(normA, hourLabels);
    var mappedB = _cmpMapToLabels(normB, hourLabels);

    var xLabels = _cmpBuildTimeLabels(hourLabels, pb);

    if (pa.timeseries.length === 0 && pb.timeseries.length === 0) {
        DOCSightEmptyState.show(document.getElementById('comparison-placeholder'), {
            icon: 'clock',
            title: T['docsight.comparison.no_data_period'] || 'No data in selected period',
            text: T['docsight.comparison.empty_no_data_text'],
            action: {
                label: T['docsight.comparison.empty_no_data_action'] || 'Choose other periods',
                onClick: _cmpAdjustTimes
            },
            glossary: 'before_after_comparison'
        });
        return;
    }

    document.getElementById('comparison-charts').hidden = false;

    function extract(mapped, key) {
        return mapped.map(function(pt) { return pt ? pt[key] : null; });
    }

    renderChart('cmp-chart-ds-power', xLabels, [
        {label: labelA, data: extract(mappedA, 'ds_power_avg'), color: '#2196f3', spanGaps: true},
        {label: labelB, data: extract(mappedB, 'ds_power_avg'), color: '#ff9800', spanGaps: true}
    ], null, DS_POWER_THRESHOLDS);

    renderChart('cmp-chart-ds-snr', xLabels, [
        {label: labelA, data: extract(mappedA, 'ds_snr_avg'), color: '#2196f3', spanGaps: true},
        {label: labelB, data: extract(mappedB, 'ds_snr_avg'), color: '#ff9800', spanGaps: true}
    ], null, DS_SNR_THRESHOLDS);

    renderChart('cmp-chart-us-power', xLabels, [
        {label: labelA, data: extract(mappedA, 'us_power_avg'), color: '#2196f3', spanGaps: true},
        {label: labelB, data: extract(mappedB, 'us_power_avg'), color: '#ff9800', spanGaps: true}
    ], null, US_POWER_THRESHOLDS);

    var showErrors = _cmpPeriodSupportsDocsisErrors(pa) || _cmpPeriodSupportsDocsisErrors(pb);
    _cmpSetErrorsChartVisible(showErrors);
    if (showErrors) {
        renderChart('cmp-chart-errors', xLabels, [
            {label: labelA, data: extract(mappedA, 'uncorr_errors'), color: '#2196f3'},
            {label: labelB, data: extract(mappedB, 'uncorr_errors'), color: '#ff9800'}
        ], 'bar');
    }
}

/* ── Delta Table ── */
function _cmpRenderDeltaTable(data) {
    var pa = data.period_a;
    var pb = data.period_b;
    var delta = data.delta;

    var tbody = document.getElementById('comparison-delta-body');
    /* Clear existing rows */
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

    _cmpAppendDeltaRow(tbody, T['docsight.comparison.ds_power'] || 'DS Power',
        pa.avg.ds_power, pb.avg.ds_power, 'dBmV', delta.ds_power, false, false);
    _cmpAppendDeltaRow(tbody, T['docsight.comparison.ds_snr'] || 'DS SNR',
        pa.avg.ds_snr, pb.avg.ds_snr, 'dB', delta.ds_snr, true, false);
    _cmpAppendDeltaRow(tbody, T['docsight.comparison.us_power'] || 'US Power',
        pa.avg.us_power, pb.avg.us_power, 'dBmV', delta.us_power, false, false);
    if (_cmpPeriodSupportsDocsisErrors(pa) || _cmpPeriodSupportsDocsisErrors(pb)) {
        _cmpAppendDeltaRow(tbody, T['docsight.comparison.uncorr_errors'] || 'Uncorr. Errors',
            pa.total.uncorr_errors, pb.total.uncorr_errors, '', delta.uncorr_errors, false, true);
    }

    /* Health verdict row */
    var healthA = _cmpTopHealth(pa.health_distribution);
    var healthB = _cmpTopHealth(pb.health_distribution);
    var verdictLabel = T['docsight.comparison.' + delta.verdict] || delta.verdict;
    var verdictClass = delta.verdict === 'improved' ? 'cmp-good' :
                       delta.verdict === 'degraded' ? 'cmp-bad' : '';
    var tr = document.createElement('tr');
    _cmpAddCell(tr, T['docsight.comparison.health'] || 'Health');
    _cmpAddCell(tr, healthA);
    _cmpAddCell(tr, healthB);
    _cmpAddCell(tr, verdictLabel, verdictClass);
    tbody.appendChild(tr);
    labelDataTable(document.getElementById('comparison-delta-table'));

    document.getElementById('comparison-delta').hidden = false;
}

function _cmpRenderHealthDistribution(data) {
    _cmpRenderHealthCard(
        document.getElementById('comparison-health-range-a'),
        document.getElementById('comparison-health-bars-a'),
        data.period_a
    );
    _cmpRenderHealthCard(
        document.getElementById('comparison-health-range-b'),
        document.getElementById('comparison-health-bars-b'),
        data.period_b
    );
    document.getElementById('comparison-health').hidden = false;
}

function _cmpRenderHealthCard(rangeEl, container, period) {
    rangeEl.textContent = _cmpFormatRange(period.from, period.to);
    while (container.firstChild) container.removeChild(container.firstChild);

    [
        ['good', _cmpHealthLabel('good')],
        ['tolerated', _cmpHealthLabel('tolerated')],
        ['marginal', _cmpHealthLabel('marginal')],
        ['critical', _cmpHealthLabel('critical')],
        ['unknown', _cmpHealthLabel('unknown')]
    ].forEach(function(entry) {
        var key = entry[0];
        var label = entry[1];
        container.appendChild(_cmpCreateHealthRow(label, key, period.health_distribution || {}, period.snapshots || 0));
    });
}

function _cmpCreateHealthRow(label, key, dist, total) {
    var count = dist[key] || 0;
    var pct = total ? Math.round((count / total) * 100) : 0;
    var row = document.createElement('div');
    row.className = 'comparison-health-row';

    var labelEl = document.createElement('div');
    labelEl.className = 'comparison-health-label';
    labelEl.textContent = label;
    row.appendChild(labelEl);

    var track = document.createElement('div');
    track.className = 'comparison-health-track';
    var fill = document.createElement('div');
    fill.className = 'comparison-health-fill health-' + key;
    fill.style.width = pct + '%';
    track.appendChild(fill);
    row.appendChild(track);

    var valueEl = document.createElement('div');
    valueEl.className = 'comparison-health-value';
    valueEl.textContent = count + ' (' + pct + '%)';
    row.appendChild(valueEl);

    return row;
}

function _cmpHealthLabel(key) {
    var map = {
        good: T.health_good || 'Good',
        tolerated: T.health_tolerated || 'Tolerated',
        marginal: T.health_marginal || 'Marginal',
        critical: T.health_critical || 'Critical',
        unknown: T['docsight.comparison.health_unknown'] || 'Unknown'
    };
    return map[key] || key;
}

function _cmpFormatRange(fromTs, toTs) {
    return _cmpShortDate(fromTs) + ' - ' + _cmpShortDate(toTs);
}

function _cmpShortDate(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    var month = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    var hours = String(d.getHours()).padStart(2, '0');
    var minutes = String(d.getMinutes()).padStart(2, '0');
    return d.getFullYear() + '-' + month + '-' + day + ' ' + hours + ':' + minutes;
}

function _cmpAppendDeltaRow(tbody, label, aVal, bVal, unit, delta, higherIsBetter, isInt) {
    var aStr = aVal != null ? (isInt ? String(aVal) : aVal.toFixed(1)) + (unit ? ' ' + unit : '') : '-';
    var bStr = bVal != null ? (isInt ? String(bVal) : bVal.toFixed(1)) + (unit ? ' ' + unit : '') : '-';

    var deltaStr = '-';
    var cls = '';
    if (delta != null) {
        var sign = delta > 0 ? '+' : '';
        deltaStr = sign + (isInt ? String(delta) : delta.toFixed(1)) + (unit ? ' ' + unit : '');
        if (Math.abs(delta) > 0.5) {
            if (higherIsBetter) {
                cls = delta > 0 ? 'cmp-good' : 'cmp-bad';
            } else if (isInt) {
                /* Error counts: more = bad */
                cls = delta > 0 ? 'cmp-bad' : 'cmp-good';
            }
        }
    }

    var tr = document.createElement('tr');
    _cmpAddCell(tr, label);
    _cmpAddCell(tr, aStr);
    _cmpAddCell(tr, bStr);
    _cmpAddCell(tr, deltaStr, cls);
    tbody.appendChild(tr);
}

function _cmpAddCell(tr, text, className) {
    var td = document.createElement('td');
    td.textContent = text;
    if (className) td.className = className;
    tr.appendChild(td);
}

function _cmpTopHealth(dist) {
    if (!dist || Object.keys(dist).length === 0) return '-';
    var total = 0;
    var best = '';
    var bestCount = 0;
    for (var k in dist) {
        total += dist[k];
        if (dist[k] > bestCount) { bestCount = dist[k]; best = k; }
    }
    var pct = Math.round(bestCount / total * 100);
    return _cmpHealthLabel(best) + ' (' + pct + '%)';
}

/* ── Init ── */
function initComparison() {
    if (!_cmpInitialized) {
        _cmpInitialized = true;

        ['comparison-from-a', 'comparison-to-a', 'comparison-from-b', 'comparison-to-b'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) {
                el.type = 'datetime-local';
                el.removeAttribute('readonly');
                el.addEventListener('change', _cmpOnDateChange);
            }
        });

        document.getElementById('comparison-preset').addEventListener('change', function(event) {
            _cmpChoosePreset(event.target.value);
        });
        document.getElementById('comparison-case').addEventListener('change', function() {
            if (_cmpApplyPreset()) _cmpRunComparison();
        });
        document.getElementById('comparison-adjust-btn').addEventListener('click', _cmpAdjustTimes);
        document.getElementById('comparison-run-btn').addEventListener('click', function() {
            _cmpUpdatePeriodText();
            _cmpRunComparison();
        });
        _cmpLoadCases();
    }

    /* "#comparison?preset=last_this_week" opens that comparison; otherwise the last one. */
    var linked = docsightReadViewState('comparison').preset;
    if (_CMP_LINKABLE_PRESETS.indexOf(linked) !== -1) _cmpPreset = linked;
    _cmpSetPreset(_cmpPreset);
    if (_cmpPreset !== 'custom') _cmpApplyPreset();
    _cmpRunComparison();
}

function openComparisonInComplaint() {
    if (!_cmpLastResult) return;
    if (typeof openReportModal === 'function') openReportModal();
    var toggle = document.getElementById('report-include-comparison');
    if (toggle) toggle.checked = true;
}

window.openComparisonInComplaint = openComparisonInComplaint;
window.initComparison = initComparison;
