/* ═══ DOCSight Speedtest Module ═══ */

var _speedtestRawData = [];
var _speedtestAllData = [];
var _speedtestVisible = 50;
var _speedtestSortCol = 'timestamp';
var _speedtestSortDir = 'desc';
var _signalCache = {};

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
                noData.classList.remove('speedtest-empty-error');
                noData.style.display = '';
                return;
            }
            _speedtestRawData = data;
            filterSpeedtestData();
        })
        .catch(function() {
            if (loading) loading.style.display = 'none';
            noData.classList.add('speedtest-empty-error');
            noData.setAttribute('data-error', T.network_error || 'Error');
            noData.style.display = '';
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
            noData.classList.remove('speedtest-empty-error');
            noData.style.display = '';
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
        if (r.smart_capture) tr.className = 'st-row-sc';
        var serverCell = r.server_id
            ? '<td title="' + escapeHtml(r.server_name || '') + '">#' + r.server_id + '</td>'
            : '<td></td>';
        var scBadge = r.smart_capture
            ? '<td class="st-sc-col"><span class="sc-badge">' + escapeHtml(T.sc_badge_label || 'Smart Capture') + '</span></td>'
            : '<td class="st-sc-col"></td>';
        tr.innerHTML = '<td class="st-expand-col"><button class="st-expand-btn" data-id="' + r.id + '" onclick="toggleSpeedtestSignal(this)"><i data-lucide="chevron-right"></i></button></td>'
            + '<td>' + escapeHtml(formatSpeedtestTimestamp(r.timestamp)) + '</td>'
            + serverCell
            + '<td><strong' + dlClass + '>' + escapeHtml(r.download_human || (r.download_mbps + ' Mbps')) + '</strong></td>'
            + '<td><strong' + ulClass + '>' + escapeHtml(r.upload_human || (r.upload_mbps + ' Mbps')) + '</strong></td>'
            + '<td' + pingClass + '>' + escapeHtml(String(r.ping_ms)) + ' ms</td>'
            + '<td' + jitterClass + '>' + escapeHtml(String(r.jitter_ms)) + ' ms</td>'
            + '<td>' + (r.packet_loss_pct > 0 ? '<span class="val-warn">' + r.packet_loss_pct + '%</span>' : '0%') + '</td>'
            + scBadge;
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
    var items = [
        {label: T.signal_health || 'Health', value: healthLabel, badge: healthClass},
        {label: T.signal_ds_power || 'DS Power', value: data.ds_power_min + ' / ' + data.ds_power_avg + ' / ' + data.ds_power_max + ' dBmV'},
        {label: T.signal_ds_snr || 'DS SNR', value: data.ds_snr_min + ' / ' + data.ds_snr_avg + ' dB'},
        {label: T.signal_us_power || 'US Power', value: data.us_power_min + ' / ' + data.us_power_avg + ' / ' + data.us_power_max + ' dBmV'},
        {label: T.signal_errors || 'Errors', value: (data.ds_correctable_errors || 0).toLocaleString() + ' ' + (T.signal_corr || 'corr.') + ' / ' + (data.ds_uncorrectable_errors || 0).toLocaleString() + ' ' + (T.signal_uncorr || 'uncorr.')},
        {label: (T.signal_ds_channels || 'DS') + ' / ' + (T.signal_us_channels || 'US'), value: (data.ds_total || 0) + ' / ' + (data.us_total || 0)}
    ];
    items.forEach(function(item) {
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
    snapVal.style.fontSize = '0.85em';
    snapVal.style.color = 'var(--muted)';
    snapVal.textContent = data.snapshot_timestamp || '';
    snapDiv.appendChild(snapVal);
    container.appendChild(snapDiv);
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
    // Create detail row and populate (from cache or fetch)
    btn.classList.add('open');
    var newRow = document.createElement('tr');
    newRow.className = 'st-signal-row';
    var cols = parentRow.children.length;
    var td = document.createElement('td');
    td.colSpan = cols;
    td.textContent = '...';
    var detailDiv = document.createElement('div');
    detailDiv.className = 'st-signal-detail';
    var loadSpan = document.createElement('span');
    loadSpan.className = 'st-sig-no-data';
    loadSpan.style.textAlign = 'center';
    loadSpan.textContent = '...';
    detailDiv.appendChild(loadSpan);
    td.textContent = '';
    td.appendChild(detailDiv);
    newRow.appendChild(td);
    parentRow.after(newRow);

    var container = newRow.querySelector('.st-signal-detail');
    if (_signalCache[id]) {
        _renderSignalDetail(_signalCache[id], container);
    } else {
        fetch('/api/speedtest/' + id + '/signal')
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
    // Padding (reduced on narrow screens)
    var mobile = w < 500;
    var padL = mobile ? 40 : 60, padR = mobile ? 30 : 60, padT = 20, padB = 30;
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
    var gridColor = cs.getPropertyValue('--border-subtle').trim() || 'rgba(255,255,255,0.07)';
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    var monoFont = cs.getPropertyValue('--font-mono').trim() || 'monospace';
    ctx.font = '11px ' + monoFont;
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
    ctx.font = '10px ' + monoFont;
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
    ctx.font = '10px ' + monoFont;
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
    // Hover / touch interaction
    var tooltip = document.getElementById('speedtest-chart-tooltip');
    // Move tooltip to body so it's never clipped
    if (tooltip.parentElement !== document.body) document.body.appendChild(tooltip);
    tooltip.style.position = 'fixed';
    function showTooltipAt(clientX, clientY) {
        var rect = canvas.getBoundingClientRect();
        var scaleX = w / rect.width;
        var scaleY = h / rect.height;
        var mx = (clientX - rect.left) * scaleX;
        var my = (clientY - rect.top) * scaleY;
        if (mx < padL || mx > w - padR || my < padT || my > padT + ch) {
            tooltip.style.display = 'none'; return;
        }
        var ratio = (mx - padL) / cw;
        var idx = Math.round(ratio * (data.length - 1));
        if (idx < 0) idx = 0;
        if (idx >= data.length) idx = data.length - 1;
        tooltip.style.display = 'block';
        tooltip.textContent = '';
        var strong = document.createElement('strong');
        strong.textContent = formatSpeedtestTimestamp(data[idx].timestamp);
        tooltip.appendChild(strong);
        var lines = [
            {color: '#a855f7', sym: '\u25BC', label: T.speedtest_dl || 'DL', val: dls[idx].toFixed(2) + ' Mbps'},
            {color: '#22c55e', sym: '\u25B2', label: T.speedtest_ul || 'UL', val: uls[idx].toFixed(2) + ' Mbps'},
            {color: '#f59e0b', sym: '\u25CF', label: T.speedtest_ping || 'Ping', val: pings[idx].toFixed(1) + ' ms'}
        ];
        lines.forEach(function(line) {
            tooltip.appendChild(document.createElement('br'));
            var span = document.createElement('span');
            span.style.color = line.color;
            span.textContent = line.sym;
            tooltip.appendChild(span);
            tooltip.appendChild(document.createTextNode(' ' + line.label + ': ' + line.val));
        });
        // Position with edge detection
        var tipW = tooltip.offsetWidth || 160;
        var leftPos = clientX + 14;
        if (leftPos + tipW > window.innerWidth - 8) {
            leftPos = clientX - tipW - 14;
        }
        tooltip.style.left = leftPos + 'px';
        tooltip.style.top = (clientY - 10) + 'px';
    }
    function onMouseMove(e) { showTooltipAt(e.clientX, e.clientY); }
    function onMouseLeave() { tooltip.style.display = 'none'; }
    function onTouchMove(e) {
        if (e.touches.length === 1) {
            e.preventDefault();
            var touch = e.touches[0];
            showTooltipAt(touch.clientX, touch.clientY);
        }
    }
    function onTouchEnd() { tooltip.style.display = 'none'; }
    // Clean up old handlers
    if (canvas._chartMoveHandler) canvas.removeEventListener('mousemove', canvas._chartMoveHandler);
    if (canvas._chartLeaveHandler) canvas.removeEventListener('mouseleave', canvas._chartLeaveHandler);
    if (canvas._chartTouchMoveHandler) canvas.removeEventListener('touchmove', canvas._chartTouchMoveHandler);
    if (canvas._chartTouchEndHandler) canvas.removeEventListener('touchend', canvas._chartTouchEndHandler);
    canvas._chartMoveHandler = onMouseMove;
    canvas._chartLeaveHandler = onMouseLeave;
    canvas._chartTouchMoveHandler = onTouchMove;
    canvas._chartTouchEndHandler = onTouchEnd;
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseleave', onMouseLeave);
    canvas.addEventListener('touchmove', onTouchMove, {passive: false});
    canvas.addEventListener('touchend', onTouchEnd);
}

// Resize handler for speedtest chart only
window.addEventListener('resize', function() {
    if (_speedtestAllData.length >= 2) renderSpeedtestChart();
});

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
    fetch('/api/speedtest?count=1')
        .then(function(r) { return r.json(); })
        .then(function(latest) {
            var lastId = (latest && latest.length > 0) ? latest[0].id : 0;
            return fetch('/api/speedtest/run', {method: 'POST'})
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
                            fetch('/api/speedtest?count=1')
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
