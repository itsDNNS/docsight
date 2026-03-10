/**
 * Hero Trend Chart - uPlot
 *
 * Displays inline SNR + Power trend in the hero card
 * Dual Y-axis chart with 24h history
 */
(function() {
    'use strict';

    var heroChartInstance = null;
    var heroResizeObs = null;

    function getThemeColors() {
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        return {
            text: isDark ? 'rgba(224,224,224,0.9)' : 'rgba(30,30,30,0.9)',
            textMuted: isDark ? 'rgba(224,224,224,0.6)' : 'rgba(60,60,60,0.6)',
            grid: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.08)',
            tooltipBg: isDark ? 'rgba(15,20,25,0.95)' : 'rgba(255,255,255,0.95)',
            tooltipBorder: isDark ? 'rgba(168,85,247,0.3)' : 'rgba(168,85,247,0.4)',
            placeholder: isDark ? 'rgba(224,224,224,0.5)' : 'rgba(60,60,60,0.5)'
        };
    }

    function destroyHero() {
        if (heroResizeObs) { heroResizeObs.disconnect(); heroResizeObs = null; }
        if (heroChartInstance) { heroChartInstance.destroy(); heroChartInstance = null; }
    }

    function getContainer() {
        var el = document.getElementById('hero-trend-chart');
        if (!el) return null;
        if (el.tagName === 'CANVAS') {
            var div = document.createElement('div');
            div.id = 'hero-trend-chart';
            div.style.width = '100%';
            div.style.height = '100%';
            el.parentNode.replaceChild(div, el);
            return div;
        }
        el.textContent = '';
        el.style.width = '100%';
        el.style.height = '100%';
        return el;
    }

    function initHeroChart() {
        destroyHero();
        var container = getContainer();
        if (!container) return;

        fetch('/api/trends?range=week')
            .then(function(r) {
                if (!r.ok) throw new Error('API error: ' + r.status);
                return r.json();
            })
            .then(function(data) {
                if (!data || !Array.isArray(data) || data.length === 0) {
                    renderEmptyChart(container);
                    return;
                }
                var now = new Date();
                var cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);
                var filtered = data.filter(function(d) { return new Date(d.timestamp) >= cutoff; });
                if (filtered.length === 0) {
                    renderEmptyChart(container);
                    return;
                }
                renderChart(container, filtered);
            })
            .catch(function(err) {
                console.error('[HeroChart] Failed to load data:', err);
                renderEmptyChart(container);
            });
    }

    function heroTooltipPlugin(timestamps) {
        var tooltip;
        var overEl;
        function init(u) {
            overEl = u.over;
            tooltip = document.createElement('div');
            tooltip.className = 'uplot-tooltip';
            tooltip.style.display = 'none';
            tooltip.style.position = 'fixed';
            document.body.appendChild(tooltip);
        }
        function setCursor(u) {
            var idx = u.cursor.idx;
            if (idx == null) { tooltip.style.display = 'none'; return; }
            var c = getThemeColors();
            tooltip.textContent = '';
            var header = document.createElement('div');
            header.style.cssText = 'font-weight:600;margin-bottom:4px;';
            var ts = timestamps[idx];
            header.textContent = ts ? formatHeroDate(ts) : '';
            tooltip.appendChild(header);
            var units = ['', 'dBmV', 'dBmV', 'dB'];
            for (var i = 1; i < u.series.length; i++) {
                var s = u.series[i];
                if (!s.show) continue;
                var val = u.data[i][idx];
                if (val == null) continue;
                var color = s._stroke || s.stroke;
                if (typeof color === 'function') color = color(u, i);
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;gap:6px;';
                var marker = document.createElement('span');
                marker.style.cssText = 'width:10px;height:3px;display:inline-block;border-radius:1px;background:' + color;
                var label = document.createElement('span');
                label.textContent = s.label + ': ' + val.toFixed(1) + ' ' + (units[i] || '');
                row.appendChild(marker);
                row.appendChild(label);
                tooltip.appendChild(row);
            }
            tooltip.style.display = 'block';
            tooltip.style.background = c.tooltipBg;
            tooltip.style.color = c.text;
            tooltip.style.border = '1px solid ' + c.tooltipBorder;
            var rect = overEl.getBoundingClientRect();
            var left = rect.left + u.cursor.left;
            var top = rect.top + u.cursor.top;
            var tw = tooltip.offsetWidth;
            var th = tooltip.offsetHeight;
            var x = left + 12;
            var y = top - th - 8;
            if (x + tw > window.innerWidth) x = left - tw - 12;
            if (y < 0) y = top + 12;
            tooltip.style.left = x + 'px';
            tooltip.style.top = y + 'px';
        }
        function destroy() {
            if (tooltip && tooltip.parentNode) tooltip.parentNode.removeChild(tooltip);
        }
        return { hooks: { init: [init], setCursor: [setCursor], destroy: [destroy] } };
    }

    function formatHeroDate(ts) {
        var d = new Date(ts);
        var dd = d.getDate(), mm = d.getMonth() + 1, hh = d.getHours(), mi = d.getMinutes();
        return (dd < 10 ? '0' : '') + dd + '.' + (mm < 10 ? '0' : '') + mm + ' ' +
               (hh < 10 ? '0' : '') + hh + ':' + (mi < 10 ? '0' : '') + mi;
    }

    function renderChart(container, data) {
        var c = getThemeColors();
        var timestamps = data.map(function(d) { return d.timestamp; });
        var xData = [];
        for (var i = 0; i < data.length; i++) xData.push(i);
        var dsPower = data.map(function(d) { return d.ds_power_avg; });
        var usPower = data.map(function(d) { return d.us_power_avg; });
        var snr = data.map(function(d) { return d.ds_snr_avg; });
        var n = data.length;

        /* X-axis: show formatted time labels */
        var xLabels = timestamps.map(function(ts) {
            var d = new Date(ts);
            var hh = d.getHours(), mi = d.getMinutes();
            return (hh < 10 ? '0' : '') + hh + ':' + (mi < 10 ? '0' : '') + mi;
        });

        var wrap = container.parentElement;
        var width = container.offsetWidth || (wrap ? wrap.offsetWidth : 400);
        var height = (wrap ? wrap.offsetHeight : 100) || 100;

        var opts = {
            width: width,
            height: height,
            scales: {
                x: { time: false, range: function() { return [-0.5, n - 0.5]; } },
                power: {},
                snr: { range: [10, 50] }
            },
            axes: [
                {
                    scale: 'x',
                    show: false
                },
                {
                    scale: 'power',
                    side: 3,
                    stroke: 'rgba(168,85,247,0.9)',
                    grid: { stroke: c.grid, width: 1 },
                    ticks: { stroke: c.grid, width: 1 },
                    font: '10px system-ui',
                    size: 42,
                    gap: 2
                },
                {
                    scale: 'snr',
                    side: 1,
                    stroke: 'rgba(59,130,246,0.9)',
                    grid: { show: false },
                    ticks: { stroke: 'rgba(59,130,246,0.2)', width: 1 },
                    font: '10px system-ui',
                    size: 36,
                    gap: 2
                }
            ],
            series: [
                { label: 'X', value: function(u, v) { return xLabels[v] || ''; } },
                {
                    label: T.chart_ds_power || 'DS Power (dBmV)',
                    stroke: 'rgba(168,85,247,0.9)',
                    fill: 'rgba(168,85,247,0.15)',
                    width: 2,
                    scale: 'power',
                    points: { show: false }
                },
                {
                    label: T.chart_us_power || 'US Power (dBmV)',
                    stroke: 'rgba(245,158,11,0.9)',
                    fill: 'rgba(245,158,11,0.15)',
                    width: 2,
                    scale: 'power',
                    points: { show: false }
                },
                {
                    label: T.chart_snr || 'SNR (dB)',
                    stroke: 'rgba(59,130,246,0.9)',
                    fill: 'rgba(59,130,246,0.15)',
                    width: 2,
                    scale: 'snr',
                    points: { show: false }
                }
            ],
            cursor: { show: true, x: true, y: false, points: { show: false } },
            legend: { show: true, live: false },
            plugins: [heroTooltipPlugin(timestamps)]
        };

        heroChartInstance = new uPlot(opts, [xData, dsPower, usPower, snr], container);

        heroResizeObs = new ResizeObserver(function(entries) {
            var w = Math.round(entries[0].contentRect.width);
            var h = Math.round(entries[0].contentRect.height);
            if (w > 0 && h > 0 && (Math.abs(w - heroChartInstance.width) > 5 || Math.abs(h - heroChartInstance.height) > 5)) {
                heroChartInstance.setSize({width: w, height: h});
            }
        });
        heroResizeObs.observe(container);
    }

    function renderEmptyChart(container) {
        var c = getThemeColors();
        container.textContent = '';
        container.style.position = 'relative';
        var placeholder = document.createElement('div');
        placeholder.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:' + c.placeholder + ';font-size:13px;text-align:center;';
        placeholder.textContent = T.chart_no_history || 'No trend data available';
        container.appendChild(placeholder);
    }

    window.refreshHeroChart = initHeroChart;

    var themeToggle = document.getElementById('theme-toggle-sidebar');
    if (themeToggle) {
        themeToggle.addEventListener('change', function() {
            setTimeout(initHeroChart, 50);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initHeroChart);
    } else {
        initHeroChart();
    }
})();
