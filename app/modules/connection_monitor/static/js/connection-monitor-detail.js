/**
 * Connection Monitor Detail View - PingPlotter-style
 * Fetches all targets in parallel, renders combined chart with zones + loss markers.
 */
/* global CMCharts */
(function() {
    'use strict';

    var currentRange = 3600; // 1h default
    var targets = [];

    window.cmSetRange = function(btn, seconds) {
        currentRange = seconds;
        document.querySelectorAll('[data-cm-range]').forEach(function(b) {
            b.classList.remove('active');
        });
        btn.classList.add('active');
        loadData();
    };

    window.cmExportCsv = function(targetId) {
        var now = Date.now() / 1000;
        var start = now - currentRange;
        window.location.href = '/api/connection-monitor/export/' + targetId + '?start=' + start + '&end=' + now;
    };

    function init() {
        fetch('/api/connection-monitor/capability')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var el = document.getElementById('cm-capability-info');
                if (el && data.method === 'tcp') {
                    el.textContent = data.reason || 'TCP mode';
                }
            })
            .catch(function() {});

        loadTargets();

        // Auto-refresh every 10s when view is active
        setInterval(function() {
            var view = document.getElementById('cm-detail-view');
            if (view && view.closest('.view.active')) {
                loadData();
            }
        }, 10000);
    }

    function loadTargets() {
        fetch('/api/connection-monitor/targets')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                targets = data.filter(function(t) { return t.enabled; });
                if (targets.length > 0) {
                    loadData();
                } else {
                    showNoData();
                }
            })
            .catch(function() {});
    }

    function loadData() {
        if (targets.length === 0) { showNoData(); return; }

        var now = Date.now() / 1000;
        var start = now - currentRange;

        // Fetch samples for ALL targets in parallel
        var samplePromises = targets.map(function(t) {
            return fetch('/api/connection-monitor/samples/' + t.id + '?start=' + start + '&end=' + now)
                .then(function(r) { return r.json(); })
                .then(function(samples) { return { target: t, samples: samples }; });
        });

        // Fetch outages for ALL targets in parallel
        var outagePromises = targets.map(function(t) {
            return fetch('/api/connection-monitor/outages/' + t.id + '?start=' + start + '&end=' + now)
                .then(function(r) { return r.json(); })
                .then(function(outages) { return { target: t, outages: outages }; });
        });

        Promise.all([Promise.all(samplePromises), Promise.all(outagePromises)])
            .then(function(results) {
                var allTargetData = results[0];
                var allOutageData = results[1];

                var hasSamples = allTargetData.some(function(td) {
                    return td.samples && td.samples.length > 0;
                });
                if (!hasSamples) { showNoData(); return; }

                hideNoData();
                CMCharts.renderCombinedChart('cm-combined-chart', allTargetData);
                CMCharts.renderAvailabilityBand('cm-availability', allTargetData);
                renderOutages(allOutageData);
                renderExportLinks();
            })
            .catch(function() {});
    }

    function renderExportLinks() {
        var container = document.getElementById('cm-export-links');
        if (!container) return;
        container.textContent = '';
        targets.forEach(function(t) {
            var btn = document.createElement('button');
            btn.className = 'trend-tab';
            btn.style.cssText = 'font-size:0.75rem;padding:4px 10px;';
            btn.textContent = t.label;
            btn.onclick = function() { window.cmExportCsv(t.id); };
            container.appendChild(btn);
        });
    }

    function renderOutages(allOutageData) {
        var tbody = document.getElementById('cm-outage-tbody');
        if (!tbody) return;

        // Flatten all outages with target info, sorted by start time desc
        var allOutages = [];
        allOutageData.forEach(function(od) {
            if (!od.outages) return;
            od.outages.forEach(function(o) {
                allOutages.push({ target: od.target, outage: o });
            });
        });
        allOutages.sort(function(a, b) { return (b.outage.start || 0) - (a.outage.start || 0); });

        tbody.textContent = '';

        if (allOutages.length === 0) {
            var emptyRow = document.createElement('tr');
            var emptyCell = document.createElement('td');
            emptyCell.colSpan = 4;
            emptyCell.style.cssText = 'text-align:center;color:var(--text-muted);padding:20px;';
            emptyCell.textContent = '\u2014';
            emptyRow.appendChild(emptyCell);
            tbody.appendChild(emptyRow);
            return;
        }

        allOutages.forEach(function(item) {
            var o = item.outage;
            var tr = document.createElement('tr');

            var tdTarget = document.createElement('td');
            tdTarget.textContent = item.target.label;

            var tdStart = document.createElement('td');
            tdStart.textContent = new Date(o.start * 1000).toLocaleString();

            var tdEnd = document.createElement('td');
            if (o.end) {
                tdEnd.textContent = new Date(o.end * 1000).toLocaleString();
            } else {
                var span = document.createElement('span');
                span.style.color = 'var(--crit)';
                span.textContent = 'Ongoing';
                tdEnd.appendChild(span);
            }

            var tdDur = document.createElement('td');
            tdDur.textContent = o.duration_s ? formatDuration(o.duration_s) : '\u2014';

            tr.appendChild(tdTarget);
            tr.appendChild(tdStart);
            tr.appendChild(tdEnd);
            tr.appendChild(tdDur);
            tbody.appendChild(tr);
        });
    }

    function formatDuration(seconds) {
        if (seconds < 60) return seconds + 's';
        if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        return h + 'h ' + m + 'm';
    }

    function showNoData() {
        var noData = document.getElementById('cm-no-data');
        var chartsEl = document.getElementById('cm-charts-section');
        if (noData) noData.style.display = '';
        if (chartsEl) chartsEl.style.display = 'none';
    }

    function hideNoData() {
        var noData = document.getElementById('cm-no-data');
        var chartsEl = document.getElementById('cm-charts-section');
        if (noData) noData.style.display = 'none';
        if (chartsEl) chartsEl.style.display = '';
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
