/* ── BNetzA Breitbandmessung ── */
/* Extracted from IIFE – depends on: T, showToast */

function _bnetzIcon(name) {
    var icon = document.createElement('i');
    icon.setAttribute('data-lucide', name);
    return icon;
}

function _bnetzCell(label, text) {
    var cell = document.createElement('td');
    cell.setAttribute('data-label', label);
    cell.textContent = text;
    return cell;
}

/* Cells only shown on mobile once the row is expanded. */
function _bnetzSecondary(cell) {
    cell.classList.add('bnetz-secondary-cell');
    return cell;
}

function _bnetzActionButton(className, title, iconName, handler) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.title = title;
    button.setAttribute('aria-label', title);
    button.appendChild(_bnetzIcon(iconName));
    button.addEventListener('click', handler);
    return button;
}

/* Keeps the action icons in the same column position on every row. */
function _bnetzActionPlaceholder() {
    var slot = document.createElement('span');
    slot.className = 'bnetz-action-btn bnetz-action-placeholder';
    slot.setAttribute('aria-hidden', 'true');
    slot.appendChild(_bnetzIcon('file-pen'));
    return slot;
}

function _bnetzMeasurementSection(label, measurements, minimum, normal) {
    var section = document.createElement('div');
    var heading = document.createElement('span');
    heading.className = 'bnetz-detail-label';
    heading.textContent = label;
    section.appendChild(heading);

    var table = document.createElement('table');
    table.className = 'bnetz-detail-table';
    var header = document.createElement('tr');
    [T.bnetz_measurement_nr || 'Nr.', T.bnetz_measurement_time || 'Time', T.bnetz_measurement_speed || 'Speed'].forEach(function(text, index) {
        var th = document.createElement('th');
        if (index === 2) th.className = 'bnetz-detail-speed-col';
        th.textContent = text;
        header.appendChild(th);
    });
    table.appendChild(header);

    measurements.forEach(function(measurement, index) {
        var speed = measurement.mbps || measurement.speed || measurement.value || 0;
        var color = 'var(--text)';
        if (minimum && speed < minimum) color = 'var(--crit)';
        else if (normal && speed < normal) color = 'var(--warn, orange)';

        var row = document.createElement('tr');
        var numberCell = document.createElement('td');
        numberCell.textContent = index + 1;
        row.appendChild(numberCell);
        var timeCell = document.createElement('td');
        timeCell.textContent = (measurement.date || '') + ' ' + (measurement.time || '');
        row.appendChild(timeCell);
        var speedCell = document.createElement('td');
        speedCell.className = 'bnetz-detail-speed-col';
        speedCell.style.color = color;
        speedCell.textContent = (typeof speed === 'number' ? speed.toFixed(1) : speed) + ' Mbit/s';
        row.appendChild(speedCell);
        table.appendChild(row);
    });
    section.appendChild(table);
    return section;
}

function buildBnetzDetail(m) {
    var measurements = m.measurements || {};
    var download = measurements.download || [];
    var upload = measurements.upload || [];
    var grid = document.createElement('div');
    grid.className = 'bnetz-detail-grid';
    if (download.length > 0) {
        grid.appendChild(_bnetzMeasurementSection(
            T.download || 'Download',
            download,
            m.download_min_tariff,
            m.download_normal_tariff
        ));
    }
    if (upload.length > 0) {
        grid.appendChild(_bnetzMeasurementSection(
            T.upload || 'Upload',
            upload,
            m.upload_min_tariff,
            m.upload_normal_tariff
        ));
    }
    return grid;
}

/* ── BNetzA Breitbandmessung ── */
function _showBnetzEmpty(empty) {
    DOCSightEmptyState.show(empty, {
        icon: 'upload',
        title: T.bnetz_no_measurements || 'No measurements uploaded yet',
        text: T.bnetz_empty_text,
        action: {
            label: T.bnetz_upload || 'Upload',
            onClick: function() { document.getElementById('bnetz-file-input').click(); }
        },
        glossary: 'bnetza'
    });
}

function loadBnetzData() {
    var loading = document.getElementById('bnetz-loading');
    var empty = document.getElementById('bnetz-empty');
    var card = document.getElementById('bnetz-table-card');
    var tbody = document.getElementById('bnetz-tbody');
    if (!loading) return;
    loading.hidden = false;
    DOCSightEmptyState.hide(empty);
    card.hidden = true;
    fetch(docsightUrl('/api/bnetz/measurements')).then(function(r) { return r.json(); }).then(function(data) {
        loading.hidden = true;
        if (!data || data.length === 0) {
            _showBnetzEmpty(empty);
            return;
        }
        card.hidden = false;
        tbody.replaceChildren();
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
            tr.className = hasMeasurements ? 'bnetz-row-expandable' : '';
            tr.setAttribute('data-bnetz-idx', idx);
            // Every row expands on mobile (secondary values); rows with
            // individual measurements also expand on desktop.
            tr.onclick = function() { toggleBnetzDetail(idx); };

            var dateCell = _bnetzCell(T.bnetz_date || 'Date', '');
            var expandButton = document.createElement('button');
            expandButton.type = 'button';
            expandButton.className = 'bnetz-expand-btn' + (hasMeasurements ? '' : ' bnetz-expand-mobile-only');
            expandButton.id = 'bnetz-arrow-' + idx;
            expandButton.setAttribute('aria-label', T.expand || 'Expand');
            expandButton.setAttribute('aria-expanded', 'false');
            if (hasMeasurements) expandButton.setAttribute('aria-controls', 'bnetz-detail-' + idx);
            expandButton.appendChild(_bnetzIcon('chevron-right'));
            dateCell.appendChild(expandButton);
            dateCell.appendChild(document.createTextNode(' '));
            dateCell.appendChild(document.createTextNode(m.date ? formatDocsightTime(m.date, 'date') : ''));
            tr.appendChild(dateCell);
            tr.appendChild(_bnetzSecondary(_bnetzCell(T.bnetz_provider || 'Provider', m.provider || '-')));
            tr.appendChild(_bnetzSecondary(_bnetzCell(T.bnetz_download_target || 'Download target', m.download_max_tariff ? Math.round(m.download_max_tariff) + ' Mbit/s' : '-')));
            tr.appendChild(_bnetzCell(T.bnetz_download_actual || 'Download measured', Math.round(m.download_measured_avg || 0) + ' Mbit/s' + (dlPct ? ' (' + dlPct + '%)' : '')));
            tr.appendChild(_bnetzSecondary(_bnetzCell(T.bnetz_upload_target || 'Upload target', m.upload_max_tariff ? Math.round(m.upload_max_tariff) + ' Mbit/s' : '-')));
            tr.appendChild(_bnetzCell(T.bnetz_upload_actual || 'Upload measured', Math.round(m.upload_measured_avg || 0) + ' Mbit/s' + (ulPct ? ' (' + ulPct + '%)' : '')));

            var verdictCell = _bnetzCell(T.bnetz_verdict || 'Verdict', '');
            verdictCell.className = 'bnetz-verdict ' + verdictClass;
            verdictCell.title = verdictText;
            verdictCell.appendChild(_bnetzIcon(hasDeviation ? 'triangle-alert' : 'circle-check'));
            var verdictLabel = document.createElement('span');
            verdictLabel.className = 'bnetz-verdict-text';
            verdictLabel.textContent = verdictText;
            verdictCell.appendChild(verdictLabel);
            tr.appendChild(verdictCell);

            var actionsCell = _bnetzCell(T.actions || 'Actions', '');
            actionsCell.className = 'bnetz-actions-cell bnetz-secondary-cell';
            actionsCell.addEventListener('click', function(event) { event.stopPropagation(); });
            if (hasDeviation) {
                actionsCell.appendChild(_bnetzActionButton(
                    'bnetz-action-btn',
                    T.bnetz_generate_complaint || 'Generate complaint',
                    'file-pen',
                    function() { generateBnetzComplaint(m.id); }
                ));
            } else {
                actionsCell.appendChild(_bnetzActionPlaceholder());
            }
            if (m.source !== 'csv_import') {
                var pdfLink = document.createElement('a');
                pdfLink.href = docsightUrl('/api/bnetz/pdf/' + encodeURIComponent(String(m.id)));
                pdfLink.className = 'bnetz-action-btn';
                pdfLink.title = 'PDF';
                pdfLink.setAttribute('aria-label', 'PDF');
                pdfLink.appendChild(_bnetzIcon('file-down'));
                actionsCell.appendChild(pdfLink);
            } else {
                actionsCell.appendChild(_bnetzActionPlaceholder());
            }
            actionsCell.appendChild(_bnetzActionButton(
                'bnetz-action-btn bnetz-action-delete',
                T.delete_incident || 'Delete',
                'trash-2',
                function() { deleteBnetzFromView(m.id); }
            ));
            tr.appendChild(actionsCell);
            tbody.appendChild(tr);
            // Detail expand row (hidden by default)
            if (hasMeasurements) {
                var detailTr = document.createElement('tr');
                detailTr.id = 'bnetz-detail-' + idx;
                detailTr.style.display = 'none';
                var detailTd = document.createElement('td');
                detailTd.colSpan = 8;
                detailTd.className = 'bnetz-detail-cell';
                detailTd.appendChild(buildBnetzDetail(m));
                detailTr.appendChild(detailTd);
                tbody.appendChild(detailTr);
            }
        });
        lucide.createIcons();
    }).catch(function() {
        loading.hidden = true;
        DOCSightEmptyState.showError(empty, {retry: loadBnetzData});
    });

    /* Fetch watcher status for the banner */
    var watcherBanner = document.getElementById('bnetz-watcher-status');
    var watcherText = document.getElementById('bnetz-watcher-text');
    if (watcherBanner) {
        fetch(docsightUrl('/api/collectors/status')).then(function(r) { return r.json(); }).then(function(collectors) {
            var watcher = null;
            for (var i = 0; i < collectors.length; i++) {
                if (collectors[i].name === 'bnetz_watcher') { watcher = collectors[i]; break; }
            }
            if (watcher && watcher.enabled) {
                watcherBanner.hidden = false;
                var parts = [(T.bnetz_watcher_active || 'File watcher active')];
                if (watcher.watch_dir) parts.push((T.bnetz_watcher_watching || 'Watching {dir}').replace('{dir}', watcher.watch_dir));
                if (watcher.last_import_count > 0) parts.push((T.bnetz_watcher_last_import || '{count} file(s) imported').replace('{count}', watcher.last_import_count));
                if (watcher.next_poll_in > 0) parts.push((T.bnetz_watcher_next_check || 'Next check in {min}min').replace('{min}', Math.round(watcher.next_poll_in / 60)));
                watcherText.textContent = parts.join(' · ');
                lucide.createIcons();
            } else {
                watcherBanner.hidden = true;
            }
        }).catch(function() { watcherBanner.hidden = true; });
    }
}

function toggleBnetzDetail(idx) {
    var summary = document.querySelector('#bnetz-tbody tr[data-bnetz-idx="' + idx + '"]');
    var row = document.getElementById('bnetz-detail-' + idx);
    var arrow = document.getElementById('bnetz-arrow-' + idx);
    if (!summary) return;
    var open = !summary.classList.contains('bnetz-row-open');
    summary.classList.toggle('bnetz-row-open', open);
    if (row) row.style.display = open ? 'table-row' : 'none';
    if (arrow) {
        arrow.classList.toggle('open', open);
        arrow.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
}

function uploadBnetzFromView() {
    var input = document.getElementById('bnetz-file-input');
    if (!input.files || !input.files[0]) return;
    var fd = new FormData();
    fd.append('file', input.files[0]);
    fetch(docsightUrl('/api/bnetz/upload'), {method: 'POST', body: fd})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            input.value = '';
            if (data.error) { showToast(data.error, 'error'); return; }
            loadBnetzData();
        })
        .catch(function(e) { showToast((T.bnetz_upload_failed || 'Upload failed') + ': ' + e, 'error'); input.value = ''; });
}

function deleteBnetzFromView(id) {
    docsightConfirm({
        title: T.delete || 'Delete',
        message: T.bnetz_delete_confirm || 'Delete this measurement?',
        confirmText: T.delete || 'Delete',
        cancelText: T.cancel || 'Cancel',
        danger: true
    }).then(function(confirmed) {
        if (!confirmed) return null;
        return fetch(docsightUrl('/api/bnetz/' + id), {method: 'DELETE'});
    })
        .then(function(r) { if (r) loadBnetzData(); });
}
