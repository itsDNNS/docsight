/* ── BNetzA Breitbandmessung ── */
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
            var verdictIcon = hasDeviation
                ? '<i data-lucide="triangle-alert"></i>'
                : '<i data-lucide="circle-check"></i>';
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
                complaintBtn = '<a href="javascript:void(0)" class="bnetz-action-btn" onclick="generateBnetzComplaint(' + m.id + ')" ' +
                    'title="' + (T.bnetz_generate_complaint || 'Generate complaint') + '">' +
                    '<i data-lucide="file-pen"></i></a>';
            }
            tr.innerHTML = '<td>' + (hasMeasurements ? '<button class="bnetz-expand-btn" id="bnetz-arrow-' + idx + '"><i data-lucide="chevron-right"></i></button> ' : '') + m.date + '</td>' +
                '<td>' + (m.provider || '-') + '</td>' +
                '<td>' + (m.download_max_tariff ? Math.round(m.download_max_tariff) + ' Mbit/s' : '-') + '</td>' +
                '<td>' + Math.round(m.download_measured_avg || 0) + ' Mbit/s' + (dlPct ? ' (' + dlPct + '%)' : '') + '</td>' +
                '<td>' + (m.upload_max_tariff ? Math.round(m.upload_max_tariff) + ' Mbit/s' : '-') + '</td>' +
                '<td>' + Math.round(m.upload_measured_avg || 0) + ' Mbit/s' + (ulPct ? ' (' + ulPct + '%)' : '') + '</td>' +
                '<td class="bnetz-verdict ' + verdictClass + '" title="' + verdictText + '">' + verdictIcon + '</td>' +
                '<td class="bnetz-actions-cell" onclick="event.stopPropagation();">' +
                    complaintBtn +
                    (m.source !== 'csv_import' ? '<a href="/api/bnetz/pdf/' + m.id + '" class="bnetz-action-btn" title="PDF"><i data-lucide="file-down"></i></a>' : '') +
                    '<a href="javascript:void(0)" class="bnetz-action-btn bnetz-action-delete" onclick="deleteBnetzFromView(' + m.id + ')" title="' + (T.delete_incident || 'Delete') + '"><i data-lucide="trash-2"></i></a>' +
                '</td>';
            tbody.appendChild(tr);
            // Detail expand row (hidden by default)
            if (hasMeasurements) {
                var detailTr = document.createElement('tr');
                detailTr.id = 'bnetz-detail-' + idx;
                detailTr.style.display = 'none';
                var detailTd = document.createElement('td');
                detailTd.colSpan = 8;
                detailTd.className = 'bnetz-detail-cell';
                detailTd.innerHTML = buildBnetzDetailHtml(m);
                detailTr.appendChild(detailTd);
                tbody.appendChild(detailTr);
            }
        });
        lucide.createIcons();
    }).catch(function() {
        loading.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = T.channel_error_loading || 'Error loading data';
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
                if (watcher.next_poll_in > 0) parts.push((T.bnetz_watcher_next_check || 'Next check in {min}min').replace('{min}', Math.round(watcher.next_poll_in / 60)));
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
    if (arrow) arrow.classList.toggle('open', !isOpen);
}

function buildBnetzDetailHtml(m) {
    var ms = m.measurements || {};
    var dlList = ms.download || [];
    var ulList = ms.upload || [];
    var html = '<div class="bnetz-detail-grid">';
    // Download measurements
    if (dlList.length > 0) {
        html += '<div><span class="bnetz-detail-label">' + (T.download || 'Download') + '</span>';
        html += '<table class="bnetz-detail-table">';
        html += '<tr><th>' + (T.bnetz_measurement_nr || 'Nr.') + '</th>' +
            '<th>' + (T.bnetz_measurement_time || 'Time') + '</th>' +
            '<th class="bnetz-detail-speed-col">' + (T.bnetz_measurement_speed || 'Speed') + '</th></tr>';
        dlList.forEach(function(meas, i) {
            var speed = meas.mbps || meas.speed || meas.value || 0;
            var color = 'var(--text)';
            if (m.download_min_tariff && speed < m.download_min_tariff) color = 'var(--crit)';
            else if (m.download_normal_tariff && speed < m.download_normal_tariff) color = 'var(--warn, orange)';
            html += '<tr>' +
                '<td>' + (i + 1) + '</td>' +
                '<td>' + (meas.date || '') + ' ' + (meas.time || '') + '</td>' +
                '<td class="bnetz-detail-speed-col" style="color:' + color + ';">' + (typeof speed === 'number' ? speed.toFixed(1) : speed) + ' Mbit/s</td></tr>';
        });
        html += '</table></div>';
    }
    // Upload measurements
    if (ulList.length > 0) {
        html += '<div><span class="bnetz-detail-label">' + (T.upload || 'Upload') + '</span>';
        html += '<table class="bnetz-detail-table">';
        html += '<tr><th>' + (T.bnetz_measurement_nr || 'Nr.') + '</th>' +
            '<th>' + (T.bnetz_measurement_time || 'Time') + '</th>' +
            '<th class="bnetz-detail-speed-col">' + (T.bnetz_measurement_speed || 'Speed') + '</th></tr>';
        ulList.forEach(function(meas, i) {
            var speed = meas.mbps || meas.speed || meas.value || 0;
            var color = 'var(--text)';
            if (m.upload_min_tariff && speed < m.upload_min_tariff) color = 'var(--crit)';
            else if (m.upload_normal_tariff && speed < m.upload_normal_tariff) color = 'var(--warn, orange)';
            html += '<tr>' +
                '<td>' + (i + 1) + '</td>' +
                '<td>' + (meas.date || '') + ' ' + (meas.time || '') + '</td>' +
                '<td class="bnetz-detail-speed-col" style="color:' + color + ';">' + (typeof speed === 'number' ? speed.toFixed(1) : speed) + ' Mbit/s</td></tr>';
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
        .catch(function(e) { alert((T.bnetz_upload_failed || 'Upload failed') + ': ' + e); input.value = ''; });
}

function deleteBnetzFromView(id) {
    if (!confirm(T.bnetz_delete_confirm)) return;
    fetch('/api/bnetz/' + id, {method: 'DELETE'})
        .then(function() { loadBnetzData(); });
}

