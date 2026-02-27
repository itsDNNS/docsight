/* ── BNetzA Breitbandmessung + Smokeping Graphs ── */
/* Extracted from IIFE – depends on: T, showToast */

/* ── BNetzA Breitbandmessung ── */
function loadBnetzData() {
    var loading = document.getElementById('bnetz-loading');
    var empty = document.getElementById('bnetz-empty');
    var card = document.getElementById('bnetz-table-card');
    var tbody = document.getElementById('bnetz-tbody');
    if (!loading) return;
    loading.style.display = 'block';
    empty.style.display = 'none';
    card.style.display = 'none';
    fetch('/api/bnetz/measurements').then(function(r) { return r.json(); }).then(function(data) {
        loading.style.display = 'none';
        if (!data || data.length === 0) {
            empty.style.display = 'block';
            return;
        }
        card.style.display = 'block';
        tbody.innerHTML = '';
        data.forEach(function(m, idx) {
            var hasDeviation = m.verdict_download === 'deviation' || m.verdict_upload === 'deviation';
            var verdictText = hasDeviation ? T.bnetz_verdict_deviation : T.bnetz_verdict_ok;
            var verdictClass = hasDeviation ? 'val-crit' : 'val-good';
            var dlPct = m.download_max_tariff ? Math.round(m.download_measured_avg / m.download_max_tariff * 100) : 0;
            var ulPct = m.upload_max_tariff ? Math.round(m.upload_measured_avg / m.upload_max_tariff * 100) : 0;
            var hasMeasurements = m.measurements && (
                (m.measurements.download && m.measurements.download.length > 0) ||
                (m.measurements.upload && m.measurements.upload.length > 0));
            var tr = document.createElement('tr');
            tr.style.cursor = hasMeasurements ? 'pointer' : 'default';
            tr.setAttribute('data-bnetz-idx', idx);
            if (hasMeasurements) {
                tr.onclick = function() { toggleBnetzDetail(idx); };
            }
            var complaintBtn = '';
            if (hasDeviation) {
                complaintBtn = '<a href="javascript:void(0)" onclick="generateBnetzComplaint(' + m.id + ')" ' +
                    'title="' + (T.bnetz_generate_complaint || 'Generate complaint') + '" ' +
                    'style="margin-right:8px;">&#9998;</a>';
            }
            tr.innerHTML = '<td>' + (hasMeasurements ? '<span class="bnetz-expand-arrow" id="bnetz-arrow-' + idx + '">&#9654;</span> ' : '') + m.date + '</td>' +
                '<td>' + (m.provider || '-') + '</td>' +
                '<td>' + Math.round(m.download_max_tariff || 0) + ' Mbit/s</td>' +
                '<td>' + Math.round(m.download_measured_avg || 0) + ' Mbit/s (' + dlPct + '%)</td>' +
                '<td>' + Math.round(m.upload_max_tariff || 0) + ' Mbit/s</td>' +
                '<td>' + Math.round(m.upload_measured_avg || 0) + ' Mbit/s (' + ulPct + '%)</td>' +
                '<td class="' + verdictClass + '">' + verdictText + '</td>' +
                '<td style="white-space:nowrap;" onclick="event.stopPropagation();">' +
                    complaintBtn +
                    (m.source !== 'csv_import' ? '<a href="/api/bnetz/pdf/' + m.id + '" title="PDF" style="margin-right:8px;">&#128196;</a>' : '') +
                    '<a href="javascript:void(0)" onclick="deleteBnetzFromView(' + m.id + ')" title="' + (T.delete_incident || 'Delete') + '">&#128465;</a>' +
                '</td>';
            tbody.appendChild(tr);
            // Detail expand row (hidden by default)
            if (hasMeasurements) {
                var detailTr = document.createElement('tr');
                detailTr.id = 'bnetz-detail-' + idx;
                detailTr.style.display = 'none';
                var detailTd = document.createElement('td');
                detailTd.colSpan = 8;
                detailTd.style.padding = '0 8px 12px 24px';
                detailTd.innerHTML = buildBnetzDetailHtml(m);
                detailTr.appendChild(detailTd);
                tbody.appendChild(detailTr);
            }
        });
        lucide.createIcons();
    }).catch(function() {
        loading.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = 'Error loading data';
    });

    /* Fetch watcher status for the banner */
    var watcherBanner = document.getElementById('bnetz-watcher-status');
    var watcherText = document.getElementById('bnetz-watcher-text');
    if (watcherBanner) {
        fetch('/api/collectors/status').then(function(r) { return r.json(); }).then(function(collectors) {
            var watcher = null;
            for (var i = 0; i < collectors.length; i++) {
                if (collectors[i].name === 'bnetz_watcher') { watcher = collectors[i]; break; }
            }
            if (watcher && watcher.enabled) {
                watcherBanner.style.display = 'flex';
                var parts = [(T.bnetz_watcher_active || 'File watcher active')];
                if (watcher.watch_dir) parts.push((T.bnetz_watcher_watching || 'Watching {dir}').replace('{dir}', watcher.watch_dir));
                if (watcher.last_import_count > 0) parts.push((T.bnetz_watcher_last_import || '{count} file(s) imported').replace('{count}', watcher.last_import_count));
                if (watcher.next_poll_in > 0) parts.push('Next check in ' + Math.round(watcher.next_poll_in / 60) + 'min');
                watcherText.textContent = parts.join(' · ');
                lucide.createIcons();
            } else {
                watcherBanner.style.display = 'none';
            }
        }).catch(function() { watcherBanner.style.display = 'none'; });
    }
}

function toggleBnetzDetail(idx) {
    var row = document.getElementById('bnetz-detail-' + idx);
    var arrow = document.getElementById('bnetz-arrow-' + idx);
    if (!row) return;
    var isOpen = row.style.display !== 'none';
    row.style.display = isOpen ? 'none' : 'table-row';
    if (arrow) arrow.innerHTML = isOpen ? '&#9654;' : '&#9660;';
}

function buildBnetzDetailHtml(m) {
    var ms = m.measurements || {};
    var dlList = ms.download || [];
    var ulList = ms.upload || [];
    var html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:8px;">';
    // Download measurements
    if (dlList.length > 0) {
        html += '<div><strong style="font-size:0.85em;color:var(--text-secondary);">' + (T.download || 'Download') + '</strong>';
        html += '<table style="width:100%;font-size:0.8em;border-collapse:collapse;margin-top:4px;">';
        html += '<tr style="color:var(--text-secondary);border-bottom:1px solid var(--card-border);">' +
            '<th style="text-align:left;padding:3px 6px;">' + (T.bnetz_measurement_nr || 'Nr.') + '</th>' +
            '<th style="text-align:left;padding:3px 6px;">' + (T.bnetz_measurement_time || 'Time') + '</th>' +
            '<th style="text-align:right;padding:3px 6px;">' + (T.bnetz_measurement_speed || 'Speed') + '</th></tr>';
        dlList.forEach(function(meas, i) {
            var speed = meas.speed || meas.value || 0;
            var color = 'var(--text)';
            if (m.download_min_tariff && speed < m.download_min_tariff) color = 'var(--crit)';
            else if (m.download_normal_tariff && speed < m.download_normal_tariff) color = 'var(--warn, orange)';
            html += '<tr style="border-bottom:1px solid var(--card-border);">' +
                '<td style="padding:3px 6px;">' + (i + 1) + '</td>' +
                '<td style="padding:3px 6px;">' + (meas.date || '') + ' ' + (meas.time || '') + '</td>' +
                '<td style="text-align:right;padding:3px 6px;color:' + color + ';">' + (typeof speed === 'number' ? speed.toFixed(1) : speed) + ' Mbit/s</td></tr>';
        });
        html += '</table></div>';
    }
    // Upload measurements
    if (ulList.length > 0) {
        html += '<div><strong style="font-size:0.85em;color:var(--text-secondary);">' + (T.upload || 'Upload') + '</strong>';
        html += '<table style="width:100%;font-size:0.8em;border-collapse:collapse;margin-top:4px;">';
        html += '<tr style="color:var(--text-secondary);border-bottom:1px solid var(--card-border);">' +
            '<th style="text-align:left;padding:3px 6px;">' + (T.bnetz_measurement_nr || 'Nr.') + '</th>' +
            '<th style="text-align:left;padding:3px 6px;">' + (T.bnetz_measurement_time || 'Time') + '</th>' +
            '<th style="text-align:right;padding:3px 6px;">' + (T.bnetz_measurement_speed || 'Speed') + '</th></tr>';
        ulList.forEach(function(meas, i) {
            var speed = meas.speed || meas.value || 0;
            var color = 'var(--text)';
            if (m.upload_min_tariff && speed < m.upload_min_tariff) color = 'var(--crit)';
            else if (m.upload_normal_tariff && speed < m.upload_normal_tariff) color = 'var(--warn, orange)';
            html += '<tr style="border-bottom:1px solid var(--card-border);">' +
                '<td style="padding:3px 6px;">' + (i + 1) + '</td>' +
                '<td style="padding:3px 6px;">' + (meas.date || '') + ' ' + (meas.time || '') + '</td>' +
                '<td style="text-align:right;padding:3px 6px;color:' + color + ';">' + (typeof speed === 'number' ? speed.toFixed(1) : speed) + ' Mbit/s</td></tr>';
        });
        html += '</table></div>';
    }
    html += '</div>';
    return html;
}

function uploadBnetzFromView(input) {
    if (!input.files || !input.files[0]) return;
    var fd = new FormData();
    fd.append('file', input.files[0]);
    fetch('/api/bnetz/upload', {method: 'POST', body: fd})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            input.value = '';
            if (data.error) { alert(data.error); return; }
            loadBnetzData();
        })
        .catch(function(e) { alert('Upload failed: ' + e); input.value = ''; });
}

function deleteBnetzFromView(id) {
    if (!confirm(T.bnetz_delete_confirm)) return;
    fetch('/api/bnetz/' + id, {method: 'DELETE'})
        .then(function() { loadBnetzData(); });
}

/* ── Smokeping Graphs ── */
var _smokepingSpan = '3h';
var smokepingTabs = document.querySelectorAll('#smokeping-tabs .trend-tab');
smokepingTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _smokepingSpan = this.getAttribute('data-span');
        smokepingTabs.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-span') === _smokepingSpan);
        });
        loadSmokepingGraphs();
    });
});

function loadSmokepingGraphs() {
    var content = document.getElementById('smokeping-content');
    var noData = document.getElementById('smokeping-no-data');
    if (!content || !noData) return;
    content.innerHTML = '';
    noData.style.display = 'none';

    fetch('/api/smokeping/targets')
        .then(function(r) { return r.json(); })
        .then(function(targets) {
            if (!targets || targets.length === 0) {
                noData.textContent = T.smokeping_no_data || 'Could not load Smokeping graphs.';
                noData.style.display = 'block';
                return;
            }
            targets.forEach(function(target) {
                var card = document.createElement('div');
                card.className = 'bqm-card';
                var header = document.createElement('div');
                header.className = 'chart-card-header';
                header.innerHTML = '<div class="chart-header-content"><div class="chart-label">' + target + '</div></div>';
                card.appendChild(header);
                var wrap = document.createElement('div');
                wrap.style.textAlign = 'center';
                var img = document.createElement('img');
                img.style.maxWidth = '100%';
                img.style.borderRadius = '8px';
                img.alt = target;
                img.src = '/api/smokeping/graph/' + encodeURIComponent(target) + '/' + _smokepingSpan;
                img.onerror = function() {
                    wrap.innerHTML = '<div class="no-data-msg" style="display:block;">' + (T.smokeping_no_data || 'Could not load graph.') + '</div>';
                };
                wrap.appendChild(img);
                card.appendChild(wrap);
                content.appendChild(card);
            });
        })
        .catch(function() {
            noData.textContent = T.smokeping_no_data || 'Could not load Smokeping graphs.';
            noData.style.display = 'block';
        });
}

window.loadSmokepingGraphs = loadSmokepingGraphs;
