/**
 * Connection Monitor Detail View - PingPlotter-style
 * Fetches all targets in parallel, renders combined chart with zones + loss markers.
 */
/* global CMCharts */
(function() {
    'use strict';

    var currentRange = 3600; // 1h default
    var targets = [];
    var refreshTimer = null;

    function updateRefreshInterval() {
        if (refreshTimer) clearInterval(refreshTimer);
        var interval = currentRange <= 86400 ? 10000 : 60000;
        refreshTimer = setInterval(function() {
            var view = document.getElementById('cm-detail-view');
            if (view && view.closest('.view.active')) {
                loadData();
            }
        }, interval);
    }

    window.cmSetRange = function(btn, seconds) {
        currentRange = seconds;
        document.querySelectorAll('[data-cm-range]').forEach(function(b) {
            b.classList.remove('active');
        });
        btn.classList.add('active');
        loadData();
        updateRefreshInterval();
    };

    window.cmExportCsv = function(targetId) {
        var now = Date.now() / 1000;
        var start = now - currentRange;
        var res = 'raw';
        if (currentRange > 90 * 86400) res = '1hr';
        else if (currentRange > 30 * 86400) res = '5min';
        else if (currentRange > 7 * 86400) res = '1min';
        var a = document.createElement('a');
        a.href = '/api/connection-monitor/export/' + targetId + '?start=' + start + '&end=' + now + '&resolution=' + res;
        a.download = '';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    function init() {
        fetch('/api/connection-monitor/capability')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var el = document.getElementById('cm-capability-info');
                if (!el) return;
                var isTcp = data.method === 'tcp';
                var label = isTcp
                    ? (el.dataset.methodTcp || 'TCP')
                    : (el.dataset.methodIcmp || 'ICMP');

                // Badge
                var badge = document.createElement('span');
                badge.style.cssText = 'padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;' +
                    (isTcp ? 'background:rgba(234,179,8,0.15);color:#eab308;' : 'background:rgba(34,197,94,0.15);color:#22c55e;');
                badge.textContent = label + ' mode';
                el.appendChild(badge);

                // Glossary hint with popover (only for TCP)
                if (isTcp && el.dataset.hintTcp) {
                    var hint = document.createElement('span');
                    hint.className = 'glossary-hint';
                    var icon = document.createElement('i');
                    icon.setAttribute('data-lucide', 'info');
                    var popover = document.createElement('div');
                    popover.className = 'glossary-popover';
                    popover.textContent = el.dataset.hintTcp;
                    hint.appendChild(icon);
                    hint.appendChild(popover);
                    el.appendChild(hint);
                    if (window.lucide) lucide.createIcons();
                }
            })
            .catch(function() {});

        loadTargets();

        updateRefreshInterval();
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
            return fetch('/api/connection-monitor/samples/' + t.id + '?start=' + start + '&end=' + now + '&limit=0')
                .then(function(r) { return r.json(); })
                .then(function(data) { return { target: t, samples: data.samples, meta: data.meta }; });
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

                var meta = allTargetData.length > 0 ? allTargetData[0].meta : null;
                hideNoData();
                CMCharts.renderStatsCards('cm-stats-cards', allTargetData);
                CMCharts.renderPerTargetStats('cm-per-target-stats', allTargetData);
                CMCharts.renderCombinedChart('cm-combined-chart', allTargetData);
                CMCharts.renderAvailabilityBand('cm-availability', allTargetData);
                renderOutages(allOutageData);
                renderExportLinks();
                renderResolutionIndicator(meta);
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

        // Flatten all outages, then group overlapping ones across targets
        var flat = [];
        allOutageData.forEach(function(od) {
            if (!od.outages) return;
            od.outages.forEach(function(o) {
                flat.push({ target: od.target, outage: o });
            });
        });
        flat.sort(function(a, b) { return (a.outage.start || 0) - (b.outage.start || 0); });

        // Merge outages that overlap in time (same root cause across targets)
        var grouped = [];
        flat.forEach(function(item) {
            var o = item.outage;
            var merged = false;
            for (var i = grouped.length - 1; i >= 0; i--) {
                var g = grouped[i];
                // Overlap if starts are within 60s of each other
                if (Math.abs((g.start || 0) - (o.start || 0)) < 60) {
                    if (g.targets.indexOf(item.target.label) === -1) {
                        g.targets.push(item.target.label);
                    }
                    // Use widest window
                    if (o.end && g.end && o.end > g.end) g.end = o.end;
                    if (!o.end) g.end = null;
                    g.duration = Math.max(g.duration || 0, o.duration_seconds || 0);
                    merged = true;
                    break;
                }
            }
            if (!merged) {
                grouped.push({
                    targets: [item.target.label],
                    start: o.start,
                    end: o.end,
                    duration: o.duration_seconds || 0,
                    ongoing: !o.end
                });
            }
        });
        grouped.sort(function(a, b) { return (b.start || 0) - (a.start || 0); });

        tbody.textContent = '';

        if (grouped.length === 0) {
            var emptyRow = document.createElement('tr');
            var emptyCell = document.createElement('td');
            emptyCell.colSpan = 4;
            emptyCell.style.cssText = 'text-align:center;color:var(--text-muted);padding:20px;';
            emptyCell.textContent = '\u2014';
            emptyRow.appendChild(emptyCell);
            tbody.appendChild(emptyRow);
            return;
        }

        grouped.forEach(function(g) {
            var tr = document.createElement('tr');

            var tdTarget = document.createElement('td');
            tdTarget.textContent = g.targets.join(', ');

            var tdStart = document.createElement('td');
            tdStart.textContent = new Date(g.start * 1000).toLocaleString();

            var tdEnd = document.createElement('td');
            if (g.ongoing) {
                var span = document.createElement('span');
                span.style.color = 'var(--crit)';
                span.textContent = 'Ongoing';
                tdEnd.appendChild(span);
            } else if (g.end) {
                tdEnd.textContent = new Date(g.end * 1000).toLocaleString();
            }

            var tdDur = document.createElement('td');
            tdDur.style.textAlign = 'right';
            tdDur.textContent = g.duration ? formatDuration(g.duration) : '\u2014';

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

    function renderResolutionIndicator(meta) {
        var el = document.getElementById('cm-resolution-indicator');
        if (!el || !meta) return;
        var labels = {
            'raw': el.dataset.labelRaw || 'Raw samples',
            '1min': el.dataset.label1min || '1-min averages',
            '5min': el.dataset.label5min || '5-min averages',
            '1hr': el.dataset.label1hr || '1-hour averages'
        };
        el.textContent = labels[meta.resolution] || meta.resolution;
        el.style.display = '';
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
