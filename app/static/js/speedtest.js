/* ═══ DOCSight Speedtest Module ═══ */

var _speedtestRawData = [];
var _speedtestAllData = [];
var _speedtestVisible = 50;
var _speedtestSortCol = 'timestamp';
var _speedtestSortDir = 'desc';

function formatSpeedtestTimestamp(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    var dd = String(d.getDate()).padStart(2, '0');
    var mm = String(d.getMonth() + 1).padStart(2, '0');
    var yyyy = d.getFullYear();
    var hh = String(d.getHours()).padStart(2, '0');
    var min = String(d.getMinutes()).padStart(2, '0');
    return dd + '.' + mm + '.' + yyyy + ' ' + hh + ':' + min;
}

function loadSpeedtestHistory() {
    var tbody = document.getElementById('speedtest-tbody');
    var table = document.getElementById('speedtest-table');
    var noData = document.getElementById('speedtest-no-data');
    var loading = document.getElementById('speedtest-loading');
    var moreWrap = document.getElementById('speedtest-show-more');
    if (!tbody || !table || !noData) return;
    tbody.innerHTML = '';
    table.style.display = 'none';
    noData.style.display = 'none';
    if (loading) loading.style.display = '';
    if (moreWrap) moreWrap.style.display = 'none';
    _speedtestRawData = [];
    _speedtestAllData = [];
    _speedtestVisible = 50;
    fetch('/api/speedtest?count=2000')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (loading) loading.style.display = 'none';
            if (!data || data.length === 0) {
                noData.textContent = T.speedtest_no_data || 'No speedtest data.';
                noData.style.display = 'block';
                return;
            }
            _speedtestRawData = data;
            filterSpeedtestData();
        })
        .catch(function() {
            if (loading) loading.style.display = 'none';
            noData.textContent = T.network_error || 'Error';
            noData.style.display = 'block';
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
            return new Date(r.timestamp) >= cutoff;
        });
    }
    sortSpeedtestData();
    if (_speedtestAllData.length === 0) {
        if (table) table.style.display = 'none';
        if (noData) {
            noData.textContent = T.speedtest_no_data || 'No speedtest data.';
            noData.style.display = 'block';
        }
        var cc = document.getElementById('speedtest-chart-container');
        if (cc) cc.style.display = 'none';
    } else {
        if (table) table.style.display = '';
        if (noData) noData.style.display = 'none';
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
    var medianDl = computeMedian(downloads);
    var medianUl = computeMedian(uploads);
    var show = Math.min(_speedtestVisible, _speedtestAllData.length);
    for (var i = 0; i < show; i++) {
        var r = _speedtestAllData[i];
        var dlVal = parseFloat(r.download_mbps) || 0;
        var ulVal = parseFloat(r.upload_mbps) || 0;
        var pingVal = parseFloat(r.ping_ms) || 0;
        var jitterVal = parseFloat(r.jitter_ms) || 0;
        var dlClass = (medianDl > 0 && dlVal < medianDl * 0.8) ? ' class="val-bad"' : '';
        var ulClass = (medianUl > 0 && ulVal < medianUl * 0.8) ? ' class="val-bad"' : '';
        var pingClass = pingVal > 50 ? ' class="val-warn"' : '';
        var jitterClass = jitterVal > 20 ? ' class="val-warn"' : '';
        var tr = document.createElement('tr');
        var serverCell = r.server_id
            ? '<td title="' + escapeHtml(r.server_name || '') + '">#' + r.server_id + '</td>'
            : '<td></td>';
        tr.innerHTML = '<td class="st-expand-col"><button class="st-expand-btn" data-id="' + r.id + '" onclick="toggleSpeedtestSignal(this)">&#9654;</button></td>'
            + '<td>' + escapeHtml(formatSpeedtestTimestamp(r.timestamp)) + '</td>'
            + serverCell
            + '<td><strong' + dlClass + '>' + escapeHtml(r.download_human || (r.download_mbps + ' Mbps')) + '</strong></td>'
            + '<td><strong' + ulClass + '>' + escapeHtml(r.upload_human || (r.upload_mbps + ' Mbps')) + '</strong></td>'
            + '<td' + pingClass + '>' + r.ping_ms + ' ms</td>'
            + '<td' + jitterClass + '>' + r.jitter_ms + ' ms</td>'
            + '<td>' + (r.packet_loss_pct > 0 ? '<span class="val-warn">' + r.packet_loss_pct + '%</span>' : '0%') + '</td>';
        tbody.appendChild(tr);
    }
    if (moreWrap && moreBtn) {
        if (_speedtestAllData.length > _speedtestVisible) {
            moreWrap.style.display = '';
            moreBtn.textContent = (T.show_more || 'Show more') + ' (' + (_speedtestAllData.length - _speedtestVisible) + ')';
        } else {
            moreWrap.style.display = 'none';
        }
    }
}

function toggleSpeedtestSignal(btn) {
    var id = btn.getAttribute('data-id');
    var parentRow = btn.closest('tr');
    var detailRow = parentRow.nextElementSibling;
    // If detail row exists and belongs to this entry, toggle it
    if (detailRow && detailRow.classList.contains('st-signal-row')) {
        detailRow.remove();
        btn.classList.remove('open');
        return;
    }
    // Create detail row and fetch data
    btn.classList.add('open');
    var newRow = document.createElement('tr');
    newRow.className = 'st-signal-row';
    var cols = parentRow.children.length;
    var td = document.createElement('td');
    td.colSpan = cols;
    td.innerHTML = '<div class="st-signal-detail"><span class="st-sig-no-data" style="text-align:center;">...</span></div>';
    newRow.appendChild(td);
    parentRow.after(newRow);
    fetch('/api/speedtest/' + id + '/signal')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var container = newRow.querySelector('.st-signal-detail');
            if (!data.found) {
                container.innerHTML = '<span class="st-sig-no-data">' + escapeHtml(data.message || T.signal_no_snapshot) + '</span>';
                return;
            }
            var healthClass = 'health-' + (data.health === 'good' ? 'good' : data.health === 'marginal' ? 'marginal' : 'poor');
            var healthLabel = data.health === 'good' ? (T.health_good || 'Good')
                : data.health === 'marginal' ? (T.health_marginal || 'Marginal')
                : (T.health_poor || 'Poor');
            var html = '<div class="st-sig-item"><span class="st-sig-label">' + (T.signal_health || 'Health') + '</span>'
                + '<span class="st-health-badge ' + healthClass + '">' + escapeHtml(healthLabel) + '</span></div>'
                + '<div class="st-sig-item"><span class="st-sig-label">' + (T.signal_ds_power || 'DS Power') + '</span>'
                + '<span class="st-sig-value">' + data.ds_power_min + ' / ' + data.ds_power_avg + ' / ' + data.ds_power_max + ' dBmV</span></div>'
                + '<div class="st-sig-item"><span class="st-sig-label">' + (T.signal_ds_snr || 'DS SNR') + '</span>'
                + '<span class="st-sig-value">' + data.ds_snr_min + ' / ' + data.ds_snr_avg + ' dB</span></div>'
                + '<div class="st-sig-item"><span class="st-sig-label">' + (T.signal_us_power || 'US Power') + '</span>'
                + '<span class="st-sig-value">' + data.us_power_min + ' / ' + data.us_power_avg + ' / ' + data.us_power_max + ' dBmV</span></div>'
                + '<div class="st-sig-item"><span class="st-sig-label">' + (T.signal_errors || 'Errors') + '</span>'
                + '<span class="st-sig-value">' + (data.ds_correctable_errors || 0).toLocaleString() + ' ' + (T.signal_corr || 'corr.') + ' / '
                + (data.ds_uncorrectable_errors || 0).toLocaleString() + ' ' + (T.signal_uncorr || 'uncorr.') + '</span></div>'
                + '<div class="st-sig-item"><span class="st-sig-label">' + (T.signal_ds_channels || 'DS') + ' / ' + (T.signal_us_channels || 'US') + '</span>'
                + '<span class="st-sig-value">' + (data.ds_total || 0) + ' / ' + (data.us_total || 0) + '</span></div>';
            if (data.us_channels && data.us_channels.length > 0) {
                html += '<div class="st-us-mods"><span class="st-sig-label">' + (T.signal_us_modulation || 'US Modulation') + ': </span>';
                for (var c = 0; c < data.us_channels.length; c++) {
                    var ch = data.us_channels[c];
                    html += '<span>Ch' + (ch.channel_id || c) + ': ' + escapeHtml(ch.modulation || '?') + '</span>';
                }
                html += '</div>';
            }
            html += '<div class="st-sig-item"><span class="st-sig-label">' + (T.signal_snapshot_time || 'Snapshot') + '</span>'
                + '<span class="st-sig-value" style="font-size:0.85em; color:var(--muted);">' + escapeHtml(data.snapshot_timestamp || '') + '</span></div>';
            container.innerHTML = html;
        })
        .catch(function() {
            var container = newRow.querySelector('.st-signal-detail');
            if (container) container.innerHTML = '<span class="st-sig-no-data">Error loading signal data</span>';
        });
}

function renderSpeedtestChart() {
    var container = document.getElementById('speedtest-chart-container');
    var canvas = document.getElementById('speedtest-chart');
    if (!container || !canvas) return;
    // Sort data chronologically for chart (oldest first)
    var data = _speedtestAllData.slice().sort(function(a, b) {
        return new Date(a.timestamp) - new Date(b.timestamp);
    });
    if (data.length < 2) { container.style.display = 'none'; return; }
    container.style.display = '';
    var wrap = canvas.parentElement;
    var dpr = window.devicePixelRatio || 1;
    var w = wrap.clientWidth;
    var h = canvas.clientHeight || 250;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    // Padding
    var padL = 60, padR = 60, padT = 20, padB = 30;
    var cw = w - padL - padR;
    var ch = h - padT - padB;
    // Extract data arrays
    var dls = [], uls = [], pings = [], times = [];
    for (var i = 0; i < data.length; i++) {
        dls.push(parseFloat(data[i].download_mbps) || 0);
        uls.push(parseFloat(data[i].upload_mbps) || 0);
        pings.push(parseFloat(data[i].ping_ms) || 0);
        times.push(new Date(data[i].timestamp));
    }
    // Scales
    var maxSpeed = Math.max.apply(null, dls.concat(uls)) * 1.1 || 1;
    var maxPing = Math.max.apply(null, pings) * 1.1 || 1;
    var medianDl = computeMedian(dls);
    var threshold = medianDl * 0.8;
    function xPos(idx) { return padL + (idx / (data.length - 1)) * cw; }
    function ySpeed(v) { return padT + ch - (v / maxSpeed) * ch; }
    function yPing(v) { return padT + ch - (v / maxPing) * ch; }
    // Clear
    ctx.clearRect(0, 0, w, h);
    // Background zones (green/red tint per segment)
    for (var i = 0; i < data.length - 1; i++) {
        var x1 = xPos(i), x2 = xPos(i + 1);
        var isHealthy = dls[i] >= threshold && dls[i + 1] >= threshold;
        ctx.fillStyle = isHealthy ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)';
        ctx.fillRect(x1, padT, x2 - x1, ch);
    }
    // Grid lines + left Y axis labels (speed)
    var cs = getComputedStyle(document.documentElement);
    var mutedColor = cs.getPropertyValue('--muted').trim() || '#888';
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth = 1;
    ctx.font = '11px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    var gridLines = 5;
    for (var g = 0; g <= gridLines; g++) {
        var gy = padT + (g / gridLines) * ch;
        var speedVal = maxSpeed - (g / gridLines) * maxSpeed;
        var pingVal = maxPing - (g / gridLines) * maxPing;
        ctx.beginPath();
        ctx.moveTo(padL, gy);
        ctx.lineTo(w - padR, gy);
        ctx.stroke();
        ctx.fillStyle = mutedColor;
        ctx.textAlign = 'right';
        ctx.fillText(speedVal.toFixed(0), padL - 6, gy);
        ctx.textAlign = 'left';
        ctx.fillText(pingVal.toFixed(0), w - padR + 6, gy);
    }
    ctx.fillStyle = mutedColor;
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.save();
    ctx.translate(12, padT + ch / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Mbps', 0, 0);
    ctx.restore();
    ctx.save();
    ctx.translate(w - 10, padT + ch / 2);
    ctx.rotate(Math.PI / 2);
    ctx.fillText('ms', 0, 0);
    ctx.restore();
    // X axis labels (timestamps)
    ctx.fillStyle = mutedColor;
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    var labelCount = Math.min(6, data.length);
    for (var li = 0; li < labelCount; li++) {
        var idx = Math.round(li * (data.length - 1) / (labelCount - 1));
        var t = times[idx];
        var label = String(t.getDate()).padStart(2, '0') + '.' + String(t.getMonth() + 1).padStart(2, '0') + ' ' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0');
        ctx.fillText(label, xPos(idx), padT + ch + 6);
    }
    // Threshold line (dashed red)
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = 'rgba(239,68,68,0.6)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    var threshY = ySpeed(threshold);
    ctx.moveTo(padL, threshY);
    ctx.lineTo(w - padR, threshY);
    ctx.stroke();
    ctx.setLineDash([]);
    // Helper: draw filled line with gradient (Phase 4.2)
    function drawLine(values, yFn, color, gradientColors) {
        // Filled area with gradient
        ctx.beginPath();
        ctx.moveTo(xPos(0), padT + ch);
        for (var i = 0; i < values.length; i++) {
            ctx.lineTo(xPos(i), yFn(values[i]));
        }
        ctx.lineTo(xPos(values.length - 1), padT + ch);
        ctx.closePath();
        
        // Create gradient if provided
        if (gradientColors && gradientColors.length === 2) {
            var gradient = ctx.createLinearGradient(0, padT, 0, padT + ch);
            gradient.addColorStop(0, gradientColors[0]);
            gradient.addColorStop(1, gradientColors[1]);
            ctx.fillStyle = gradient;
        } else {
            ctx.fillStyle = gradientColors;
        }
        ctx.fill();
        
        // Line with smooth curves
        ctx.beginPath();
        for (var i = 0; i < values.length; i++) {
            if (i === 0) {
                ctx.moveTo(xPos(i), yFn(values[i]));
            } else {
                // Smooth curve approximation using quadratic curves
                var prevX = xPos(i - 1);
                var prevY = yFn(values[i - 1]);
                var currX = xPos(i);
                var currY = yFn(values[i]);
                var cpX = (prevX + currX) / 2;
                var cpY = (prevY + currY) / 2;
                ctx.quadraticCurveTo(prevX, prevY, cpX, cpY);
                if (i === values.length - 1) {
                    ctx.lineTo(currX, currY);
                }
            }
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.stroke();
    }
    
    // Phase 4.2: Purple gradient for download, green for upload, amber line for ping
    drawLine(uls, ySpeed, '#22c55e', ['rgba(34,197,94,0.3)', 'rgba(34,197,94,0)']);
    drawLine(dls, ySpeed, '#a855f7', ['rgba(168,85,247,0.3)', 'rgba(168,85,247,0)']);
    drawLine(pings, yPing, '#f59e0b', 'rgba(245,158,11,0.10)');
    // Hover interaction
    var tooltip = document.getElementById('speedtest-chart-tooltip');
    // Move tooltip to body so it's never clipped
    if (tooltip.parentElement !== document.body) document.body.appendChild(tooltip);
    tooltip.style.position = 'fixed';
    function onMouseMove(e) {
        var rect = canvas.getBoundingClientRect();
        var scaleX = w / rect.width;
        var scaleY = h / rect.height;
        var mx = (e.clientX - rect.left) * scaleX;
        var my = (e.clientY - rect.top) * scaleY;
        if (mx < padL || mx > w - padR || my < padT || my > padT + ch) {
            tooltip.style.display = 'none'; return;
        }
        var ratio = (mx - padL) / cw;
        var idx = Math.round(ratio * (data.length - 1));
        if (idx < 0) idx = 0;
        if (idx >= data.length) idx = data.length - 1;
        tooltip.style.display = 'block';
        tooltip.innerHTML = '<strong>' + formatSpeedtestTimestamp(data[idx].timestamp) + '</strong><br>'
            + '<span style="color:#a855f7">&#9660;</span> DL: ' + dls[idx].toFixed(2) + ' Mbps<br>'
            + '<span style="color:#22c55e">&#9650;</span> UL: ' + uls[idx].toFixed(2) + ' Mbps<br>'
            + '<span style="color:#f59e0b">&#9679;</span> Ping: ' + pings[idx].toFixed(1) + ' ms';
        tooltip.style.left = (e.clientX + 14) + 'px';
        tooltip.style.top = (e.clientY - 10) + 'px';
    }
    function onMouseLeave() { tooltip.style.display = 'none'; }
    if (canvas._chartMoveHandler) canvas.removeEventListener('mousemove', canvas._chartMoveHandler);
    if (canvas._chartLeaveHandler) canvas.removeEventListener('mouseleave', canvas._chartLeaveHandler);
    canvas._chartMoveHandler = onMouseMove;
    canvas._chartLeaveHandler = onMouseLeave;
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseleave', onMouseLeave);
}

// Resize handler for speedtest chart only
window.addEventListener('resize', function() {
    if (_speedtestAllData.length >= 2) renderSpeedtestChart();
});

function showMoreSpeedtest() {
    _speedtestVisible += 50;
    renderSpeedtestRows();
}

(function() {
    var ths = document.querySelectorAll('#speedtest-table thead th[data-col]');
    ths.forEach(function(th) {
        th.addEventListener('click', function() {
            handleSpeedtestSort(th.getAttribute('data-col'));
        });
    });
})();
