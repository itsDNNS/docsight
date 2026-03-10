/* -- Before/After Comparison Module -- */

var _cmpInitialized = false;
var _cmpLastResult = null;

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

function _cmpFmtDT(date, hours, minutes) {
    var d = new Date(date);
    if (hours !== undefined) d.setHours(hours);
    if (minutes !== undefined) d.setMinutes(minutes);
    d.setSeconds(0);
    d.setMilliseconds(0);
    return d.toISOString().replace('Z', '').slice(0, 16);
}

function _cmpToISO(dtLocal) {
    if (!dtLocal) return '';
    /* datetime-local gives "YYYY-MM-DDTHH:MM", append seconds + Z */
    return dtLocal + ':00Z';
}

/* ── UI Handlers ── */
function _cmpApplyPreset() {
    var preset = document.getElementById('comparison-preset').value;
    var dates = _cmpPresetDates(preset);
    if (!dates) return;
    document.getElementById('comparison-from-a').value = dates.fromA;
    document.getElementById('comparison-to-a').value = dates.toA;
    document.getElementById('comparison-from-b').value = dates.fromB;
    document.getElementById('comparison-to-b').value = dates.toB;
}

function _cmpOnDateChange() {
    document.getElementById('comparison-preset').value = 'custom';
}

function _cmpRunComparison() {
    var fromA = document.getElementById('comparison-from-a').value;
    var toA = document.getElementById('comparison-to-a').value;
    var fromB = document.getElementById('comparison-from-b').value;
    var toB = document.getElementById('comparison-to-b').value;

    if (!fromA || !toA || !fromB || !toB) return;

    var placeholder = document.getElementById('comparison-placeholder');
    placeholder.style.display = 'none';
    document.getElementById('comparison-charts').style.display = 'none';
    document.getElementById('comparison-delta').style.display = 'none';
    document.getElementById('comparison-loading').style.display = 'block';

    var url = '/api/comparison?from_a=' + encodeURIComponent(_cmpToISO(fromA)) +
              '&to_a=' + encodeURIComponent(_cmpToISO(toA)) +
              '&from_b=' + encodeURIComponent(_cmpToISO(fromB)) +
              '&to_b=' + encodeURIComponent(_cmpToISO(toB));

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('comparison-loading').style.display = 'none';
            if (data.error) {
                placeholder.style.display = 'block';
                placeholder.textContent = data.error;
                document.getElementById('comparison-health').style.display = 'none';
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
            document.getElementById('comparison-loading').style.display = 'none';
            placeholder.style.display = 'block';
            placeholder.textContent = err.message;
            document.getElementById('comparison-health').style.display = 'none';
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

/* ── Chart Rendering ── */
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

    var hrsLabel = 'h';
    var xLabels = hourLabels.map(function(h) { return h + hrsLabel; });

    if (pa.timeseries.length === 0 && pb.timeseries.length === 0) {
        var placeholder = document.getElementById('comparison-placeholder');
        placeholder.style.display = 'block';
        placeholder.textContent = T['docsight.comparison.no_data_period'] || 'No data in selected period';
        return;
    }

    document.getElementById('comparison-charts').style.display = '';

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

    renderChart('cmp-chart-errors', xLabels, [
        {label: labelA, data: extract(mappedA, 'uncorr_errors'), color: '#2196f3'},
        {label: labelB, data: extract(mappedB, 'uncorr_errors'), color: '#ff9800'}
    ], 'bar');
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
    _cmpAppendDeltaRow(tbody, T['docsight.comparison.uncorr_errors'] || 'Uncorr. Errors',
        pa.total.uncorr_errors, pb.total.uncorr_errors, '', delta.uncorr_errors, false, true);

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

    document.getElementById('comparison-delta').style.display = '';
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
    document.getElementById('comparison-health').style.display = '';
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
        unknown: T.unknown || 'Unknown'
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
    return best.charAt(0).toUpperCase() + best.slice(1) + ' (' + pct + '%)';
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

        document.getElementById('comparison-preset').addEventListener('change', _cmpApplyPreset);
        document.getElementById('comparison-run-btn').addEventListener('click', _cmpRunComparison);
    }

    /* Apply default preset on each view */
    _cmpApplyPreset();
}

function openComparisonInComplaint() {
    if (!_cmpLastResult) return;
    if (typeof openReportModal === 'function') openReportModal();
    var toggle = document.getElementById('report-include-comparison');
    if (toggle) toggle.checked = true;
}

window.openComparisonInComplaint = openComparisonInComplaint;
window.initComparison = initComparison;
