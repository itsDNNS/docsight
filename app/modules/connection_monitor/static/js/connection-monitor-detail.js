/**
 * Connection Monitor Detail View
 */
(function() {
    'use strict';

    var currentTargetId = null;
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

    window.cmExportCsv = function() {
        if (!currentTargetId) return;
        var now = Date.now() / 1000;
        var start = now - currentRange;
        window.location.href = '/api/connection-monitor/export/' + currentTargetId + '?start=' + start + '&end=' + now;
    };

    function init() {
        // Load capability info
        fetch('/api/connection-monitor/capability')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var el = document.getElementById('cm-capability-info');
                if (el && data.method === 'tcp') {
                    el.textContent = data.reason || 'TCP mode';
                }
            })
            .catch(function() {});

        // Load targets and select first
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
                targets = data;
                renderTargetTabs();
                if (targets.length > 0) {
                    selectTarget(targets[0].id);
                } else {
                    showNoData();
                }
            })
            .catch(function() {});
    }

    function renderTargetTabs() {
        var container = document.getElementById('cm-target-tabs');
        if (!container) return;

        container.textContent = '';
        targets.forEach(function(t) {
            var btn = document.createElement('button');
            btn.className = t.id === currentTargetId ? 'trend-tab active' : 'trend-tab';
            btn.onclick = function() { cmSelectTarget(t.id); };

            var labelText = document.createTextNode(t.label + ' ');
            var hostSpan = document.createElement('span');
            hostSpan.style.cssText = 'font-size:0.75rem;color:var(--text-muted);';
            hostSpan.textContent = '(' + t.host + ')';

            btn.appendChild(labelText);
            btn.appendChild(hostSpan);
            container.appendChild(btn);
        });
    }

    window.cmSelectTarget = function(id) {
        selectTarget(id);
    };

    function selectTarget(id) {
        currentTargetId = id;
        renderTargetTabs();
        loadData();
    }

    function loadData() {
        if (!currentTargetId) return;

        var now = Date.now() / 1000;
        var start = now - currentRange;

        // Fetch samples and outages in parallel
        Promise.all([
            fetch('/api/connection-monitor/samples/' + currentTargetId + '?start=' + start + '&end=' + now).then(function(r) { return r.json(); }),
            fetch('/api/connection-monitor/outages/' + currentTargetId + '?start=' + start + '&end=' + now).then(function(r) { return r.json(); })
        ]).then(function(results) {
            var samples = results[0];
            var outages = results[1];

            if (!samples || samples.length === 0) {
                showNoData();
                return;
            }

            hideNoData();

            // Determine loss chart bucket size based on range
            var windowMs = currentRange <= 3600   ? 30000  :  // 1h  -> 30s buckets
                           currentRange <= 21600  ? 60000  :  // 6h  -> 1m  buckets
                           currentRange <= 86400  ? 300000 :  // 24h -> 5m  buckets
                                                    900000;   // 7d  -> 15m buckets

            CMCharts.renderLatencyChart('cm-latency-chart', samples);
            CMCharts.renderLossChart('cm-loss-chart', samples, windowMs);
            CMCharts.renderAvailabilityBand('cm-availability', samples);
            renderOutages(outages);
        }).catch(function() {});
    }

    function renderOutages(outages) {
        var tbody = document.getElementById('cm-outage-tbody');
        if (!tbody) return;

        if (!outages || outages.length === 0) {
            tbody.textContent = '';
            var emptyRow = document.createElement('tr');
            var emptyCell = document.createElement('td');
            emptyCell.colSpan = 3;
            emptyCell.style.cssText = 'text-align:center;color:var(--text-muted);padding:20px;';
            emptyCell.textContent = '\u2014';
            emptyRow.appendChild(emptyCell);
            tbody.appendChild(emptyRow);
            return;
        }

        tbody.textContent = '';
        outages.forEach(function(o) {
            var tr = document.createElement('tr');

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
        var charts = document.getElementById('cm-charts-section');
        if (noData) noData.style.display = '';
        if (charts) charts.style.display = 'none';
    }

    function hideNoData() {
        var noData = document.getElementById('cm-no-data');
        var charts = document.getElementById('cm-charts-section');
        if (noData) noData.style.display = 'none';
        if (charts) charts.style.display = '';
    }

    // Init on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
