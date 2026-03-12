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
    var lastResolution = 'raw';
    var pinnedDayView = null; // { date: 'YYYY-MM-DD', start: epoch, end: epoch } when viewing a pinned day

    function updateRefreshInterval() {
        if (refreshTimer) clearInterval(refreshTimer);
        if (pinnedDayView) return; // no auto-refresh for pinned day views
        var interval = currentRange <= 86400 ? 10000 : 60000;
        refreshTimer = setInterval(function() {
            var view = document.getElementById('cm-detail-view');
            if (view && view.closest('.view.active')) {
                loadData();
            }
        }, interval);
    }

    function getMaxPointsForRange(seconds) {
        return seconds >= 86400 ? 1440 : 0;
    }

    window.cmSetRange = function(btn, seconds) {
        pinnedDayView = null;
        currentRange = seconds;
        document.querySelectorAll('[data-cm-range]').forEach(function(b) {
            b.classList.remove('active');
        });
        btn.classList.add('active');
        updatePinButton();
        loadData();
        updateRefreshInterval();
    };

    window.cmExportCsv = function(targetId) {
        var now = Date.now() / 1000;
        var start = now - currentRange;
        var a = document.createElement('a');
        a.href = '/api/connection-monitor/export/' + targetId + '?start=' + start + '&end=' + now + '&resolution=' + lastResolution;
        a.download = '';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    // --- Pin Button ---

    function updatePinButton() {
        var existing = document.getElementById('cm-pin-day-btn');
        if (existing) existing.remove();

        if (currentRange !== 86400 || pinnedDayView) return;

        var container = document.querySelector('#cm-detail-view [data-cm-range]');
        if (!container) return;
        var parent = container.parentElement;

        var btn = document.createElement('button');
        btn.id = 'cm-pin-day-btn';
        btn.className = 'trend-tab';
        btn.style.cssText = 'font-size:0.75rem;padding:4px 10px;margin-left:4px;';
        btn.textContent = '\uD83D\uDCCC Pin this day';
        btn.onclick = function() {
            var now = new Date();
            var dateStr = now.getFullYear() + '-' +
                String(now.getMonth() + 1).padStart(2, '0') + '-' +
                String(now.getDate()).padStart(2, '0');
            fetch('/api/connection-monitor/pinned-days', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ date: dateStr })
            }).then(function() {
                loadPinnedDays();
            });
        };
        parent.appendChild(btn);
    }

    // --- Pinned Days Bar ---

    function loadPinnedDays() {
        fetch('/api/connection-monitor/pinned-days')
            .then(function(r) { return r.json(); })
            .then(function(days) {
                renderPinnedDays(days);
            })
            .catch(function() {});
    }

    function renderPinnedDays(days) {
        var bar = document.getElementById('cm-pinned-days-bar');
        var container = document.getElementById('cm-pinned-days');
        if (!bar || !container) return;

        container.textContent = '';
        if (days.length === 0) {
            bar.style.display = 'none';
            return;
        }
        bar.style.display = '';

        days.forEach(function(day) {
            var chip = document.createElement('button');
            chip.className = 'trend-tab';
            chip.style.cssText = 'font-size:0.72rem;padding:3px 8px;display:inline-flex;align-items:center;gap:4px;';
            if (pinnedDayView && pinnedDayView.date === day.date) {
                chip.classList.add('active');
            }

            var label = day.label ? day.date + ' (' + day.label + ')' : day.date;
            var textSpan = document.createElement('span');
            textSpan.textContent = label;
            textSpan.style.cursor = 'pointer';
            textSpan.onclick = function(e) {
                e.stopPropagation();
                viewPinnedDay(day.date);
            };

            var removeBtn = document.createElement('span');
            removeBtn.textContent = '\u00d7';
            removeBtn.style.cssText = 'cursor:pointer;font-size:0.85rem;line-height:1;opacity:0.6;';
            removeBtn.onclick = function(e) {
                e.stopPropagation();
                fetch('/api/connection-monitor/pinned-days/' + day.date, { method: 'DELETE' })
                    .then(function() { loadPinnedDays(); });
            };

            chip.appendChild(textSpan);
            chip.appendChild(removeBtn);
            container.appendChild(chip);
        });
    }

    function viewPinnedDay(dateStr) {
        var parts = dateStr.split('-');
        var dayStart = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        var dayEnd = new Date(dayStart);
        dayEnd.setDate(dayEnd.getDate() + 1);

        pinnedDayView = {
            date: dateStr,
            start: dayStart.getTime() / 1000,
            end: dayEnd.getTime() / 1000
        };

        // Deactivate range buttons
        document.querySelectorAll('[data-cm-range]').forEach(function(b) {
            b.classList.remove('active');
        });
        var pinBtn = document.getElementById('cm-pin-day-btn');
        if (pinBtn) pinBtn.remove();

        if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }

        loadData();
        loadPinnedDays(); // refresh to highlight active
    }

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
        loadPinnedDays();

        updateRefreshInterval();
    }

    function loadTargets() {
        fetch('/api/connection-monitor/targets')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                targets = data.filter(function(t) { return t.enabled; });
                if (targets.length > 0) {
                    loadData();
                    updatePinButton();
                } else {
                    showNoData();
                }
            })
            .catch(function() {});
    }

    function loadData() {
        if (targets.length === 0) { showNoData(); return; }

        var now = Date.now() / 1000;
        var start, end;
        if (pinnedDayView) {
            start = pinnedDayView.start;
            end = pinnedDayView.end;
        } else {
            start = now - currentRange;
            end = now;
        }
        var maxPoints = pinnedDayView ? 0 : getMaxPointsForRange(currentRange);

        // Fetch samples for ALL targets in parallel
        var samplePromises = targets.map(function(t) {
            var url = '/api/connection-monitor/samples/' + t.id + '?start=' + start + '&end=' + end + '&limit=0';
            if (maxPoints > 0) {
                url += '&max_points=' + maxPoints;
            }
            return fetch(url)
                .then(function(r) { return r.json(); })
                .then(function(data) { return { target: t, samples: data.samples, meta: data.meta }; });
        });

        var statsPromise = fetch('/api/connection-monitor/stats?start=' + start + '&end=' + end)
            .then(function(r) { return r.json(); });

        // Fetch outages for ALL targets in parallel
        var outagePromises = targets.map(function(t) {
            return fetch('/api/connection-monitor/outages/' + t.id + '?start=' + start + '&end=' + end)
                .then(function(r) { return r.json(); })
                .then(function(outages) { return { target: t, outages: outages }; });
        });

        Promise.all([Promise.all(samplePromises), Promise.all(outagePromises), statsPromise])
            .then(function(results) {
                var allTargetData = results[0];
                var allOutageData = results[1];
                var statsByTarget = results[2] || {};

                allTargetData.forEach(function(td) {
                    td.stats = statsByTarget[String(td.target.id)] || statsByTarget[td.target.id] || null;
                });

                var hasSamples = allTargetData.some(function(td) {
                    return td.samples && td.samples.length > 0;
                });
                if (!hasSamples) { showNoData(); return; }

                var meta = allTargetData.length > 0 ? allTargetData[0].meta : null;
                if (meta && meta.resolution) lastResolution = meta.resolution;
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
        if (pinnedDayView) {
            el.textContent = 'Pinned: ' + pinnedDayView.date + ' (full resolution)';
            el.style.display = '';
            return;
        }
        if (meta.mixed && Array.isArray(meta.tiers_used) && meta.tiers_used.length > 0) {
            el.textContent = meta.tiers_used.map(function(tier) {
                return labels[tier] || tier;
            }).join(' + ');
        } else {
            el.textContent = labels[meta.resolution] || meta.resolution;
        }
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
