/* ── Trend Charts ── */
/* Extracted from IIFE – depends on: T, charts, renderChart, currentView,
   todayStr, formatDateDE, DS_POWER_THRESHOLDS, DS_SNR_THRESHOLDS,
   US_POWER_THRESHOLDS, _tempOverlayVisible (chart-engine.js) */

var _trendRange = '1d';
var _lastTrendData = null;
var _lastTrendWeather = null;
var _lastTrendRange = '1d';
var POWER_TREND_FILL = 'rgba(168,85,247,0.15)';

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
    document.querySelectorAll('#trend-tabs .trend-tab').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-range') === _trendRange);
    });
}
document.querySelectorAll('#trend-tabs .trend-tab').forEach(function(btn) {
    btn.addEventListener('click', function() {
        _trendRange = this.getAttribute('data-range');
        updateTrendTabs();
        loadTrends(_trendRange);
    });
});

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
            var tTs = new Date(trendData[i].timestamp).getTime();
            var best = null, bestDist = Infinity;
            for (var j = 0; j < weatherData.length; j++) {
                var wTs = new Date(weatherData[j].timestamp).getTime();
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

function _setTrendErrorsVisible(visible) {
    var card = document.getElementById('trend-errors-card');
    if (card) card.style.display = visible ? '' : 'none';
    if (!visible && charts['chart-errors']) {
        charts['chart-errors'].destroy();
        delete charts['chart-errors'];
    }
}

function _renderTrendCharts() {
    var data = _lastTrendData;
    var range = _lastTrendRange;
    if (!data || data.length === 0) return;
    var xLabels = data.map(function(d) {
        if (!d.timestamp) return '';
        if (_trendRangeHours(range) <= 24) return d.timestamp.substring(11, 16);
        if (_trendRangeHours(range) < 24 * 30) return d.timestamp.substring(5, 16).replace('T', ' ');
        return d.date ? formatDateDE(d.date) : formatDateDE(d.timestamp.substring(0, 10));
    });
    var tempOpts = (_lastTrendWeather && _lastTrendWeather.length > 0) ? { tempData: _lastTrendWeather } : null;
    renderChart('chart-ds-power', xLabels,
        [{label: 'DS Power Avg', data: data.map(function(d){ return d.ds_power_avg; }), color: '#a855f7', fill: POWER_TREND_FILL, fillTo: fillToScaleMin}],
        null, DS_POWER_THRESHOLDS, tempOpts);
    renderChart('chart-ds-snr', xLabels,
        [{label: 'DS SNR Avg', data: data.map(function(d){ return d.ds_snr_avg; }), color: '#a855f7', fill: POWER_TREND_FILL, fillTo: fillToScaleMin}],
        null, DS_SNR_THRESHOLDS, tempOpts);
    renderChart('chart-us-power', xLabels,
        [{label: 'US Power Avg', data: data.map(function(d){ return d.us_power_avg; }), color: '#a855f7', fill: POWER_TREND_FILL, fillTo: fillToScaleMin}],
        null, US_POWER_THRESHOLDS, tempOpts);
    var showErrors = _hasTrendDocsisErrorSeries(data);
    _setTrendErrorsVisible(showErrors);
    if (showErrors) {
        renderChart('chart-errors', xLabels, [
            {label: T.correctable, data: data.map(function(d){ return d.ds_correctable_errors; }), color: '#2196f3'},
            {label: T.uncorrectable, data: data.map(function(d){ return d.ds_uncorrectable_errors; }), color: '#f44336'}
        ], 'bar');
    }
}

function loadTrends(range) {
    var title = document.getElementById('trend-title');
    var noData = document.getElementById('trend-no-data');
    var grid = document.getElementById('charts-grid');
    var label = String(range || '1d');
    title.textContent = (T.signal_trends || 'Signal Trends') + ' (' + label + ')';
    _lastTrendRange = range;

    var wr = _getWeatherRange(range);
    var trendsUrl = '/api/trends?range=' + encodeURIComponent(range || '1d');
    var weatherUrl = '/api/weather/range?start=' + encodeURIComponent(wr.start) + '&end=' + encodeURIComponent(wr.end);

    Promise.all([
        fetch(trendsUrl).then(function(r) { return r.json(); }),
        fetch(weatherUrl).then(function(r) { return r.json(); }).catch(function() { return []; })
    ]).then(function(results) {
            var data = results[0];
            var weatherData = results[1];
            if (!data || data.length === 0) {
                noData.textContent = T.no_data;
                noData.style.display = 'block';
                grid.style.display = 'none';
                _lastTrendData = null;
                _lastTrendWeather = null;
                _updateTempToggle();
                return;
            }
            noData.style.display = 'none';
            grid.style.display = '';
            _lastTrendData = data;
            _lastTrendWeather = _alignWeatherToTrends(data, weatherData, range);
            _updateTempToggle();
            _renderTrendCharts();
        })
        .catch(function() {
            noData.textContent = T.trend_error;
            noData.style.display = 'block';
            grid.style.display = 'none';
        });
}

function _updateTempToggle() {
    var btn = document.getElementById('temp-toggle-btn');
    if (!btn) return;
    var hasWeather = _lastTrendWeather && _lastTrendWeather.some(function(v) { return v !== null; });
    btn.style.display = hasWeather ? '' : 'none';
    btn.classList.toggle('active', _tempOverlayVisible && hasWeather);
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

/* Close chart zoom on Escape */
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.getElementById('chart-zoom-overlay').classList.contains('open')) {
        closeChartZoom();
        return;
    }
});
