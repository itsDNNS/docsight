/* ── Trend Charts ── */
/* Extracted from IIFE – depends on: T, charts, renderChart, currentView,
   todayStr, docsightFormatXAxisLabels, DS_POWER_THRESHOLDS, DS_SNR_THRESHOLDS,
   US_POWER_THRESHOLDS, _tempOverlayVisible and its helpers (chart-engine.js) */

var _trendRange = '1d';
var _lastTrendData = null;
var _lastTrendRows = null;
var _lastTrendWeather = null;
var _lastTrendRange = '1d';
var _trendLoadSeq = 0;

/* ── Trend Tabs ── */
function updateTrendTabs() {
    syncSegments('trend-tabs', function(btn) { return btn.getAttribute('data-range') === _trendRange; });
}

// The window ends now unless the arrows (or a swipe) moved it into the past.
var _trendWindow = DOCSightWindowShift.create('trend', {
    hours: function() { return docsightRangeHours(_trendRange); },
    onChange: function() {
        _writeTrendsViewState();
        loadTrends(_trendRange);
    },
    swipeArea: document.getElementById('charts-grid')
});

function _writeTrendsViewState() {
    docsightWriteViewState('trends', {range: _trendRange, end: _trendWindow.param()});
}

document.querySelectorAll('#trend-tabs .segmented-option').forEach(function(btn) {
    btn.addEventListener('click', function() {
        _trendRange = this.getAttribute('data-range');
        _writeTrendsViewState();
        updateTrendTabs();
        _trendWindow.sync();
        loadTrends(_trendRange);
    });
});

function applyTrendsViewState() {
    var state = docsightReadViewState('trends');
    if (docsightSelectSegment('trend-tabs', 'data-range', state.range)) _trendRange = state.range;
    _trendWindow.restore(state.end);
}

function _getWeatherRange(range) {
    var param = _trendWindow.param();
    var hours = docsightRangeHours(range);
    // The nearest reading of a point at the window edge can lie just outside the window.
    var margin = hours < TEMP_DAILY_FROM_HOURS ? TEMP_MATCH_MS : 0;
    var endDt = new Date((param ? DOCSightWindowShift.fromParam(param) : Date.now()) + margin);
    var startDt = new Date(endDt.getTime() - hours * 3600000 - 2 * margin);
    var end = endDt.toISOString().substring(0, 19) + 'Z';
    var start = startDt.toISOString().substring(0, 19) + 'Z';
    return { start: start, end: end };
}

function _supportsTrendDocsisErrors(row) {
    if (!row) return false;
    if (row.errors_supported === false) return false;
    return row.errors_supported === true || row.ds_correctable_errors != null || row.ds_uncorrectable_errors != null;
}

function _hasTrendDocsisErrorSeries(data) {
    return !!(data && data.some(_supportsTrendDocsisErrors));
}

function _isDocsisTrendRow(row) {
    return !!(row && (
        row.ds_power_avg != null ||
        row.us_power_avg != null ||
        row.ds_snr_avg != null ||
        row.ds_correctable_errors != null ||
        row.ds_uncorrectable_errors != null
    ));
}

function _setTrendErrorsTitle(minutes) {
    var title = document.getElementById('trend-errors-title');
    if (title) title.textContent = docsightErrorsTitle(minutes);
}

function _renderTrendCharts() {
    var data = _lastTrendData;
    var range = _lastTrendRange;
    if (!data || data.length === 0) return;
    var timestamps = data.map(function(d) { return d.timestamp || ''; });
    var xLabels = docsightFormatXAxisLabels(timestamps, range);
    // Points by time, so a pause in the polls shows as a gap.
    var times = docsightTimesFromStamps(timestamps);
    var chartOpts = function(canvasId, titleId) {
        var opts = Object.assign({times: times}, tempOpts || {});
        // Clicking a point opens the snapshot taken at that time.
        opts.onPointClick = function(idx) {
            _openTrendSnapshot(canvasId, idx, timestamps[idx], titleId);
        };
        return opts;
    };
    var tempOpts = (_lastTrendWeather && _lastTrendWeather.length > 0) ? { tempData: _lastTrendWeather } : null;
    renderChart('chart-ds-power', xLabels,
        [{label: 'DS Power Avg', data: data.map(function(d){ return d.ds_power_avg; }), color: '#a855f7'}],
        null, DS_POWER_THRESHOLDS, chartOpts('chart-ds-power', 'chart-ds-power'));
    renderChart('chart-ds-snr', xLabels,
        [{label: 'DS SNR Avg', data: data.map(function(d){ return d.ds_snr_avg; }), color: '#a855f7'}],
        null, DS_SNR_THRESHOLDS, chartOpts('chart-ds-snr', 'chart-ds-snr'));
    renderChart('chart-us-power', xLabels,
        [{label: 'US Power Avg', data: data.map(function(d){ return d.us_power_avg; }), color: '#a855f7'}],
        null, US_POWER_THRESHOLDS, chartOpts('chart-us-power', 'chart-us-power'));
    var showErrors = _hasTrendDocsisErrorSeries(data);
    _setChartCardVisible('trend-errors-card', 'chart-errors', showErrors);
    if (showErrors) {
        // New uncorrectable errors per interval; the cumulative counter hides when they happened.
        // All rows, since a poll without any reading still changes the channels behind the counter.
        var buckets = docsightErrorBuckets(_lastTrendRows, range);
        _setTrendErrorsTitle(docsightErrorBucketMinutes(range));
        var bucketMinutes = docsightErrorBucketMinutes(range);
        var bucketTimes = docsightTimesFromStamps(buckets.map(function(b) { return b.timestamp; }));
        renderChart('chart-errors', docsightFormatXAxisLabels(buckets.map(function(b) { return b.timestamp; }), range), [
            {label: T.uncorrectable, data: buckets.map(function(b) { return b.errors; }), color: docsightThemeColor('--crit', 0.8)}
        ], 'bar', null, {times: bucketTimes, gaps: docsightNullRunGaps(bucketTimes, buckets.map(function(b) { return b.errors; })), onPointClick: function(idx) {
            // A bar covers an interval; its last snapshot shows what the interval ended with.
            var end = new Date(Date.parse(buckets[idx].timestamp + 'Z') + (bucketMinutes * 60 - 1) * 1000).toISOString().slice(0, 19);
            _openTrendSnapshot('chart-errors', idx, end, 'trend-errors-title');
        }});
    }
}

function _openTrendSnapshot(canvasId, idx, time, titleId) {
    if (!time || typeof DOCSightSnapshotPanel === 'undefined') return;
    var title = document.getElementById(titleId);
    var card = title && title.closest ? title.closest('.chart-card') : null;
    var label = card ? card.querySelector('.chart-label') : null;
    DOCSightSnapshotPanel.open(time, {canvasId: canvasId, index: idx, source: label ? label.textContent.trim() : ''});
}

function loadTrends(range) {
    var title = document.getElementById('trend-title');
    var noData = document.getElementById('trend-no-data');
    var grid = document.getElementById('charts-grid');
    if (title) title.textContent = T.signal_trends;
    _lastTrendRange = range;
    // Quick steps or range clicks overlap; only the latest request may draw.
    var seq = ++_trendLoadSeq;

    var wr = _getWeatherRange(range);
    var end = _trendWindow.param();
    var trendsUrl = docsightUrl('/api/trends?range=' + encodeURIComponent(range || '1d') + (end ? '&end=' + encodeURIComponent(end) : ''));
    var weatherUrl = docsightUrl('/api/weather/range?start=' + encodeURIComponent(wr.start) + '&end=' + encodeURIComponent(wr.end));

    Promise.all([
        fetch(trendsUrl).then(function(r) { return r.json(); }),
        fetch(weatherUrl).then(function(r) { return r.json(); }).catch(function() { return []; })
    ]).then(function(results) {
            if (seq !== _trendLoadSeq) return;
            _lastTrendRows = results[0] || [];
            var data = _lastTrendRows.filter(_isDocsisTrendRow);
            var weatherData = results[1];
            if (!data || data.length === 0) {
                DOCSightEmptyState.showRange(noData, {tabs: 'trend-tabs', glossary: 'signal_trends'});
                grid.style.display = 'none';
                _lastTrendData = null;
                _lastTrendWeather = null;
                _updateTempToggleButton('temp-toggle-btn', null);
                return;
            }
            DOCSightEmptyState.hide(noData);
            grid.style.display = '';
            _lastTrendData = data;
            _lastTrendWeather = _alignWeatherToTimestamps(data.map(function(d) { return d.timestamp; }), weatherData, range);
            _updateTempToggleButton('temp-toggle-btn', _lastTrendWeather);
            _renderTrendCharts();
        })
        .catch(function() {
            if (seq !== _trendLoadSeq) return;
            DOCSightEmptyState.showError(noData, {retry: function() { loadTrends(range); }});
            grid.style.display = 'none';
        });
}

(function() {
    var btn = document.getElementById('temp-toggle-btn');
    if (btn) {
        btn.addEventListener('click', function() {
            _tempOverlayVisible = !_tempOverlayVisible;
            _updateTempToggleButton('temp-toggle-btn', _lastTrendWeather);
            _renderTrendCharts();
        });
    }
})();

/* Expand button click handlers */
document.querySelectorAll('.chart-expand-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        openChartZoom(btn.getAttribute('data-chart'));
    });
});
