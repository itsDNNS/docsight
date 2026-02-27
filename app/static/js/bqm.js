/* ═══ DOCSight BQM (Breitbandmessung Quality Monitor) ═══ */
/* Calendar navigation, live refresh, slideshow, graph display, and image import */
/* Note: innerHTML usage is safe here — all data is from trusted server responses or internal state */

/* ── BQM State ── */
var bqmDate = todayStr();
var _bqmAvailableDates = new Set();
var _bqmCalYear = new Date().getFullYear();
var _bqmCalMonth = new Date().getMonth(); // 0-based
var _bqmDatesLoaded = false;
var _bqmLiveTimer = null;
var _BQM_LIVE_INTERVAL = 300000; // 5 min
var _bqmSlideshow = { playing: false, speed: 2000, range: [], currentIdx: 0, timer: null };
var _bqmRangeStart = null;
var _bqmRangeEnd = null;

/* ── BQM Calendar Navigation ── */
function fetchBqmDates(cb) {
    fetch('/api/bqm/dates').then(function(r) { return r.json(); }).then(function(dates) {
        _bqmAvailableDates = new Set(dates);
        _bqmDatesLoaded = true;
        if (cb) cb();
    }).catch(function() { _bqmDatesLoaded = true; if (cb) cb(); });
}

function renderBqmCalendar(year, month) {
    var grid = document.getElementById('bqm-calendar-grid');
    var label = document.getElementById('bqm-month-label');
    if (!grid || !label) return;
    var monthNames = T.month_names || ['January','February','March','April','May','June','July','August','September','October','November','December'];
    label.textContent = monthNames[month] + ' ' + year;
    grid.innerHTML = '';
    var firstDay = new Date(year, month, 1);
    // Monday-start: 0=Mon..6=Sun
    var startDow = (firstDay.getDay() + 6) % 7;
    var daysInMonth = new Date(year, month + 1, 0).getDate();
    var today = todayStr();
    // Fill leading empty cells
    for (var e = 0; e < startDow; e++) {
        var empty = document.createElement('div');
        empty.className = 'bqm-day other-month';
        grid.appendChild(empty);
    }
    for (var d = 1; d <= daysInMonth; d++) {
        var dateStr = year + '-' + pad(month + 1) + '-' + pad(d);
        var cell = document.createElement('div');
        cell.className = 'bqm-day';
        cell.textContent = d;
        cell.setAttribute('data-date', dateStr);
        if (_bqmAvailableDates.has(dateStr)) cell.classList.add('has-data');
        if (dateStr === today) cell.classList.add('today');
        if (dateStr === bqmDate) cell.classList.add('selected');
        // Range highlighting
        if (_bqmRangeStart && _bqmRangeEnd) {
            if (dateStr === _bqmRangeStart) cell.classList.add('range-start');
            else if (dateStr === _bqmRangeEnd) cell.classList.add('range-end');
            else if (dateStr > _bqmRangeStart && dateStr < _bqmRangeEnd) cell.classList.add('in-range');
        }
        cell.addEventListener('click', (function(ds, ev) {
            return function(e) {
                if (!_bqmAvailableDates.has(ds)) return;
                if (e.shiftKey && bqmDate) {
                    // Range selection
                    var a = bqmDate < ds ? bqmDate : ds;
                    var b = bqmDate < ds ? ds : bqmDate;
                    _bqmRangeStart = a;
                    _bqmRangeEnd = b;
                    updateBqmRangeLabel();
                    renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
                } else {
                    _bqmRangeStart = null;
                    _bqmRangeEnd = null;
                    selectBqmDate(ds);
                }
            };
        })(dateStr));
        grid.appendChild(cell);
    }
}

function selectBqmDate(date) {
    bqmDate = date;
    stopBqmSlideshow();
    renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
    if (date === todayStr()) {
        loadBqmLive();
    } else {
        hideBqmLiveBadge();
        loadBqmGraph(date);
    }
}

function bqmMonthNav(dir) {
    _bqmCalMonth += dir;
    if (_bqmCalMonth < 0) { _bqmCalMonth = 11; _bqmCalYear--; }
    if (_bqmCalMonth > 11) { _bqmCalMonth = 0; _bqmCalYear++; }
    renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
}

function initBqmCalendar() {
    // Set calendar month to match selected date
    var d = new Date(bqmDate + 'T12:00:00');
    _bqmCalYear = d.getFullYear();
    _bqmCalMonth = d.getMonth();
    fetchBqmDates(function() {
        renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
    });
}

// Quick-jump buttons
var bqmTodayBtn = document.getElementById('bqm-today-btn');
var bqmYesterdayBtn = document.getElementById('bqm-yesterday-btn');
if (bqmTodayBtn) bqmTodayBtn.addEventListener('click', function() {
    var t = todayStr();
    _bqmCalYear = new Date().getFullYear();
    _bqmCalMonth = new Date().getMonth();
    selectBqmDate(t);
});
if (bqmYesterdayBtn) bqmYesterdayBtn.addEventListener('click', function() {
    var d = new Date(); d.setDate(d.getDate() - 1);
    var yd = d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate());
    _bqmCalYear = d.getFullYear();
    _bqmCalMonth = d.getMonth();
    selectBqmDate(yd);
});

// Month nav
var bqmMonthPrev = document.getElementById('bqm-month-prev');
var bqmMonthNext = document.getElementById('bqm-month-next');
if (bqmMonthPrev) bqmMonthPrev.addEventListener('click', function() { bqmMonthNav(-1); });
if (bqmMonthNext) bqmMonthNext.addEventListener('click', function() { bqmMonthNav(1); });

/* ── BQM Live Refresh ── */
function loadBqmLive() {
    var img = document.getElementById('bqm-image');
    var noData = document.getElementById('bqm-no-data');
    var card = document.getElementById('bqm-card');
    if (!img || !noData) return;
    if (card) card.style.display = 'none';
    noData.style.display = 'none';
    fetch('/api/bqm/live').then(function(r) {
        if (!r.ok) throw new Error('Live fetch failed');
        var source = r.headers.get('X-BQM-Source') || 'cached';
        var ts = r.headers.get('X-BQM-Timestamp');
        return r.blob().then(function(blob) {
            return { blob: blob, source: source, timestamp: ts };
        });
    }).then(function(data) {
        var url = URL.createObjectURL(data.blob);
        img.onload = function() {
            if (card) card.style.display = 'block';
            URL.revokeObjectURL(url);
        };
        img.onerror = function() {
            if (card) card.style.display = 'none';
            noData.textContent = T.bqm_no_data || 'No BQM graph for this date.';
            noData.style.display = 'block';
            URL.revokeObjectURL(url);
        };
        img.src = url;
        showBqmLiveBadge(data.source, data.timestamp);
    }).catch(function() {
        // Fallback to cached
        hideBqmLiveBadge();
        loadBqmGraph(todayStr());
    });
}

function showBqmLiveBadge(source, timestamp) {
    var badge = document.getElementById('bqm-live-badge');
    var updated = document.getElementById('bqm-last-updated');
    if (badge) badge.style.display = source === 'live' ? 'inline' : 'none';
    if (updated && timestamp) {
        var d = new Date(timestamp);
        updated.textContent = (T.bqm_last_updated || 'Last updated') + ': ' + d.toLocaleTimeString();
        updated.style.display = 'inline';
    }
}

function hideBqmLiveBadge() {
    var badge = document.getElementById('bqm-live-badge');
    var updated = document.getElementById('bqm-last-updated');
    if (badge) badge.style.display = 'none';
    if (updated) updated.style.display = 'none';
}

function startBqmLiveRefresh() {
    stopBqmLiveRefresh();
    if (bqmDate === todayStr()) {
        _bqmLiveTimer = setInterval(function() {
            if (currentView !== 'bqm' || document.hidden || bqmDate !== todayStr()) return;
            loadBqmLive();
        }, _BQM_LIVE_INTERVAL);
    }
}

function stopBqmLiveRefresh() {
    if (_bqmLiveTimer) { clearInterval(_bqmLiveTimer); _bqmLiveTimer = null; }
}

/* ── BQM Slideshow ── */
function getBqmRangeDates() {
    if (!_bqmRangeStart || !_bqmRangeEnd) {
        // Use all available dates
        return Array.from(_bqmAvailableDates).sort();
    }
    return Array.from(_bqmAvailableDates).filter(function(d) {
        return d >= _bqmRangeStart && d <= _bqmRangeEnd;
    }).sort();
}

function startBqmSlideshow() {
    var dates = getBqmRangeDates();
    if (dates.length === 0) return;
    _bqmSlideshow.range = dates;
    _bqmSlideshow.currentIdx = 0;
    _bqmSlideshow.playing = true;
    updateBqmSlideshowUI();
    selectBqmSlideshowFrame();
    _bqmSlideshow.timer = setInterval(function() {
        _bqmSlideshow.currentIdx++;
        if (_bqmSlideshow.currentIdx >= _bqmSlideshow.range.length) {
            _bqmSlideshow.currentIdx = 0; // loop
        }
        selectBqmSlideshowFrame();
    }, _bqmSlideshow.speed);
}

function pauseBqmSlideshow() {
    if (_bqmSlideshow.timer) { clearInterval(_bqmSlideshow.timer); _bqmSlideshow.timer = null; }
    _bqmSlideshow.playing = false;
    updateBqmSlideshowUI();
}

function stopBqmSlideshow() {
    if (_bqmSlideshow.timer) { clearInterval(_bqmSlideshow.timer); _bqmSlideshow.timer = null; }
    _bqmSlideshow.playing = false;
    _bqmSlideshow.range = [];
    _bqmSlideshow.currentIdx = 0;
    updateBqmSlideshowUI();
}

function selectBqmSlideshowFrame() {
    var date = _bqmSlideshow.range[_bqmSlideshow.currentIdx];
    if (!date) return;
    bqmDate = date;
    // Update calendar to show the month of the current frame
    var d = new Date(date + 'T12:00:00');
    _bqmCalYear = d.getFullYear();
    _bqmCalMonth = d.getMonth();
    renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
    hideBqmLiveBadge();
    loadBqmGraph(date);
}

function updateBqmSlideshowUI() {
    var playBtn = document.getElementById('bqm-play-btn');
    var stopBtn = document.getElementById('bqm-stop-btn');
    if (!playBtn) return;
    if (_bqmSlideshow.playing) {
        // Show pause icon
        playBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><rect x="5" y="4" width="4" height="16" rx="1"/><rect x="15" y="4" width="4" height="16" rx="1"/></svg>';
        playBtn.classList.add('playing');
        playBtn.title = T.bqm_pause || 'Pause';
        if (stopBtn) stopBtn.style.display = 'inline-flex';
    } else {
        // Show play icon
        playBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><polygon points="6,4 20,12 6,20"/></svg>';
        playBtn.classList.remove('playing');
        playBtn.title = T.bqm_play || 'Play';
        if (stopBtn) stopBtn.style.display = _bqmSlideshow.range.length ? 'inline-flex' : 'none';
    }
}

function updateBqmRangeLabel() {
    var label = document.getElementById('bqm-range-label');
    if (!label) return;
    if (_bqmRangeStart && _bqmRangeEnd) {
        var count = getBqmRangeDates().length;
        label.textContent = formatDateDE(_bqmRangeStart) + ' \u2013 ' + formatDateDE(_bqmRangeEnd) + ' (' + count + ')';
    } else {
        label.textContent = '';
    }
}

// Play/Pause button
var bqmPlayBtn = document.getElementById('bqm-play-btn');
if (bqmPlayBtn) bqmPlayBtn.addEventListener('click', function() {
    if (_bqmSlideshow.playing) {
        pauseBqmSlideshow();
    } else {
        startBqmSlideshow();
    }
});

// Stop button
var bqmStopBtn = document.getElementById('bqm-stop-btn');
if (bqmStopBtn) bqmStopBtn.addEventListener('click', function() {
    stopBqmSlideshow();
});

// Speed tabs
var bqmSpeedTabs = document.querySelectorAll('#bqm-speed-tabs .trend-tab');
bqmSpeedTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _bqmSlideshow.speed = parseInt(this.getAttribute('data-speed'), 10);
        bqmSpeedTabs.forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
        if (_bqmSlideshow.playing) {
            pauseBqmSlideshow();
            startBqmSlideshow();
        }
    });
});

/* ── BQM Keyboard Shortcuts ── */
document.addEventListener('keydown', function(e) {
    // BQM slideshow keyboard shortcuts (only when BQM view active)
    if (currentView !== 'bqm') return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault();
        if (_bqmSlideshow.playing) pauseBqmSlideshow();
        else startBqmSlideshow();
    } else if (e.key === 'Escape') {
        stopBqmSlideshow();
    } else if (e.key === 'ArrowLeft') {
        if (_bqmSlideshow.playing || _bqmSlideshow.range.length) {
            e.preventDefault();
            if (_bqmSlideshow.playing) pauseBqmSlideshow();
            if (_bqmSlideshow.currentIdx > 0) {
                _bqmSlideshow.currentIdx--;
                selectBqmSlideshowFrame();
            }
        }
    } else if (e.key === 'ArrowRight') {
        if (_bqmSlideshow.playing || _bqmSlideshow.range.length) {
            e.preventDefault();
            if (_bqmSlideshow.playing) pauseBqmSlideshow();
            if (_bqmSlideshow.currentIdx < _bqmSlideshow.range.length - 1) {
                _bqmSlideshow.currentIdx++;
                selectBqmSlideshowFrame();
            }
        }
    }
});

/* ── BQM Graph ── */
function loadBqmGraph(date) {
    var img = document.getElementById('bqm-image');
    var noData = document.getElementById('bqm-no-data');
    var card = document.getElementById('bqm-card');
    if (!img || !noData) return;
    if (card) card.style.display = 'none';
    noData.style.display = 'none';
    img.onload = function() {
        if (card) card.style.display = 'block';
    };
    img.onerror = function() {
        if (card) card.style.display = 'none';
        noData.textContent = T.bqm_no_data || 'No BQM graph for this date.';
        noData.style.display = 'block';
    };
    img.src = '/api/bqm/image/' + date;
}

/* ── BQM Import ── */
var _bqmImportFiles = [];

function detectDateFromFilename(filename) {
    var base = filename.replace(/\.[^.]+$/, '');
    var m;
    // YYYY-MM-DD (with optional _HHMM or _HH-MM suffix)
    m = base.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (m) return m[1] + '-' + m[2] + '-' + m[3];
    // YYYYMMDD
    m = base.match(/(\d{4})(\d{2})(\d{2})/);
    if (m && +m[2] >= 1 && +m[2] <= 12 && +m[3] >= 1 && +m[3] <= 31)
        return m[1] + '-' + m[2] + '-' + m[3];
    // DD.MM.YYYY (German)
    m = base.match(/(\d{2})\.(\d{2})\.(\d{4})/);
    if (m) return m[3] + '-' + m[2] + '-' + m[1];
    // DD-MM-YYYY
    m = base.match(/(\d{2})-(\d{2})-(\d{4})/);
    if (m) return m[3] + '-' + m[2] + '-' + m[1];
    return '';
}

function openBqmImportModal() {
    _bqmImportFiles = [];
    var modal = document.getElementById('bqm-import-modal');
    document.getElementById('bqm-import-dropzone').style.display = '';
    document.getElementById('bqm-import-options').style.display = 'none';
    document.getElementById('bqm-import-status').style.display = 'none';
    document.getElementById('bqm-import-preview').style.display = 'none';
    document.getElementById('bqm-import-footer').style.display = 'none';
    document.getElementById('bqm-import-overwrite').checked = false;
    document.getElementById('bqm-import-offset').value = '0';
    document.getElementById('bqm-import-tbody').innerHTML = '';
    modal.classList.add('open');
}

function closeBqmImportModal() {
    document.getElementById('bqm-import-modal').classList.remove('open');
    // Revoke thumb URLs
    _bqmImportFiles.forEach(function(f) { if (f.thumbUrl) URL.revokeObjectURL(f.thumbUrl); });
    _bqmImportFiles = [];
}

function offsetDate(isoDate, days) {
    if (!isoDate || !days) return isoDate;
    var d = new Date(isoDate + 'T12:00:00');
    d.setDate(d.getDate() + days);
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate());
}

function applyBqmImportOffset() {
    var days = parseInt(document.getElementById('bqm-import-offset').value) || 0;
    _bqmImportFiles.forEach(function(entry) {
        if (entry.originalDate) {
            entry.date = offsetDate(entry.originalDate, days);
        }
    });
    renderBqmImportPreview();
}

function handleBqmImportFiles(fileList) {
    var rejected = 0;
    for (var i = 0; i < fileList.length; i++) {
        var f = fileList[i];
        // Check type by MIME or extension fallback
        var validMime = (f.type === 'image/png' || f.type === 'image/jpeg');
        var ext = f.name.toLowerCase().split('.').pop();
        var validExt = (ext === 'png' || ext === 'jpg' || ext === 'jpeg');
        if (!validMime && !validExt) { rejected++; continue; }
        var date = detectDateFromFilename(f.name);
        var thumbUrl = URL.createObjectURL(f);
        _bqmImportFiles.push({ file: f, date: date, originalDate: date, thumbUrl: thumbUrl });
    }
    if (rejected > 0) showToast(T.bqm_import_invalid || 'Only PNG and JPEG images', 'error');
    if (_bqmImportFiles.length > 0) {
        // Apply current offset to newly added files
        var days = parseInt(document.getElementById('bqm-import-offset').value) || 0;
        if (days !== 0) {
            _bqmImportFiles.forEach(function(entry) {
                if (entry.originalDate) entry.date = offsetDate(entry.originalDate, days);
            });
        }
        renderBqmImportPreview();
    }
}

function renderBqmImportPreview() {
    var tbody = document.getElementById('bqm-import-tbody');
    tbody.innerHTML = '';
    var datesDetected = 0;
    var datesMissing = 0;

    _bqmImportFiles.forEach(function(entry, idx) {
        var tr = document.createElement('tr');
        // Thumbnail
        var tdThumb = document.createElement('td');
        if (entry.thumbUrl) {
            var img = document.createElement('img');
            img.src = entry.thumbUrl;
            img.className = 'bqm-import-thumb';
            tdThumb.appendChild(img);
        }
        tr.appendChild(tdThumb);

        // Filename
        var tdName = document.createElement('td');
        var nameSpan = document.createElement('span');
        nameSpan.className = 'bqm-import-filename';
        nameSpan.textContent = entry.file.name.length > 30 ? entry.file.name.substring(0, 27) + '...' : entry.file.name;
        nameSpan.title = entry.file.name;
        tdName.appendChild(nameSpan);
        // Conflict badge
        if (entry.date && _bqmAvailableDates.has(entry.date)) {
            var badge = document.createElement('span');
            badge.className = 'bqm-import-conflict';
            badge.textContent = T.bqm_import_conflict || 'Already exists';
            tdName.appendChild(badge);
        }
        tr.appendChild(tdName);

        // Date input
        var tdDate = document.createElement('td');
        var dateInput = document.createElement('input');
        dateInput.type = 'date';
        dateInput.value = entry.date;
        dateInput.setAttribute('data-idx', idx);
        if (!entry.date) {
            dateInput.classList.add('bqm-import-date-missing');
            datesMissing++;
        } else {
            datesDetected++;
        }
        dateInput.addEventListener('change', function() {
            var i = parseInt(this.getAttribute('data-idx'));
            _bqmImportFiles[i].date = this.value;
            renderBqmImportPreview();
        });
        tdDate.appendChild(dateInput);
        tr.appendChild(tdDate);

        // Remove button
        var tdRemove = document.createElement('td');
        var removeBtn = document.createElement('button');
        removeBtn.className = 'modal-close';
        removeBtn.innerHTML = '&times;';
        removeBtn.setAttribute('data-idx', idx);
        removeBtn.addEventListener('click', function() {
            var i = parseInt(this.getAttribute('data-idx'));
            if (_bqmImportFiles[i].thumbUrl) URL.revokeObjectURL(_bqmImportFiles[i].thumbUrl);
            _bqmImportFiles.splice(i, 1);
            if (_bqmImportFiles.length === 0) {
                openBqmImportModal();
            } else {
                renderBqmImportPreview();
            }
        });
        tdRemove.appendChild(removeBtn);
        tr.appendChild(tdRemove);

        tbody.appendChild(tr);
    });

    // Status line
    var statusEl = document.getElementById('bqm-import-status');
    statusEl.textContent = datesDetected + ' dates detected' + (datesMissing > 0 ? ', ' + datesMissing + ' needs manual entry' : '');
    statusEl.style.display = 'block';

    document.getElementById('bqm-import-dropzone').style.display = 'none';
    document.getElementById('bqm-import-options').style.display = 'block';
    document.getElementById('bqm-import-preview').style.display = 'block';
    document.getElementById('bqm-import-footer').style.display = 'flex';

    // Update button text and state
    var btn = document.getElementById('bqm-import-confirm-btn');
    var allValid = _bqmImportFiles.length > 0 && datesMissing === 0;
    btn.disabled = !allValid;
    var label = (T.bqm_import_btn || 'Import {0} images').replace('{0}', _bqmImportFiles.length);
    btn.textContent = label;
}

function executeBqmImport() {
    var btn = document.getElementById('bqm-import-confirm-btn');
    btn.disabled = true;
    btn.textContent = '...';

    var fd = new FormData();
    var dates = [];
    var overwrite = document.getElementById('bqm-import-overwrite').checked;

    _bqmImportFiles.forEach(function(entry) {
        fd.append('files[]', entry.file);
        dates.push(entry.date);
    });
    fd.append('dates', dates.join(','));
    if (overwrite) fd.append('overwrite', 'true');

    fetch('/api/bqm/import', { method: 'POST', body: fd })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            // Reload BQM calendar
            fetchBqmDates(function() {
                renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
            });
            // Show result inside the modal
            showBqmImportResult(data);
        })
        .catch(function(err) {
            showToast('Import failed: ' + err.message, 'error');
            btn.disabled = false;
            var label = (T.bqm_import_btn || 'Import {0} images').replace('{0}', _bqmImportFiles.length);
            btn.textContent = label;
        });
}

function showBqmImportResult(data) {
    var total = data.imported + (data.replaced || 0);
    var tbody = document.getElementById('bqm-import-tbody');
    var status = document.getElementById('bqm-import-status');
    var preview = document.getElementById('bqm-import-preview');
    var footer = document.getElementById('bqm-import-footer');
    var options = document.getElementById('bqm-import-options');

    // Build result summary (safe: data is from trusted server response)
    var html = '<span style="color:var(--accent-purple,var(--accent));">' + total + ' imported</span>';
    if (data.replaced) html += ' (' + data.replaced + ' replaced)';
    if (data.skipped) html += ', <span style="color:#eab308;">' + data.skipped + ' skipped</span>';
    if (data.errors && data.errors.length) html += ', <span style="color:#ef4444;">' + data.errors.length + ' errors</span>';
    status.innerHTML = html;
    status.style.display = 'block';

    // Show skipped dates if any (safe: date strings from server)
    if (data.skipped_dates && data.skipped_dates.length) {
        tbody.innerHTML = '';
        var tr = document.createElement('tr');
        var td = document.createElement('td');
        td.colSpan = 4;
        td.style.cssText = 'padding:12px 8px; font-size:0.85em;';
        var datesHtml = '<div style="margin-bottom:6px;color:#eab308;font-weight:500;">Skipped (already exist):</div>';
        datesHtml += '<div style="display:flex;flex-wrap:wrap;gap:4px 10px;">';
        data.skipped_dates.forEach(function(d) {
            datesHtml += '<span style="color:var(--muted);">' + d + '</span>';
        });
        datesHtml += '</div>';
        td.innerHTML = datesHtml;
        tr.appendChild(td);
        tbody.appendChild(tr);
        preview.style.display = 'block';
    } else {
        preview.style.display = 'none';
    }

    options.style.display = 'none';

    // Replace footer with close button (safe: static HTML with translated string)
    var footerRight = footer.querySelector('div:last-child');
    footerRight.innerHTML = '<button class="btn btn-accent" onclick="closeBqmImportModal()">' + (T.close || 'Close') + '</button>';
    footer.style.display = 'flex';
}

// Drop zone event handlers
(function() {
    var zone = document.getElementById('bqm-import-dropzone');
    var input = document.getElementById('bqm-import-file-input');
    if (!zone || !input) return;

    zone.addEventListener('click', function() { input.click(); });
    input.addEventListener('change', function() {
        if (this.files.length) handleBqmImportFiles(this.files);
        this.value = '';
    });
    zone.addEventListener('dragover', function(e) {
        e.preventDefault(); e.stopPropagation();
        zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function(e) {
        e.preventDefault(); e.stopPropagation();
        zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', function(e) {
        e.preventDefault(); e.stopPropagation();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleBqmImportFiles(e.dataTransfer.files);
    });
})();
// Offset change handler
(function() {
    var offsetInput = document.getElementById('bqm-import-offset');
    if (offsetInput) {
        offsetInput.addEventListener('change', applyBqmImportOffset);
        offsetInput.addEventListener('input', applyBqmImportOffset);
    }
})();

function deleteBqmImages() {
    var totalCount = _bqmAvailableDates.size;
    if (totalCount === 0) {
        showToast(T.bqm_no_data_range || 'No BQM data in this range', 'info');
        return;
    }

    if (_bqmRangeStart && _bqmRangeEnd) {
        // Count dates in range
        var rangeDates = [];
        _bqmAvailableDates.forEach(function(d) {
            if (d >= _bqmRangeStart && d <= _bqmRangeEnd) rangeDates.push(d);
        });
        if (rangeDates.length === 0) {
            showToast(T.bqm_no_data_range || 'No BQM data in this range', 'info');
            return;
        }
        var msg = (T.bqm_delete_range || 'Delete {0} images from {1} to {2}?')
            .replace('{0}', rangeDates.length)
            .replace('{1}', _bqmRangeStart)
            .replace('{2}', _bqmRangeEnd);
        if (!confirm(msg)) return;

        fetch('/api/bqm/images', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start: _bqmRangeStart, end: _bqmRangeEnd })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var successMsg = (T.bqm_delete_success || '{0} images deleted').replace('{0}', data.deleted);
            showToast(successMsg, 'success');
            _bqmRangeStart = null;
            _bqmRangeEnd = null;
            fetchBqmDates(function() { renderBqmCalendar(_bqmCalYear, _bqmCalMonth); });
        })
        .catch(function(err) { showToast('Delete failed: ' + err.message, 'error'); });
    } else {
        // Delete all
        var msg = (T.bqm_delete_all || 'Delete all {0} BQM images?').replace('{0}', totalCount);
        if (!confirm(msg)) return;
        var confirmText = prompt(T.bqm_delete_confirm || 'Type DELETE to confirm');
        if (confirmText !== 'DELETE') return;

        fetch('/api/bqm/images', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ all: true, confirm: 'DELETE_ALL' })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var successMsg = (T.bqm_delete_success || '{0} images deleted').replace('{0}', data.deleted);
            showToast(successMsg, 'success');
            _bqmRangeStart = null;
            _bqmRangeEnd = null;
            fetchBqmDates(function() { renderBqmCalendar(_bqmCalYear, _bqmCalMonth); });
        })
        .catch(function(err) { showToast('Delete failed: ' + err.message, 'error'); });
    }
}

/* ── BQM View Init (called from switchView) ── */
function initBqmView() {
    // Cross-view date linking (Phase 4)
    if (window._selectedDateRange) {
        _bqmRangeStart = window._selectedDateRange.start;
        _bqmRangeEnd = window._selectedDateRange.end;
        updateBqmRangeLabel();
    }
    if (!_bqmDatesLoaded) {
        initBqmCalendar();
    } else {
        renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
    }
    if (bqmDate === todayStr()) {
        loadBqmLive();
        startBqmLiveRefresh();
    } else {
        loadBqmGraph(bqmDate);
    }
}
