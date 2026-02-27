/* ── Trend Charts ── */
/* Extracted from IIFE – depends on: T, charts, renderChart, currentView,
   todayStr, formatDateDE, DS_POWER_THRESHOLDS, DS_SNR_THRESHOLDS,
   US_POWER_THRESHOLDS, _tempOverlayVisible (chart-engine.js) */

var _trendRange = 'day';
var _lastTrendData = null;
var _lastTrendWeather = null;
var _lastTrendRange = 'day';

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

function _getWeatherRange(range, date) {
    var d = new Date(date + 'T00:00:00');
    var end = date + ' 23:59:59Z';
    var start;
    if (range === 'day') {
        start = date + ' 00:00:00Z';
    } else if (range === 'week') {
        var s = new Date(d.getTime() - 6 * 86400000);
        start = s.toISOString().substring(0, 10) + ' 00:00:00Z';
    } else {
        var s = new Date(d.getTime() - 29 * 86400000);
        start = s.toISOString().substring(0, 10) + ' 00:00:00Z';
    }
    return { start: start, end: end };
}

function _alignWeatherToTrends(trendData, weatherData, range) {
    if (!weatherData || weatherData.length === 0) return null;
    var temps = [];
    if (range === 'day') {
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

function _renderTrendCharts() {
    var data = _lastTrendData;
    var range = _lastTrendRange;
    if (!data || data.length === 0) return;
    var xLabels = data.map(function(d) {
        if (!d.timestamp) return '';
        if (range === 'day') return d.timestamp.substring(11, 16);
        if (range === 'week') return d.timestamp.substring(5, 16).replace('T', ' ');
        return d.date ? formatDateDE(d.date) : formatDateDE(d.timestamp.substring(0, 10));
    });
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
    renderChart('chart-errors', xLabels, [
        {label: T.correctable, data: data.map(function(d){ return d.ds_correctable_errors; }), color: '#2196f3'},
        {label: T.uncorrectable, data: data.map(function(d){ return d.ds_uncorrectable_errors; }), color: '#f44336'}
    ], 'bar');
}

function loadTrends(range) {
    var date = todayStr();
    var title = document.getElementById('trend-title');
    var noData = document.getElementById('trend-no-data');
    var grid = document.getElementById('charts-grid');
    var labels = {day: T.day_trend, week: T.week_trend, month: T.month_trend};
    title.textContent = (labels[range] || 'Trend') + ' - ' + formatDateDE(date);
    _lastTrendRange = range;

    var wr = _getWeatherRange(range, date);
    var trendsUrl = '/api/trends?range=' + range + '&date=' + date;
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
