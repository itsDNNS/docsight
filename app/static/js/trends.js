/* ── Trend Charts ── */
/* Extracted from IIFE – depends on: T, charts, renderChart, currentView,
   todayStr, docsightFormatXAxisLabels, DS_POWER_THRESHOLDS, DS_SNR_THRESHOLDS,
   US_POWER_THRESHOLDS, _tempOverlayVisible (chart-engine.js) */

var _trendRange = '1d';
var _lastTrendData = null;
var _lastTrendWeather = null;
var _lastTrendRange = '1d';

function _trendRangeHours(range) {
    var map = { day: 24, week: 168, month: 720 };
    if (map[range]) return map[range];
    var match = String(range || '1d').match(/^(\d+)(h|d)$/);
    if (!match) return 24;
    var value = parseInt(match[1], 10);
    return match[2] === 'h' ? value : value * 24;
}

/* ── Trend Tabs ── */
function updateTrendTabs() {
    syncSegments('trend-tabs', function(btn) { return btn.getAttribute('data-range') === _trendRange; });
}
document.querySelectorAll('#trend-tabs .segmented-option').forEach(function(btn) {
    btn.addEventListener('click', function() {
        _trendRange = this.getAttribute('data-range');
        docsightWriteViewState('trends', {range: _trendRange});
        updateTrendTabs();
        loadTrends(_trendRange);
    });
});

function applyTrendsViewState() {
    var range = docsightReadViewState('trends').range;
    if (docsightSelectSegment('trend-tabs', 'data-range', range)) _trendRange = range;
}

function _getWeatherRange(range) {
    var endDt = new Date();
    var startDt = new Date(endDt.getTime() - _trendRangeHours(range) * 3600000);
    var end = endDt.toISOString().substring(0, 19) + 'Z';
    var start = startDt.toISOString().substring(0, 19) + 'Z';
    return { start: start, end: end };
}

function _alignWeatherToTrends(trendData, weatherData, range) {
    if (!weatherData || weatherData.length === 0) return null;
    var temps = [];
    if (_trendRangeHours(range) <= 24) {
        for (var i = 0; i < trendData.length; i++) {
            if (!trendData[i].timestamp) { temps.push(null); continue; }
            var tTs = docsightParseTime(trendData[i].timestamp).getTime();
            var best = null, bestDist = Infinity;
            for (var j = 0; j < weatherData.length; j++) {
                var wTs = docsightParseTime(weatherData[j].timestamp).getTime();
                var dist = Math.abs(wTs - tTs);
                if (dist < bestDist) { bestDist = dist; best = weatherData[j].temperature; }
            }
            temps.push(bestDist <= 5400000 ? best : null);
        }
    } else {
        var dailyTemps = {};
        for (var j = 0; j < weatherData.length; j++) {
            var day = weatherData[j].timestamp.substring(0, 10);
            if (!dailyTemps[day]) dailyTemps[day] = [];
            dailyTemps[day].push(weatherData[j].temperature);
        }
        var dailyAvg = {};
        for (var day in dailyTemps) {
            var sum = 0;
            for (var k = 0; k < dailyTemps[day].length; k++) sum += dailyTemps[day][k];
            dailyAvg[day] = Math.round(sum / dailyTemps[day].length * 10) / 10;
        }
        for (var i = 0; i < trendData.length; i++) {
            var date = trendData[i].date || (trendData[i].timestamp ? trendData[i].timestamp.substring(0, 10) : '');
            temps.push(dailyAvg[date] !== undefined ? dailyAvg[date] : null);
        }
    }
    return temps;
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

function _setTrendErrorsVisible(visible) {
    var card = document.getElementById('trend-errors-card');
    if (card) card.style.display = visible ? '' : 'none';
    if (!visible && charts['chart-errors']) {
        charts['chart-errors'].destroy();
        delete charts['chart-errors'];
    }
}

function _setTrendErrorsTitle(minutes) {
    var title = document.getElementById('trend-errors-title');
    if (!title) return;
    var text;
    if (minutes >= 1440) text = T.trend_errors_per_day || 'Uncorrectable errors per day';
    else if (minutes === 60) text = T.trend_errors_per_hour || 'Uncorrectable errors per hour';
    else if (minutes > 60) text = (T.trend_errors_per_hours || 'Uncorrectable errors per {hours} hours').replace('{hours}', minutes / 60);
    else text = (T.trend_errors_per_minutes || 'Uncorrectable errors per {minutes} minutes').replace('{minutes}', minutes);
    title.textContent = text;
}

function _renderTrendCharts() {
    var data = _lastTrendData;
    var range = _lastTrendRange;
    if (!data || data.length === 0) return;
    var timestamps = data.map(function(d) { return d.timestamp || ''; });
    var xLabels = docsightFormatXAxisLabels(timestamps, range);
    var tempOpts = (_lastTrendWeather && _lastTrendWeather.length > 0) ? { tempData: _lastTrendWeather } : null;
    renderChart('chart-ds-power', xLabels,
        [{label: 'DS Power Avg', data: data.map(function(d){ return d.ds_power_avg; }), color: '#a855f7'}],
        null, DS_POWER_THRESHOLDS, tempOpts);
    renderChart('chart-ds-snr', xLabels,
        [{label: 'DS SNR Avg', data: data.map(function(d){ return d.ds_snr_avg; }), color: '#a855f7'}],
        null, DS_SNR_THRESHOLDS, tempOpts);
    renderChart('chart-us-power', xLabels,
        [{label: 'US Power Avg', data: data.map(function(d){ return d.us_power_avg; }), color: '#a855f7'}],
        null, US_POWER_THRESHOLDS, tempOpts);
    var showErrors = _hasTrendDocsisErrorSeries(data);
    _setTrendErrorsVisible(showErrors);
    if (showErrors) {
        // New uncorrectable errors per interval; the cumulative counter hides when they happened.
        var buckets = docsightErrorBuckets(data, range);
        _setTrendErrorsTitle(docsightErrorBucketMinutes(range));
        renderChart('chart-errors', docsightFormatXAxisLabels(buckets.map(function(b) { return b.timestamp; }), range), [
            {label: T.uncorrectable, data: buckets.map(function(b) { return b.errors; }), color: docsightThemeColor('--crit', 0.8)}
        ], 'bar');
    }
}

function loadTrends(range) {
    var title = document.getElementById('trend-title');
    var noData = document.getElementById('trend-no-data');
    var grid = document.getElementById('charts-grid');
    if (title) title.textContent = T.signal_trends || 'Signal Trends';
    _lastTrendRange = range;

    var wr = _getWeatherRange(range);
    var trendsUrl = docsightUrl('/api/trends?range=' + encodeURIComponent(range || '1d'));
    var weatherUrl = docsightUrl('/api/weather/range?start=' + encodeURIComponent(wr.start) + '&end=' + encodeURIComponent(wr.end));

    Promise.all([
        fetch(trendsUrl).then(function(r) { return r.json(); }),
        fetch(weatherUrl).then(function(r) { return r.json(); }).catch(function() { return []; })
    ]).then(function(results) {
            var data = (results[0] || []).filter(_isDocsisTrendRow);
            var weatherData = results[1];
            if (!data || data.length === 0) {
                DOCSightEmptyState.showRange(noData, {tabs: 'trend-tabs', glossary: 'signal_trends'});
                grid.style.display = 'none';
                _lastTrendData = null;
                _lastTrendWeather = null;
                _updateTempToggle();
                return;
            }
            DOCSightEmptyState.hide(noData);
            grid.style.display = '';
            _lastTrendData = data;
            _lastTrendWeather = _alignWeatherToTrends(data, weatherData, range);
            _updateTempToggle();
            _renderTrendCharts();
        })
        .catch(function() {
            DOCSightEmptyState.showError(noData, {retry: function() { loadTrends(range); }});
            grid.style.display = 'none';
        });
}

function _updateTempToggle() {
    var btn = document.getElementById('temp-toggle-btn');
    if (!btn) return;
    var hasWeather = _lastTrendWeather && _lastTrendWeather.some(function(v) { return v !== null; });
    btn.hidden = !hasWeather;
    btn.classList.toggle('active', _tempOverlayVisible && hasWeather);
    btn.setAttribute('aria-pressed', (_tempOverlayVisible && hasWeather) ? 'true' : 'false');
    btn.title = _tempOverlayVisible ? (T.temp_overlay_hide || 'Hide temperature overlay') : (T.temp_overlay_show || 'Show temperature overlay');
}

(function() {
    var btn = document.getElementById('temp-toggle-btn');
    if (btn) {
        btn.addEventListener('click', function() {
            _tempOverlayVisible = !_tempOverlayVisible;
            _updateTempToggle();
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
