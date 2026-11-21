/* ═══ DOCSight BQM (Breitbandmessung Quality Monitor) ═══ */
/* Calendar navigation, live refresh, graph display, and image import */
/* Note: innerHTML usage is safe here — all data is from trusted server responses or internal state */

/* bqm-chart.js is a separate request; if it fails, PNG graphs still load. */
if (typeof BQMChart === 'undefined') {
    var BQMChart = { render: function() {}, destroy: function() {} };
}

/* ── BQM State ── */
var bqmDate = null;
var _bqmAvailableDates = new Set();
var _bqmCsvDates = new Set();
var _bqmPngDates = new Set();
var _bqmCalYear = new Date().getFullYear();
var _bqmCalMonth = new Date().getMonth(); // 0-based
var _bqmDatesLoaded = false;
var _bqmLiveTimer = null;
var _BQM_LIVE_INTERVAL = 900000; // 15 min
var _BQM_LIVE_JITTER = 120000; // 0-120s random offset
var _bqmRangeStart = null;
var _bqmRangeEnd = null;
var _bqmViewMode = 'png';

/* ── BQM Calendar Navigation ── */
function fetchBqmDates(cb) {
    fetch(docsightUrl('/api/bqm/data/dates')).then(function(r) { return r.json(); }).then(function(data) {
        var csvDates = data.csv_dates || [];
        var pngDates = data.png_dates || [];
        _bqmCsvDates = new Set(csvDates);
        _bqmPngDates = new Set(pngDates);
        _bqmAvailableDates = new Set(csvDates.concat(pngDates));
        _bqmDatesLoaded = true;
        updateBqmQuickButtons();
        if (cb) cb();
    }).catch(function() { _bqmDatesLoaded = true; if (cb) cb(); });
}

function updateBqmQuickButtons() {
    var today = todayStr();
    var selected = null;
    if (_bqmRangeStart && _bqmRangeEnd && _bqmRangeStart !== _bqmRangeEnd) {
        if (_bqmRangeEnd === today) {
            if (_bqmRangeStart === offsetDate(today, -6)) selected = '7d';
            else if (_bqmRangeStart === offsetDate(today, -29)) selected = '30d';
        }
    } else {
        var date = _bqmRangeStart || bqmDate;
        if (date === today) selected = 'today';
        else if (date === offsetDate(today, -1)) selected = 'yesterday';
    }
    var quickRange = document.getElementById('bqm-quick-range');
    quickRange.hidden = _bqmCsvDates.size === 0;
    syncSegments(quickRange, function(btn) { return btn.id === 'bqm-' + selected + '-btn'; });
}

function bqmScreenReaderText(text) {
    var span = document.createElement('span');
    span.className = 'sr-only';
    span.textContent = text;
    return span;
}

function renderBqmCalendar(year, month) {
    updateBqmQuickButtons();
    var grid = document.getElementById('bqm-calendar-grid');
    var label = document.getElementById('bqm-month-label');
    var monthNames = T.month_names || ['January','February','March','April','May','June','July','August','September','October','November','December'];
    label.textContent = monthNames[month] + ' ' + year;
    grid.replaceChildren();
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
        var cell = document.createElement('button');
        cell.type = 'button';
        cell.className = 'bqm-day';
        cell.setAttribute('data-date', dateStr);
        // The visible day stays part of the name; month, year and data kind are read out around it.
        var status = '';
        if (_bqmAvailableDates.has(dateStr)) {
            cell.classList.add('has-data');
            if (_bqmCsvDates.has(dateStr)) {
                cell.classList.add('has-csv');
                status = 'CSV';
            } else if (_bqmPngDates.has(dateStr)) {
                cell.classList.add('has-png');
                status = T.bqm_cached_png;
            }
        }
        cell.appendChild(bqmScreenReaderText(monthNames[month] + ' '));
        cell.appendChild(document.createTextNode(String(d)));
        cell.appendChild(bqmScreenReaderText(' ' + year + (status ? ', ' + status : '')));
        if (!_bqmAvailableDates.has(dateStr)) {
            cell.disabled = true;
        }
        if (dateStr === today) cell.classList.add('today');
        if (dateStr === bqmDate) {
            cell.classList.add('selected');
            cell.setAttribute('aria-current', 'date');
        }
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
                    bqmDate = b;
                    stopBqmLiveRefresh();
                    updateBqmRangeLabel();
                    renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
                    loadBqmRangeChart(a, b);
                } else {
                    selectBqmDate(ds);
                }
            };
        })(dateStr));
        grid.appendChild(cell);
    }
}

function setBqmViewMode(mode) {
    _bqmViewMode = mode;
    var chart = document.getElementById('bqm-chart-container');
    var imageWrap = document.getElementById('bqm-image-wrap');
    var toggleUplot = document.getElementById('bqm-toggle-uplot');
    var togglePng = document.getElementById('bqm-toggle-png');
    chart.hidden = mode !== 'chart';
    imageWrap.hidden = mode === 'chart';
    syncSegments('bqm-view-toggle', function(option) {
        return option === toggleUplot ? mode === 'chart' : mode === 'png';
    });
}

function updateBqmViewToggle(date) {
    document.getElementById('bqm-view-toggle').hidden = !(_bqmCsvDates.has(date) && _bqmPngDates.has(date));
}

function showBqmCard() {
    document.getElementById('bqm-card').hidden = false;
    DOCSightEmptyState.hide(document.getElementById('bqm-no-data'));
}

function showBqmNoData(msg) {
    document.getElementById('bqm-card').hidden = true;
    DOCSightEmptyState.show(document.getElementById('bqm-no-data'), {
        icon: 'bar-chart-3',
        title: msg || T.bqm_no_data,
        text: T.bqm_empty_text,
        action: {label: T.bqm_empty_action, onClick: openBqmCsvImport},
        glossary: 'bqm'
    });
}

function toggleBqmCsvImport() {
    var section = document.getElementById('bqm-csv-import-section');
    section.hidden = !section.hidden;
}

function openBqmCsvImport() {
    document.getElementById('bqm-csv-import-section').hidden = false;
    document.getElementById('bqm-csv-file').focus();
}

function loadBqmChart(date) {
    setBqmViewMode('chart');
    hideBqmLiveBadge();
    updateBqmViewToggle(date);
    fetch(docsightUrl('/api/bqm/data/' + date))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.points) {
                showBqmNoData(T.bqm_no_csv_data);
                return;
            }
            BQMChart.render('bqm-chart-container', data, { dateAxis: false });
            showBqmCard();
        })
        .catch(function() {
            showBqmNoData(T.bqm_no_csv_data);
        });
}

function loadBqmRangeChart(start, end) {
    if (start === end) {
        loadBqmChart(start);
        return;
    }
    setBqmViewMode('chart');
    hideBqmLiveBadge();
    document.getElementById('bqm-view-toggle').hidden = true;
    fetch(docsightUrl('/api/bqm/data/range?start=' + encodeURIComponent(start) + '&end=' + encodeURIComponent(end)))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.points) {
                showBqmNoData(T.bqm_csv_dates_only);
                return;
            }
            BQMChart.render('bqm-chart-container', data, { dateAxis: true });
            showBqmCard();
        })
        .catch(function() {
            showBqmNoData(T.bqm_no_csv_data);
        });
}

/* The frame says which day or days the graph covers. */
function setBqmWindow(text) {
    document.getElementById('bqm-window').textContent = text || '';
}

function selectBqmDate(date) {
    bqmDate = date;
    _bqmRangeStart = null;
    _bqmRangeEnd = null;
    stopBqmLiveRefresh();
    renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
    updateBqmRangeLabel();
    setBqmWindow(formatDateDE(date) + ' \u00b7 ' + (date === todayStr()
        ? T.bqm_window_today
        : T.bqm_window_day));
    updateBqmViewToggle(date);
    if (_bqmCsvDates.has(date)) {
        loadBqmChart(date);
        return;
    }
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

function setBqmQuickRange(days, endDate) {
    endDate = endDate || todayStr();
    var end = new Date(endDate + 'T12:00:00');
    _bqmRangeStart = offsetDate(endDate, 1 - days);
    _bqmRangeEnd = endDate;
    bqmDate = _bqmRangeEnd;
    _bqmCalYear = end.getFullYear();
    _bqmCalMonth = end.getMonth();
    stopBqmLiveRefresh();
    updateBqmRangeLabel();
    renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
    loadBqmRangeChart(_bqmRangeStart, _bqmRangeEnd);
}

function selectBqmQuickDate(date) {
    var d = new Date(date + 'T12:00:00');
    _bqmCalYear = d.getFullYear();
    _bqmCalMonth = d.getMonth();
    selectBqmDate(date);
}

// Quick-jump buttons
var bqmTodayBtn = document.getElementById('bqm-today-btn');
var bqmYesterdayBtn = document.getElementById('bqm-yesterday-btn');
var bqm7dBtn = document.getElementById('bqm-7d-btn');
var bqm30dBtn = document.getElementById('bqm-30d-btn');
if (bqmTodayBtn) bqmTodayBtn.addEventListener('click', function() {
    var today = todayStr();
    if (_bqmCsvDates.has(today)) {
        setBqmQuickRange(1);
        return;
    }
    selectBqmQuickDate(today);
});
if (bqmYesterdayBtn) bqmYesterdayBtn.addEventListener('click', function() {
    var yd = offsetDate(todayStr(), -1);
    if (!_bqmCsvDates.has(yd)) {
        selectBqmQuickDate(yd);
        return;
    }
    setBqmQuickRange(1, yd);
});
if (bqm7dBtn) bqm7dBtn.addEventListener('click', function() { setBqmQuickRange(7); });
if (bqm30dBtn) bqm30dBtn.addEventListener('click', function() { setBqmQuickRange(30); });

// Month nav
var bqmMonthPrev = document.getElementById('bqm-month-prev');
var bqmMonthNext = document.getElementById('bqm-month-next');
if (bqmMonthPrev) bqmMonthPrev.addEventListener('click', function() { bqmMonthNav(-1); });
if (bqmMonthNext) bqmMonthNext.addEventListener('click', function() { bqmMonthNav(1); });

/* ── BQM Live Refresh ── */
function loadBqmLive() {
    var img = document.getElementById('bqm-image');
    setBqmViewMode('png');
    BQMChart.destroy('bqm-chart-container');
    document.getElementById('bqm-view-toggle').hidden = true;
    fetch(docsightUrl('/api/bqm/live')).then(function(r) {
        if (!r.ok) throw new Error('Live fetch failed');
        var source = r.headers.get('X-BQM-Source') || 'cached';
        var ts = r.headers.get('X-BQM-Timestamp');
        return r.blob().then(function(blob) {
            return { blob: blob, source: source, timestamp: ts };
        });
    }).then(function(data) {
        var url = URL.createObjectURL(data.blob);
        img.onload = function() {
            showBqmCard();
            URL.revokeObjectURL(url);
        };
        img.onerror = function() {
            showBqmNoData(T.bqm_no_data);
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
    var isLive = source === 'live';
    badge.textContent = isLive ? T.bqm_live : T.bqm_cached_png;
    badge.hidden = false;
    if (timestamp) {
        var label = isLive ? T.bqm_last_updated : T.bqm_cached_png_loaded;
        updated.textContent = label + ': ' + formatDocsightTime(timestamp, 'time', true);
        updated.hidden = false;
    }
}

function hideBqmLiveBadge() {
    document.getElementById('bqm-live-badge').hidden = true;
    document.getElementById('bqm-last-updated').hidden = true;
}

function startBqmLiveRefresh() {
    stopBqmLiveRefresh();
    if (bqmDate === todayStr()) {
        (function scheduleTick() {
            var jitter = Math.floor(Math.random() * _BQM_LIVE_JITTER);
            _bqmLiveTimer = setTimeout(function() {
                if (currentView !== 'bqm' || document.hidden || bqmDate !== todayStr()) {
                    scheduleTick();
                    return;
                }
                loadBqmLive();
                scheduleTick();
            }, _BQM_LIVE_INTERVAL + jitter);
        })();
    }
}

function stopBqmLiveRefresh() {
    if (_bqmLiveTimer) { clearTimeout(_bqmLiveTimer); _bqmLiveTimer = null; }
}

function updateBqmRangeLabel() {
    var label = document.getElementById('bqm-range-label');
    if (_bqmRangeStart && _bqmRangeEnd) {
        var count = Array.from(_bqmAvailableDates).filter(function(d) {
            return d >= _bqmRangeStart && d <= _bqmRangeEnd;
        }).length;
        label.textContent = formatDateDE(_bqmRangeStart) + ' \u2013 ' + formatDateDE(_bqmRangeEnd) + ' (' + count + ')';
        setBqmWindow(_bqmRangeStart === _bqmRangeEnd
            ? formatDateDE(_bqmRangeStart)
            : formatDateDE(_bqmRangeStart) + ' \u2013 ' + formatDateDE(_bqmRangeEnd));
    } else {
        label.textContent = '';
    }
}

/* ── BQM View Toggle (uPlot / PNG) ── */
var bqmToggleUplot = document.getElementById('bqm-toggle-uplot');
var bqmTogglePng = document.getElementById('bqm-toggle-png');
if (bqmToggleUplot) bqmToggleUplot.addEventListener('click', function() {
    if (_bqmViewMode === 'chart') return;
    loadBqmChart(bqmDate);
});
if (bqmTogglePng) bqmTogglePng.addEventListener('click', function() {
    if (_bqmViewMode === 'png') return;
    BQMChart.destroy('bqm-chart-container');
    loadBqmGraph(bqmDate);
});

/* ── BQM Graph ── */
function loadBqmGraph(date) {
    var img = document.getElementById('bqm-image');
    setBqmViewMode('png');
    BQMChart.destroy('bqm-chart-container');
    img.onload = function() {
        showBqmCard();
    };
    img.onerror = function() {
        showBqmNoData(T.bqm_no_data);
    };
    img.src = docsightUrl('/api/bqm/image/' + date);
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

/* ── CSV Bulk Import ── */

function importBqmCsv() {
    var input = document.getElementById('bqm-csv-file');
    if (!input.files.length) return;
    var btn = document.getElementById('bqm-csv-import-btn');
    var status = document.getElementById('bqm-csv-import-status');
    btn.disabled = true;
    status.textContent = T.bqm_csv_importing;
    status.className = 'bqm-csv-status';

    var formData = new FormData();
    formData.append('file', input.files[0]);

    fetch(docsightUrl('/api/bqm/import-csv'), { method: 'POST', body: formData })
        .then(function(r) {
            var ct = r.headers.get('content-type') || '';
            if (ct.indexOf('json') === -1) {
                throw new Error(T.bqm_upload_failed.replace('{0}', r.status));
            }
            return r.json();
        })
        .then(function(data) {
            if (data.error) {
                status.textContent = data.error;
                status.className = 'bqm-csv-status error';
            } else {
                status.textContent = T.bqm_csv_import_result
                    .replace('{0}', data.parsed_rows).replace('{1}', data.days)
                    .replace('{2}', data.date_range.start).replace('{3}', data.date_range.end);
                status.className = 'bqm-csv-status ok';
                fetchBqmDates(function() { renderBqmCalendar(_bqmCalYear, _bqmCalMonth); });
            }
        })
        .catch(function(err) {
            status.textContent = T.error_prefix + ': ' + err.message;
            status.className = 'bqm-csv-status error';
        })
        .finally(function() {
            btn.disabled = false;
            input.value = '';
        });
}

/* After an import the footer offers only Close; a new import starts with Cancel and Import again. */
function _setBqmImportFinished(finished) {
    document.getElementById('bqm-import-cancel-btn').hidden = finished;
    document.getElementById('bqm-import-confirm-btn').hidden = finished;
    document.getElementById('bqm-import-done-btn').hidden = !finished;
}

function openBqmImportModal() {
    _bqmImportFiles = [];
    document.getElementById('bqm-import-dropzone').hidden = false;
    document.getElementById('bqm-import-options').hidden = true;
    document.getElementById('bqm-import-status').hidden = true;
    document.getElementById('bqm-import-preview').hidden = true;
    document.getElementById('bqm-import-footer').hidden = true;
    _setBqmImportFinished(false);
    document.getElementById('bqm-import-overwrite').checked = false;
    document.getElementById('bqm-import-offset').value = '0';
    document.getElementById('bqm-import-tbody').replaceChildren();
    setBqmImportValidationState(T.bqm_import_validation_choose, 'info');
    window.DOCSightModal.open('bqm-import-modal');
}

function closeBqmImportModal() {
    window.DOCSightModal.close('bqm-import-modal');
    // Revoke thumb URLs
    _bqmImportFiles.forEach(function(f) { if (f.thumbUrl) URL.revokeObjectURL(f.thumbUrl); });
    _bqmImportFiles = [];
}

function setBqmImportValidationState(message, tone) {
    var el = document.getElementById('bqm-import-validation-state');
    el.textContent = message || '';
    el.className = 'import-validation-state' + (tone ? ' is-' + tone : '');
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
    if (rejected > 0) setBqmImportValidationState(T.bqm_import_validation_unsupported, 'error');
    if (_bqmImportFiles.length > 0) {
        // A set offset also applies to the new files; without one, dates edited by hand stay.
        if (parseInt(document.getElementById('bqm-import-offset').value)) applyBqmImportOffset();
        else renderBqmImportPreview();
    }
}

function renderBqmImportPreview() {
    var tbody = document.getElementById('bqm-import-tbody');
    tbody.replaceChildren();
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
        tdName.className = 'dt-primary';
        var nameSpan = document.createElement('span');
        nameSpan.className = 'bqm-import-filename';
        nameSpan.textContent = entry.file.name.length > 30 ? entry.file.name.substring(0, 27) + '...' : entry.file.name;
        nameSpan.title = entry.file.name;
        tdName.appendChild(nameSpan);
        // Conflict badge
        if (entry.date && _bqmAvailableDates.has(entry.date)) {
            var badge = document.createElement('span');
            badge.className = 'bqm-import-conflict';
            badge.textContent = T.bqm_import_conflict;
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
        // Keep the model current while typing; re-rendering here would replace the field mid-entry.
        dateInput.addEventListener('input', function() {
            var i = parseInt(this.getAttribute('data-idx'));
            _bqmImportFiles[i].date = this.value;
        });
        tdDate.appendChild(dateInput);
        tr.appendChild(tdDate);

        // Remove button
        var tdRemove = document.createElement('td');
        tdRemove.className = 'dt-primary';
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'modal-close';
        removeBtn.textContent = '\u00d7';
        removeBtn.setAttribute('aria-label', T.delete + ': ' + entry.file.name);
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
    labelDataTable(document.getElementById('bqm-import-table'));

    // Status line
    var statusEl = document.getElementById('bqm-import-status');
    statusEl.textContent = T.bqm_import_validation_ready.replace('{0}', datesDetected)
        + (datesMissing > 0 ? ', ' + T.bqm_import_validation_dates.replace('{0}', datesMissing) : '');
    statusEl.hidden = false;
    setBqmImportValidationState(statusEl.textContent, datesMissing ? 'warning' : 'success');

    document.getElementById('bqm-import-dropzone').hidden = true;
    document.getElementById('bqm-import-options').hidden = false;
    document.getElementById('bqm-import-preview').hidden = false;
    document.getElementById('bqm-import-footer').hidden = false;

    // Update button text and state
    var btn = document.getElementById('bqm-import-confirm-btn');
    var allValid = _bqmImportFiles.length > 0 && datesMissing === 0;
    btn.disabled = !allValid;
    var label = T.bqm_import_btn.replace('{0}', _bqmImportFiles.length);
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

    fetch(docsightUrl('/api/bqm/import'), { method: 'POST', body: fd })
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
            showToast(T.bqm_import_failed.replace('{0}', err.message), 'error');
            btn.disabled = false;
            var label = T.bqm_import_btn.replace('{0}', _bqmImportFiles.length);
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

    function count(key, value, className) {
        var span = document.createElement('span');
        if (className) span.className = className;
        span.textContent = T[key].replace('{0}', value);
        return span;
    }
    status.textContent = '';
    status.appendChild(count('bqm_import_result_imported', total, 'bqm-import-count-imported'));
    if (data.replaced) {
        status.appendChild(document.createTextNode(' ('));
        status.appendChild(count('bqm_import_result_replaced', data.replaced));
        status.appendChild(document.createTextNode(')'));
    }
    if (data.skipped) {
        status.appendChild(document.createTextNode(', '));
        status.appendChild(count('bqm_import_result_skipped', data.skipped, 'bqm-import-count-skipped'));
    }
    if (data.errors && data.errors.length) {
        status.appendChild(document.createTextNode(', '));
        status.appendChild(count('bqm_import_result_errors', data.errors.length, 'bqm-import-count-errors'));
    }
    status.hidden = false;

    // Show skipped dates if any (safe: date strings from server)
    if (data.skipped_dates && data.skipped_dates.length) {
        tbody.replaceChildren();
        var tr = document.createElement('tr');
        var td = document.createElement('td');
        td.colSpan = 4;
        td.className = 'bqm-import-skipped';
        var heading = document.createElement('div');
        heading.className = 'bqm-import-skipped-title';
        heading.textContent = T.bqm_import_skipped_dates;
        var dates = document.createElement('div');
        dates.className = 'bqm-import-skipped-dates';
        data.skipped_dates.forEach(function(d) {
            var date = document.createElement('span');
            date.textContent = d;
            dates.appendChild(date);
        });
        td.appendChild(heading);
        td.appendChild(dates);
        tr.appendChild(td);
        tbody.appendChild(tr);
        preview.hidden = false;
    } else {
        preview.hidden = true;
    }

    options.hidden = true;

    _setBqmImportFinished(true);
    footer.hidden = false;
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
        showToast(T.bqm_no_data_range, 'info');
        return;
    }

    if (_bqmRangeStart && _bqmRangeEnd) {
        // Count dates in range
        var rangeDates = [];
        _bqmAvailableDates.forEach(function(d) {
            if (d >= _bqmRangeStart && d <= _bqmRangeEnd) rangeDates.push(d);
        });
        if (rangeDates.length === 0) {
            showToast(T.bqm_no_data_range, 'info');
            return;
        }
        _deleteBqmImages({
            message: T.bqm_delete_range
                .replace('{0}', rangeDates.length)
                .replace('{1}', _bqmRangeStart)
                .replace('{2}', _bqmRangeEnd)
        }, { start: _bqmRangeStart, end: _bqmRangeEnd });
    } else {
        _deleteBqmImages({
            message: T.bqm_delete_all.replace('{0}', totalCount),
            requireText: 'DELETE',
            requireLabel: T.bqm_delete_confirm
        }, { all: true, confirm: 'DELETE_ALL' });
    }
}

function _deleteBqmImages(dialog, body) {
    docsightConfirm(Object.assign({
        title: T.delete,
        confirmText: T.delete,
        cancelText: T.cancel,
        danger: true
    }, dialog)).then(function(confirmed) {
        if (!confirmed) return null;
        return fetch(docsightUrl('/api/bqm/images'), {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
    })
    .then(function(r) { return r ? r.json() : null; })
    .then(function(data) {
        if (!data) return;
        var successMsg = T.bqm_delete_success.replace('{0}', data.deleted);
        showToast(successMsg, 'success');
        _bqmRangeStart = null;
        _bqmRangeEnd = null;
        fetchBqmDates(function() { renderBqmCalendar(_bqmCalYear, _bqmCalMonth); });
    })
    .catch(function(err) { showToast(T.bqm_delete_failed.replace('{0}', err.message), 'error'); });
}

/* ── BQM View Init (called from switchView) ── */
window.initBqmView = function() {
    if (!document.getElementById('view-bqm')) return;
    if (!bqmDate) bqmDate = todayStr();
    if (!_bqmDatesLoaded) {
        initBqmCalendar();
    } else {
        renderBqmCalendar(_bqmCalYear, _bqmCalMonth);
    }
    if (_bqmRangeStart && _bqmRangeEnd) {
        loadBqmRangeChart(_bqmRangeStart, _bqmRangeEnd);
    } else if (_bqmCsvDates.has(bqmDate)) {
        loadBqmChart(bqmDate);
    } else if (bqmDate === todayStr()) {
        loadBqmLive();
        startBqmLiveRefresh();
    } else {
        loadBqmGraph(bqmDate);
    }
};
