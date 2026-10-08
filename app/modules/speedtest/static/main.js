/* ═══ DOCSight Speedtest Module ═══ */

var _speedtestRawData = [];
var _speedtestAllData = [];
var _speedtestVisible = 50;
var _speedtestSortCol = 'timestamp';
var _speedtestSortDir = 'desc';
var _signalCache = {};
var _enrichedCache = {};

window.initSpeedtestView = function() {
    if (!document.getElementById('view-speedtest')) return;
    docsightSelectSegment('speedtest-tabs', 'data-value', docsightReadViewState('speedtest').range);
    loadSpeedtestHistory();
};

/* A range tab was picked: keep it in the URL, then filter. */
function speedtestRangeSelected() {
    docsightWriteViewState('speedtest', {range: getPillValue('speedtest-tabs') || '7'});
    filterSpeedtestData();
}

function formatSpeedtestTimestamp(ts) {
    return formatDocsightTime(ts, 'datetime');
}

/* No results at all: start a test where that is possible (not in demo mode),
   otherwise point at the Speedtest Tracker settings. */
function _showSpeedtestEmpty(noData) {
    var canRun = !!document.getElementById('speedtest-run-btn');
    DOCSightEmptyState.show(noData, {
        icon: 'gauge',
        title: T.speedtest_empty_title || 'No speedtest results yet',
        text: T.speedtest_empty_desc || 'Automated tests will appear here once the schedule runs. You can also start a manual test.',
        action: canRun
            ? {label: T.run_speedtest || 'Run speedtest', onClick: runSpeedtest}
            : {label: T.gaming_speedtest_action || 'Set up Speedtest Tracker', href: docsightUrl('/settings#mod-docsight_speedtest')},
        glossary: 'speedtest'
    });
}

function loadSpeedtestHistory() {
    var tbody = document.getElementById('speedtest-tbody');
    var table = document.getElementById('speedtest-table');
    var noData = document.getElementById('speedtest-no-data');
    var loading = document.getElementById('speedtest-loading');
    var moreWrap = document.getElementById('speedtest-show-more');
    if (!tbody || !table || !noData) return;
    tbody.innerHTML = '';
    table.hidden = true;
    DOCSightEmptyState.hide(noData);
    if (loading) loading.hidden = false;
    if (moreWrap) moreWrap.hidden = true;
    _speedtestRawData = [];
    _speedtestAllData = [];
    _signalCache = {};
    _speedtestVisible = 50;
    fetch(docsightUrl('/api/speedtest?count=2000'))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (loading) loading.hidden = true;
            if (!data || data.length === 0) {
                _showSpeedtestEmpty(noData);
                return;
            }
            _speedtestRawData = data;
            filterSpeedtestData();
        })
        .catch(function() {
            if (loading) loading.hidden = true;
            DOCSightEmptyState.showError(noData, {retry: loadSpeedtestHistory});
        });
}

function filterSpeedtestData() {
    var days = getPillValue('speedtest-tabs') || '7';
    var table = document.getElementById('speedtest-table');
    var noData = document.getElementById('speedtest-no-data');
    _speedtestVisible = 50;
    if (days === 'all') {
        _speedtestAllData = _speedtestRawData.slice();
    } else {
        var cutoff = new Date(Date.now() - parseInt(days) * 86400000);
        _speedtestAllData = _speedtestRawData.filter(function(r) {
            return docsightParseTime(r.timestamp) >= cutoff;
        });
    }
    sortSpeedtestData();
    if (_speedtestAllData.length === 0) {
        if (table) table.hidden = true;
        // There are results, just none in the selected period.
        DOCSightEmptyState.show(noData, {
            icon: 'clock',
            title: T.speedtest_empty_period_title || 'No speedtests in this period',
            text: T.speedtest_empty_period_text,
            action: {
                label: T.speedtest_empty_period_action || 'Show all results',
                onClick: function() { document.querySelector('#speedtest-tabs [data-value="all"]').click(); }
            },
            glossary: 'speedtest'
        });
        var cc = document.getElementById('speedtest-chart-container');
        if (cc) cc.hidden = true;
    } else {
        if (table) table.hidden = false;
        if (noData) DOCSightEmptyState.hide(noData);
        renderSpeedtestRows();
        renderSpeedtestChart();
    }
}

function sortSpeedtestData() {
    var col = _speedtestSortCol;
    var dir = _speedtestSortDir === 'asc' ? 1 : -1;
    _speedtestAllData.sort(function(a, b) {
        var va = a[col], vb = b[col];
        if (col === 'timestamp') {
            va = new Date(va || 0).getTime();
            vb = new Date(vb || 0).getTime();
        } else if (col === 'server_name') {
            return String(va || '').localeCompare(String(vb || '')) * dir;
        } else {
            va = parseFloat(va) || 0;
            vb = parseFloat(vb) || 0;
        }
        if (va < vb) return -1 * dir;
        if (va > vb) return 1 * dir;
        return 0;
    });
}

function handleSpeedtestSort(col) {
    if (_speedtestSortCol === col) {
        _speedtestSortDir = _speedtestSortDir === 'asc' ? 'desc' : 'asc';
    } else {
        _speedtestSortCol = col;
        _speedtestSortDir = col === 'timestamp' ? 'desc' : 'asc';
    }
    var ths = document.querySelectorAll('#speedtest-table thead th');
    ths.forEach(function(th) {
        var indicator = th.querySelector('.sort-indicator');
        if (indicator) {
            if (th.getAttribute('data-col') === col) {
                indicator.textContent = _speedtestSortDir === 'asc' ? '▲' : '▼';
            } else {
                indicator.textContent = '';
            }
        }
    });
    sortSpeedtestData();
    _speedtestVisible = 50;
    renderSpeedtestRows();
    renderSpeedtestChart();
}

function computeMedian(arr) {
    if (arr.length === 0) return 0;
    var sorted = arr.slice().sort(function(a, b) { return a - b; });
    var mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/* Booked speed in Mbps from the chart container; 0 when neither config nor modem knows it. */
function _speedtestBooked(direction) {
    var container = document.getElementById('speedtest-chart-container');
    var value = container ? Number(container.getAttribute('data-booked-' + direction)) : 0;
    return Number.isFinite(value) && value > 0 ? value : 0;
}

/* Results below 80 % of the booked speed are flagged; without one, 80 % of the median. */
function _speedtestLimit(direction, values) {
    var booked = _speedtestBooked(direction);
    return (booked || computeMedian(values)) * 0.8;
}

/* One table cell; data-label names the value in the stacked mobile layout. */
function _speedtestCell(columnClass, label, html, extraClass, title) {
    return '<td class="' + columnClass + (extraClass ? ' ' + extraClass : '') + '" data-label="' + escapeHtml(label) + '"'
        + (title ? ' title="' + escapeHtml(title) + '"' : '') + '>' + html + '</td>';
}

function renderSpeedtestRows() {
    var tbody = document.getElementById('speedtest-tbody');
    var moreWrap = document.getElementById('speedtest-show-more');
    var moreBtn = document.getElementById('speedtest-more-btn');
    if (!tbody) return;
    tbody.innerHTML = '';
    var downloads = [], uploads = [];
    for (var j = 0; j < _speedtestAllData.length; j++) {
        var d = _speedtestAllData[j];
        if (d.download_mbps != null) downloads.push(parseFloat(d.download_mbps) || 0);
        if (d.upload_mbps != null) uploads.push(parseFloat(d.upload_mbps) || 0);
    }
    var dlLimit = _speedtestLimit('download', downloads);
    var ulLimit = _speedtestLimit('upload', uploads);
    var show = Math.min(_speedtestVisible, _speedtestAllData.length);
    for (var i = 0; i < show; i++) {
        var r = _speedtestAllData[i];
        var dlVal = parseFloat(r.download_mbps) || 0;
        var ulVal = parseFloat(r.upload_mbps) || 0;
        var pingVal = parseFloat(r.ping_ms) || 0;
        var jitterVal = parseFloat(r.jitter_ms) || 0;
        var dlClass = (dlLimit > 0 && dlVal < dlLimit) ? ' class="val-bad"' : '';
        var ulClass = (ulLimit > 0 && ulVal < ulLimit) ? ' class="val-bad"' : '';
        var pingClass = pingVal > 50 ? 'val-warn' : '';
        var jitterClass = jitterVal > 20 ? 'val-warn' : '';
        var tr = document.createElement('tr');
        if (r.smart_capture) tr.className = 'st-row-sc';
        var serverCell = r.server_name
            ? _speedtestCell('st-col-server', T.server || 'Server', escapeHtml(r.server_name), '', '#' + String(r.server_id || ''))
            : _speedtestCell('st-col-server', T.server || 'Server', r.server_id ? '#' + escapeHtml(String(r.server_id)) : '');
        var expandLabel = escapeHtml(T.speedtest_show_signal || 'Show signal at this time');
        var scBadge = r.smart_capture
            ? '<td class="st-sc-col"><span class="sc-badge">' + escapeHtml(T.sc_badge_label || 'Smart Capture') + '</span></td>'
            : '<td class="st-sc-col"></td>';
        tr.innerHTML = '<td class="st-expand-col dt-lead"><button class="st-expand-btn" data-id="' + r.id + '" data-action="toggleSpeedtestSignal" data-action-pass="element"'
            + ' aria-label="' + expandLabel + '" title="' + expandLabel + '" aria-expanded="false" aria-controls="st-signal-' + r.id + '">'
            + '<i data-lucide="chevron-right" aria-hidden="true"></i></button></td>'
            + _speedtestCell('st-col-time dt-primary', T.timestamp || 'Timestamp', escapeHtml(formatSpeedtestTimestamp(r.timestamp)))
            + serverCell
            + _speedtestCell('st-col-dl dt-primary dt-num', T.download || 'Download', '<strong' + dlClass + '>' + escapeHtml(r.download_human || (r.download_mbps + ' Mbps')) + '</strong>')
            + _speedtestCell('st-col-ul dt-num', T.upload || 'Upload', '<strong' + ulClass + '>' + escapeHtml(r.upload_human || (r.upload_mbps + ' Mbps')) + '</strong>')
            + _speedtestCell('st-col-ping dt-num', T.ping || 'Ping', r.ping_ms == null ? '&#8212;' : escapeHtml(String(r.ping_ms)) + ' ms', pingClass)
            + _speedtestCell('st-col-jitter dt-num', T.jitter || 'Jitter', r.jitter_ms == null ? '&#8212;' : escapeHtml(String(r.jitter_ms)) + ' ms', jitterClass)
            + _speedtestCell('st-col-loss dt-num', T.packet_loss || 'Packet Loss', r.packet_loss_pct == null ? '&#8212;' : r.packet_loss_pct > 0 ? '<span class="val-warn">' + r.packet_loss_pct + '%</span>' : '0%')
            + scBadge;
        tbody.appendChild(tr);
    }
    if (moreWrap && moreBtn) {
        if (_speedtestAllData.length > _speedtestVisible) {
            moreWrap.hidden = false;
            moreBtn.textContent = (T.show_more || 'Show more') + ' (' + (_speedtestAllData.length - _speedtestVisible) + ')';
        } else {
            moreWrap.hidden = true;
        }
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function _renderSignalDetail(data, container) {
    container.textContent = '';
    if (!data.found) {
        var noDataSpan = document.createElement('span');
        noDataSpan.className = 'st-sig-no-data';
        noDataSpan.textContent = data.message || T.signal_no_snapshot;
        container.appendChild(noDataSpan);
        return;
    }
    var healthClass = 'health-' + (data.health || 'unknown');
    var healthLabels = {good: T.health_good || 'Good', tolerated: T.health_tolerated || 'Tolerated', marginal: T.health_marginal || 'Marginal', critical: T.health_critical || 'Critical'};
    var healthLabel = healthLabels[data.health] || data.health;
    var errorParts = [];
    if (data.ds_correctable_errors != null) {
        errorParts.push(Number(data.ds_correctable_errors).toLocaleString() + ' ' + (T.signal_corr || 'corr.'));
    }
    if (data.ds_uncorrectable_errors != null) {
        errorParts.push(Number(data.ds_uncorrectable_errors).toLocaleString() + ' ' + (T.signal_uncorr || 'uncorr.'));
    }
    var items = [
        {label: T.signal_health || 'Health', value: healthLabel, badge: healthClass},
        {label: T.signal_ds_power || 'DS Power', value: data.ds_power_min + ' / ' + data.ds_power_avg + ' / ' + data.ds_power_max + ' dBmV'},
        {label: T.signal_ds_snr || 'DS SNR', value: data.ds_snr_min + ' / ' + data.ds_snr_avg + ' dB'},
        {label: T.signal_us_power || 'US Power', value: data.us_power_min + ' / ' + data.us_power_avg + ' / ' + data.us_power_max + ' dBmV'},
        {label: T.signal_errors || 'Errors', value: errorParts.length ? errorParts.join(' / ') : null},
        {label: (T.signal_ds_channels || 'DS') + ' / ' + (T.signal_us_channels || 'US'), value: (data.ds_total || 0) + ' / ' + (data.us_total || 0)}
    ];
    items.forEach(function(item) {
        if (item.value == null) return;
        var div = document.createElement('div');
        div.className = 'st-sig-item';
        var lbl = document.createElement('span');
        lbl.className = 'st-sig-label';
        lbl.textContent = item.label;
        div.appendChild(lbl);
        if (item.badge) {
            var badge = document.createElement('span');
            badge.className = 'st-health-badge ' + item.badge;
            badge.textContent = item.value;
            div.appendChild(badge);
        } else {
            var val = document.createElement('span');
            val.className = 'st-sig-value';
            val.textContent = item.value;
            div.appendChild(val);
        }
        container.appendChild(div);
    });
    if (data.us_channels && data.us_channels.length > 0) {
        var modsDiv = document.createElement('div');
        modsDiv.className = 'st-us-mods';
        var modsLabel = document.createElement('span');
        modsLabel.className = 'st-sig-label';
        modsLabel.textContent = (T.signal_us_modulation || 'US Modulation') + ': ';
        modsDiv.appendChild(modsLabel);
        for (var c = 0; c < data.us_channels.length; c++) {
            var ch = data.us_channels[c];
            var chSpan = document.createElement('span');
            chSpan.textContent = 'Ch' + (ch.channel_id || c) + ': ' + (ch.modulation || '?');
            modsDiv.appendChild(chSpan);
        }
        container.appendChild(modsDiv);
    }
    var snapDiv = document.createElement('div');
    snapDiv.className = 'st-sig-item';
    var snapLabel = document.createElement('span');
    snapLabel.className = 'st-sig-label';
    snapLabel.textContent = T.signal_snapshot_time || 'Snapshot';
    snapDiv.appendChild(snapLabel);
    var snapVal = document.createElement('span');
    snapVal.className = 'st-sig-value';
    snapVal.style.fontSize = 'max(var(--fs-min), 0.85em)';
    snapVal.style.color = 'var(--muted)';
    snapVal.textContent = data.snapshot_timestamp || '';
    snapDiv.appendChild(snapVal);
    container.appendChild(snapDiv);
}

function _hasEnrichedData(data) {
    var keys = ['isp', 'server_host', 'server_location', 'server_country', 'server_ip',
        'ping_low', 'ping_high', 'dl_latency_iqm', 'dl_latency_jitter',
        'ul_latency_iqm', 'ul_latency_jitter', 'dl_bytes', 'ul_bytes',
        'dl_elapsed_ms', 'ul_elapsed_ms', 'external_ip', 'is_vpn', 'result_url'];
    for (var i = 0; i < keys.length; i++) { if (data[keys[i]] != null) return true; }
    return false;
}

function _renderEnrichedDetail(data, container) {
    if (!_hasEnrichedData(data)) return;

    var section = document.createElement('div');
    section.className = 'st-enriched-detail';

    function addGroup(title, items) {
        var group = document.createElement('div');
        group.className = 'st-enriched-group';
        var heading = document.createElement('div');
        heading.className = 'st-enriched-heading';
        heading.textContent = title;
        group.appendChild(heading);
        var grid = document.createElement('div');
        grid.className = 'st-enriched-grid';
        items.forEach(function(item) {
            if (item.value == null) return;
            var div = document.createElement('div');
            div.className = 'st-sig-item';
            var lbl = document.createElement('span');
            lbl.className = 'st-sig-label';
            lbl.textContent = item.label;
            div.appendChild(lbl);
            if (item.href) {
                var link = document.createElement('a');
                link.href = item.href;
                link.target = '_blank';
                link.rel = 'noopener';
                link.className = 'st-sig-value st-ookla-link';
                link.textContent = item.value;
                div.appendChild(link);
            } else if (item.badge) {
                var badge = document.createElement('span');
                badge.className = 'st-health-badge ' + item.badge;
                badge.textContent = item.value;
                div.appendChild(badge);
            } else {
                var val = document.createElement('span');
                val.className = 'st-sig-value';
                val.textContent = item.value;
                div.appendChild(val);
            }
            grid.appendChild(div);
        });
        if (grid.children.length > 0) {
            group.appendChild(grid);
            section.appendChild(group);
        }
    }

    function fmtBytes(bytes) {
        if (bytes == null) return null;
        if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
        if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
        return (bytes / 1024).toFixed(0) + ' KB';
    }

    function fmtDuration(ms) {
        if (ms == null) return null;
        return (ms / 1000).toFixed(1) + 's';
    }

    // Connection
    var connItems = [
        {label: T.speedtest_detail_isp || 'ISP', value: data.isp},
        {label: T.speedtest_detail_external_ip || 'External IP', value: data.external_ip},
    ];
    if (data.is_vpn) connItems.push({label: T.speedtest_detail_vpn || 'VPN', value: 'Yes', badge: 'health-tolerated'});
    addGroup(T.speedtest_detail_connection || 'Connection', connItems);

    // Server
    var loc = [data.server_location, data.server_country].filter(Boolean).join(', ');
    addGroup(T.speedtest_detail_server || 'Server', [
        {label: T.speedtest_detail_server_location || 'Location', value: loc || null},
        {label: T.speedtest_detail_server_host || 'Host', value: data.server_host || null},
        {label: 'IP', value: data.server_ip || null},
    ]);

    // Latency
    var pingRange = (data.ping_low != null && data.ping_high != null) ? data.ping_low + ' \u2013 ' + data.ping_high + ' ms' : null;
    var dlLat = (data.dl_latency_iqm != null) ? data.dl_latency_iqm + ' / ' + (data.dl_latency_jitter != null ? data.dl_latency_jitter : '---') + ' ms' : null;
    var ulLat = (data.ul_latency_iqm != null) ? data.ul_latency_iqm + ' / ' + (data.ul_latency_jitter != null ? data.ul_latency_jitter : '---') + ' ms' : null;
    addGroup(T.speedtest_detail_latency || 'Latency Details', [
        {label: T.speedtest_detail_ping_range || 'Ping Range', value: pingRange},
        {label: T.speedtest_detail_dl_latency || 'DL Latency (IQM / Jitter)', value: dlLat},
        {label: T.speedtest_detail_ul_latency || 'UL Latency (IQM / Jitter)', value: ulLat},
    ]);

    // Transfer
    var dlDur = fmtDuration(data.dl_elapsed_ms);
    var dlTransfer = (data.dl_bytes != null) ? fmtBytes(data.dl_bytes) + (dlDur ? ' in ' + dlDur : '') : null;
    var ulDur = fmtDuration(data.ul_elapsed_ms);
    var ulTransfer = (data.ul_bytes != null) ? fmtBytes(data.ul_bytes) + (ulDur ? ' in ' + ulDur : '') : null;
    addGroup(T.speedtest_detail_transfer || 'Transfer', [
        {label: T.speedtest_detail_dl_transfer || 'Download', value: dlTransfer},
        {label: T.speedtest_detail_ul_transfer || 'Upload', value: ulTransfer},
    ]);

    // Ookla link (only allow https:// URLs)
    if (data.result_url && data.result_url.indexOf('https://') === 0) {
        addGroup(T.speedtest_detail_ookla || 'Ookla Result', [
            {label: '', value: '\u2197 ' + (T.speedtest_detail_view_ookla || 'View on Speedtest.net'), href: data.result_url},
        ]);
    }

    container.appendChild(section);
}

function toggleSpeedtestSignal(btn) {
    var id = btn.getAttribute('data-id');
    var parentRow = btn.closest('tr');
    var detailRow = parentRow.nextElementSibling;
    // If detail row exists and belongs to this entry, toggle it
    if (detailRow && detailRow.classList.contains('st-signal-row')) {
        detailRow.remove();
        btn.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
        return;
    }
    // Create detail row and populate (from cache or fetch)
    btn.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
    var newRow = document.createElement('tr');
    newRow.className = 'st-signal-row dt-detail';
    newRow.id = 'st-signal-' + id;
    var cols = parentRow.children.length;
    var td = document.createElement('td');
    td.colSpan = cols;
    var detailDiv = document.createElement('div');
    detailDiv.className = 'st-signal-detail';
    var loadSpan = document.createElement('span');
    loadSpan.className = 'st-sig-no-data';
    loadSpan.style.textAlign = 'center';
    loadSpan.textContent = '...';
    detailDiv.appendChild(loadSpan);
    td.appendChild(detailDiv);
    var enrichedDiv = document.createElement('div');
    enrichedDiv.className = 'st-enriched-wrap';
    td.appendChild(enrichedDiv);
    newRow.appendChild(td);
    parentRow.after(newRow);

    var container = newRow.querySelector('.st-signal-detail');
    if (_signalCache[id]) {
        _renderSignalDetail(_signalCache[id], container);
    } else {
        fetch(docsightUrl('/api/speedtest/' + id + '/signal'))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                _signalCache[id] = data;
                _renderSignalDetail(data, container);
            })
            .catch(function() {
                container.textContent = '';
                var errSpan = document.createElement('span');
                errSpan.className = 'st-sig-no-data';
                errSpan.textContent = T.signal_error_loading || 'Error loading signal data';
                container.appendChild(errSpan);
            });
    }

    // Fetch enriched detail
    if (_enrichedCache[id]) {
        _renderEnrichedDetail(_enrichedCache[id], enrichedDiv);
    } else {
        fetch(docsightUrl('/api/speedtest/' + id))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                _enrichedCache[id] = data;
                _renderEnrichedDetail(data, enrichedDiv);
            })
            .catch(function() {});
    }
}

/* Background tint between neighbouring results: green when both reach the limit, red otherwise. */
function _speedtestTintPlugin(limit) {
    return {hooks: {drawAxes: [function(u) {
        var xs = u.data[0], dls = u.data[1];
        var ctx = u.ctx;
        ctx.save();
        for (var i = 0; i < xs.length - 1; i++) {
            if (dls[i] == null || dls[i + 1] == null) continue;
            var x1 = u.valToPos(xs[i], 'x', true), x2 = u.valToPos(xs[i + 1], 'x', true);
            ctx.fillStyle = dls[i] >= limit && dls[i + 1] >= limit ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)';
            ctx.fillRect(x1, u.bbox.top, x2 - x1, u.bbox.height);
        }
        ctx.restore();
    }]}};
}

function renderSpeedtestChart() {
    var container = document.getElementById('speedtest-chart-container');
    if (!container || !document.getElementById('speedtest-chart')) return;
    // Sort data chronologically for chart (oldest first)
    var data = _speedtestAllData.slice().sort(function(a, b) {
        return docsightParseTime(a.timestamp) - docsightParseTime(b.timestamp);
    });
    if (data.length < 2) { container.hidden = true; return; }
    container.hidden = false;
    // Axis labels follow the range like Signal Trends; the tooltip names the full time.
    var range = getPillValue('speedtest-tabs') || '7';
    var hours = range === 'all' ? 'all' : Number(range) * 24;
    var labels = [], titles = [], times = [], dls = [], uls = [], pings = [];
    for (var i = 0; i < data.length; i++) {
        var t = docsightParseTime(data[i].timestamp);
        labels.push(docsightFormatXAxisLabel(t, hours));
        titles.push(formatSpeedtestTimestamp(data[i].timestamp));
        times.push(t.getTime() / 1000);
        dls.push(parseFloat(data[i].download_mbps) || 0);
        uls.push(parseFloat(data[i].upload_mbps) || 0);
        var ping = data[i].ping_ms == null ? NaN : Number(data[i].ping_ms);
        pings.push(Number.isFinite(ping) ? ping : null);
    }
    var limit = _speedtestLimit('download', dls);
    // The reference line marks the booked speed, or the 80 % median limit when none is known.
    var reference = _speedtestBooked('download') || limit;
    var maxSpeed = Math.max.apply(null, dls.concat(uls, [reference])) * 1.1 || 1;
    var maxPing = Math.max.apply(null, pings) * 1.1 || 1;
    var muted = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
    var pingLabel = T.speedtest_ping || 'Ping';
    renderChart('speedtest-chart', labels, [
        {label: T.speedtest_dl || 'DL', data: dls, color: '#a855f7', fill: 'rgba(168,85,247,0.12)'},
        {label: T.speedtest_ul || 'UL', data: uls, color: '#22c55e', fill: 'rgba(34,197,94,0.10)'},
        {label: pingLabel, data: pings, color: '#f59e0b', scale: 'ping'}
    ], null, [{yMin: 0, yMax: maxSpeed}, {value: reference, fill: false, lineColor: muted}], {
        times: times,
        tooltipTitles: titles,
        legend: false,
        heightRatio: 0.3,
        minHeight: 200,
        maxHeight: 280,
        scales: {ping: {range: function() { return [0, maxPing]; }}},
        axes: [{scale: 'ping', side: 1, stroke: muted, grid: {show: false}, ticks: {show: false},
            font: '12px system-ui', size: 40, gap: 4}],
        tooltipLabelCallback: function(ctx) {
            var ping = ctx.dataset.label === pingLabel;
            return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(ping ? 1 : 2) + (ping ? ' ms' : ' Mbps');
        },
        plugins: [_speedtestTintPlugin(limit)]
    });
}

function showMoreSpeedtest() {
    _speedtestVisible += 50;
    renderSpeedtestRows();
}

var _runElapsedTimer = null;

function _setRunBtnState(btn, loading) {
    if (_runElapsedTimer) { clearInterval(_runElapsedTimer); _runElapsedTimer = null; }
    if (loading) {
        btn.disabled = true;
        btn.textContent = '';
        var icon = document.createElement('i');
        icon.setAttribute('data-lucide', 'loader-2');
        icon.className = 'spin';
        btn.appendChild(icon);
        var textNode = document.createTextNode(' ' + (T.speedtest_running || 'Running...') + ' 0s');
        btn.appendChild(textNode);
        var startTime = Date.now();
        _runElapsedTimer = setInterval(function() {
            var elapsed = Math.round((Date.now() - startTime) / 1000);
            textNode.textContent = ' ' + (T.speedtest_running || 'Running...') + ' ' + elapsed + 's';
        }, 1000);
    } else {
        btn.disabled = false;
        btn.textContent = '';
        var playIcon = document.createElement('i');
        playIcon.setAttribute('data-lucide', 'play');
        btn.appendChild(playIcon);
        btn.appendChild(document.createTextNode(' ' + (T.run_speedtest || 'Run Speedtest')));
    }
    if (window.lucide) lucide.createIcons({nodes: [btn]});
}

function runSpeedtest() {
    var btn = document.getElementById('speedtest-run-btn');
    if (!btn || btn.disabled) return;
    _setRunBtnState(btn, true);

    // Fetch the current latest ID from the server (not stale cache)
    fetch(docsightUrl('/api/speedtest?count=1'))
        .then(function(r) { return r.json(); })
        .then(function(latest) {
            var lastId = (latest && latest.length > 0) ? latest[0].id : 0;
            return fetch(docsightUrl('/api/speedtest/run'), {method: 'POST'})
                .then(function(r) {
                    return r.json()
                        .catch(function() { return {error: 'Unexpected response'}; })
                        .then(function(d) { return {ok: r.ok, data: d}; });
                })
                .then(function(res) {
                    if (!res.ok) {
                        _setRunBtnState(btn, false);
                        showToast((res.data.error || 'Failed'), 'error');
                        return;
                    }
                    // Poll for the new result: wait 30s, then check every 5s
                    var attempts = 0;
                    var maxAttempts = 18; // 30s initial + 18*5s = ~2 minutes total
                    setTimeout(function() {
                        var pollInterval = setInterval(function() {
                            attempts++;
                            fetch(docsightUrl('/api/speedtest?count=1'))
                                .then(function(r) { return r.json(); })
                                .then(function(data) {
                                    if (data && data.length > 0 && data[0].id > lastId) {
                                        clearInterval(pollInterval);
                                        _setRunBtnState(btn, false);
                                        var r = data[0];
                                        showToast(
                                            (T.speedtest_complete || 'Speedtest complete') + ': ' +
                                            r.download_mbps + ' / ' + r.upload_mbps + ' Mbps, ' +
                                            r.ping_ms + ' ms',
                                            'success'
                                        );
                                        loadSpeedtestHistory();
                                    } else if (attempts >= maxAttempts) {
                                        clearInterval(pollInterval);
                                        _setRunBtnState(btn, false);
                                        showToast(T.speedtest_timeout || 'Speedtest is taking longer than expected. Refresh to check.', 'warning');
                                    }
                                })
                                .catch(function() {
                                    // Transient poll error - don't stop, just skip this attempt
                                    if (attempts >= maxAttempts) {
                                        clearInterval(pollInterval);
                                        _setRunBtnState(btn, false);
                                        showToast(T.speedtest_timeout || 'Speedtest is taking longer than expected. Refresh to check.', 'warning');
                                    }
                                });
                        }, 5000);
                    }, 30000);
                });
        })
        .catch(function() {
            _setRunBtnState(btn, false);
            showToast(T.network_error || 'Network error', 'error');
        });
}

(function() {
    var ths = document.querySelectorAll('#speedtest-table thead th[data-col]');
    ths.forEach(function(th) {
        th.addEventListener('click', function() {
            handleSpeedtestSort(th.getAttribute('data-col'));
        });
    });
})();
