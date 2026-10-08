/* ── Journal case timeline ──
   Opens a case as a timeline: header with the PDF report, the channel status
   track, a chart of signal, speed tests and journal entries over the case window,
   and the table of everything that happened. Loaded with the journal tab; the
   case steps and cards live in main.js. */
var _timelineChartInstance = null;

window.openIncidentTimeline = function(incidentId) {
    // Hide journal UI elements
    var tableCard = document.getElementById('journal-table-card');
    var searchWrap = document.getElementById('journal-search-wrap');
    var bulkBar = document.getElementById('journal-bulk-bar');
    var empty = document.getElementById('journal-empty');
    var deleteAllBtn = document.getElementById('journal-more-actions');
    if (tableCard) tableCard.hidden = true;
    if (searchWrap) searchWrap.hidden = true;
    if (bulkBar) bulkBar.hidden = true;
    DOCSightEmptyState.hide(empty);
    if (deleteAllBtn) deleteAllBtn.hidden = true;

    // Show timeline container with loading state
    var timelineView = document.getElementById('incident-timeline-view');
    timelineView.hidden = false;
    var caseCards = document.getElementById('case-cards');
    if (caseCards) caseCards.hidden = true;
    var header = document.getElementById('incident-timeline-header');
    header.innerHTML = '<div class="spinner incident-timeline-spinner"></div>';

    _timelineActive = true;
    _timelineIncidentId = incidentId;

    fetch(docsightUrl('/api/incidents/' + incidentId + '/timeline'))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                header.innerHTML = '<div class="incident-timeline-empty">' + escapeHtml(data.error) + '</div>';
                return;
            }
            renderIncidentTimeline(data);
        })
        .catch(function() {
            header.innerHTML = '<div class="incident-timeline-empty">' + (T.network_error || 'Error') + '</div>';
        });
};

window.closeIncidentTimeline = function() {
    var timelineView = document.getElementById('incident-timeline-view');
    timelineView.hidden = true;
    _timelineActive = false;
    var caseCards = document.getElementById('case-cards');
    if (caseCards) caseCards.hidden = !caseCards.childNodes.length;
    var caseSteps = document.getElementById('incident-timeline-steps');
    if (caseSteps) caseSteps.hidden = true;

    // Destroy chart to free memory
    if (_timelineChartInstance) {
        _timelineChartInstance = null;
    }

    // Re-show journal
    loadJournal();
};

function renderIncidentPdfButton(btn) {
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
    btn.appendChild(document.createTextNode(' ' + (T.incident_download_pdf || 'Download PDF Report')));
}

window.downloadIncidentPdf = function(incidentId, incidentName) {
    var btn = document.querySelector('.incident-timeline-pdf-btn');
    var params = new URLSearchParams();
    var langInput = document.getElementById('report-lang');
    var nameInput = document.getElementById('report-name');
    var numberInput = document.getElementById('report-number');
    var addressInput = document.getElementById('report-address');
    if (langInput) params.set('lang', langInput.value);
    if (nameInput) params.set('name', nameInput.value);
    if (numberInput) params.set('number', numberInput.value);
    if (addressInput) params.set('address', addressInput.value);
    if (btn) { btn.disabled = true; btn.textContent = '\u23F3'; }
    fetch(docsightUrl('/api/incidents/' + incidentId + '/report?' + params.toString()))
        .then(function(r) {
            if (!r.ok) throw new Error('Failed');
            return r.blob();
        })
        .then(function(blob) {
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'DOCSight_Beschwerde_' + incidentName.replace(/[^a-zA-Z0-9]/g, '_') + '_' + new Date().toISOString().slice(0, 10) + '.pdf';
            a.click();
            URL.revokeObjectURL(a.href);
        })
        .catch(function() {
            showToast(T.network_error || 'Error generating report', 'error');
        })
        .finally(function() {
            if (btn) { btn.disabled = false; renderIncidentPdfButton(btn); }
        });
};

/* Channel status track for the case window: start date to end date (inclusive), or to now. */
function _loadIncidentStatusTrack(inc) {
    var card = document.getElementById('incident-timeline-status');
    var track = document.getElementById('incident-status-track');
    if (!card || !track || !window.DOCSightStatusTrack || !inc.start_date) {
        if (card) card.hidden = true;
        return;
    }
    var params = new URLSearchParams({ start: inc.start_date.substring(0, 10) });
    var endDay = null;
    if (inc.end_date) {
        endDay = new Date(inc.end_date.substring(0, 10) + 'T00:00:00Z');
        endDay.setUTCDate(endDay.getUTCDate() + 1);
        params.set('end', endDay.toISOString().substring(0, 10));
    }
    var startMs = new Date(inc.start_date.substring(0, 10) + 'T00:00:00Z').getTime();
    var spanHours = Math.max(1, Math.round(((endDay ? endDay.getTime() : Date.now()) - startMs) / 3600000));
    track.textContent = '';
    card.hidden = false;
    window.DOCSightStatusTrack.load(track, params.toString(), {
        range: spanHours + 'h',
        idPrefix: 'incident-status',
        // The Channels charts count back from now; pick a range that reaches the case start.
        timelineRange: function() { return window.DOCSightStatusTrack.rangeFor((Date.now() - startMs) / 3600000); }
    });
}

function renderIncidentTimeline(data) {
    var inc = data.incident;
    var entries = data.entries || [];
    var timeline = data.timeline || [];
    var bnetz = data.bnetz || [];

    // -- 1. Header Card --
    var header = document.getElementById('incident-timeline-header');
    var statusLabel = T['incident_status_' + inc.status] || inc.status;
    var statusClass = 'incident-summary-status-' + inc.status;

    var dateRange = '';
    var durationText = '';
    if (inc.start_date) {
        dateRange = formatDateDE(inc.start_date);
        if (inc.end_date) {
            dateRange += ' \u2013 ' + formatDateDE(inc.end_date);
            var d1 = new Date(inc.start_date), d2 = new Date(inc.end_date);
            var diffDays = Math.ceil((d2 - d1) / (1000 * 60 * 60 * 24));
            durationText = diffDays + ' ' + (T.incident_duration_days || 'days');
        } else {
            dateRange += ' \u2013 ' + (T.incident_duration_ongoing || 'ongoing');
        }
    }

    var hHtml = '<div class="incident-timeline-header-title">';
    hHtml += escapeHtml(inc.name);
    hHtml += ' <span class="incident-summary-badge ' + statusClass + '">' + statusLabel + '</span>';
    hHtml += '</div>';
    hHtml += '<div class="incident-timeline-meta">';
    if (dateRange) {
        hHtml += '<span class="incident-timeline-meta-item">';
        hHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>';
        hHtml += dateRange;
        hHtml += '</span>';
    }
    if (durationText) {
        hHtml += '<span class="incident-timeline-meta-item">';
        hHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
        hHtml += durationText;
        hHtml += '</span>';
    }
    hHtml += '<span class="incident-timeline-meta-item">';
    hHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    hHtml += entries.length + ' ' + (T.incident_entry_count || 'Entries');
    hHtml += '</span>';
    hHtml += '</div>';
    if (inc.description) {
        hHtml += '<div class="incident-timeline-desc">' + escapeHtml(inc.description) + '</div>';
    }
    header.innerHTML = hHtml;
    var pdfBtn = document.createElement('button');
    pdfBtn.type = 'button';
    pdfBtn.className = 'incident-timeline-pdf-btn';
    renderIncidentPdfButton(pdfBtn);
    pdfBtn.addEventListener('click', function() {
        downloadIncidentPdf(inc.id, inc.name);
    });
    header.appendChild(pdfBtn);
    renderCaseSteps(inc);

    // -- 2. Journal Entries as Cards --
    var entriesDiv = document.getElementById('incident-timeline-entries');
    if (entries.length === 0) {
        entriesDiv.hidden = true;
    } else {
        entriesDiv.hidden = false;
        var eHtml = '<div class="incident-timeline-section-title">';
        eHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2z"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>';
        eHtml += (T.incident_journal_entries || 'Journal Entries');
        eHtml += '</div>';
        eHtml += '<div class="incident-timeline-entries-grid">';
        entries.forEach(function(entry) {
            var icon = _getEntryIcon(entry);
            eHtml += '<div class="incident-timeline-entry" role="button" tabindex="0" data-action="openEntryModal" data-action-args="[' + entry.id + ']">';
            eHtml += '<div class="incident-timeline-entry-icon">' + icon + '</div>';
            eHtml += '<div class="incident-timeline-entry-body">';
            eHtml += '<div class="incident-timeline-entry-date">' + formatDateDE(entry.date) + '</div>';
            eHtml += '<div class="incident-timeline-entry-title">' + escapeHtml(entry.title) + '</div>';
            if (entry.description) {
                var desc = entry.description.length > 120 ? entry.description.substring(0, 120) + '\u2026' : entry.description;
                eHtml += '<div class="incident-timeline-entry-desc">' + escapeHtml(desc) + '</div>';
            }
            if (entry.attachment_count) {
                eHtml += '<div class="incident-timeline-entry-att">\uD83D\uDCCE ' + entry.attachment_count + '</div>';
            }
            eHtml += '</div></div>';
        });
        eHtml += '</div>';
        entriesDiv.innerHTML = eHtml;
    }

    // -- 3. Channel status during the case window (its own request, started first) --
    _loadIncidentStatusTrack(inc);

    // -- 4. Signal Timeline Chart --
    var chartCard = document.getElementById('incident-timeline-chart-card');
    if (timeline.length === 0) {
        chartCard.querySelector('.incident-timeline-chart-wrap').innerHTML =
            '<div class="incident-timeline-empty">' + (T.timeline_no_data || 'No signal data for this period') + '</div>';
    } else {
        chartCard.querySelector('.incident-timeline-chart-wrap').innerHTML =
            '<canvas id="incident-timeline-canvas"></canvas>';
        _renderTimelineChart(timeline);
    }

    // -- 5. Signal Timeline Table --
    var signalsDiv = document.getElementById('incident-timeline-signals');
    if (timeline.length === 0) {
        signalsDiv.hidden = true;
    } else {
        signalsDiv.hidden = false;
        _renderTimelineTable(timeline);
    }

    // -- 6. BNetzA Section --
    var bnetzDiv = document.getElementById('incident-timeline-bnetz');
    if (bnetz.length === 0) {
        bnetzDiv.hidden = true;
    } else {
        bnetzDiv.hidden = false;
        var bHtml = '<div class="incident-timeline-section-title">';
        bHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>';
        bHtml += (T.incident_bnetz_measurements || 'BNetzA Measurements');
        bHtml += '</div>';
        bnetz.forEach(function(m) {
            var hasDeviation = m.verdict_download === 'deviation' || m.verdict_upload === 'deviation';
            var verdictText = hasDeviation ? (T.bnetz_verdict_deviation || 'Deviation') : (T.bnetz_verdict_ok || 'OK');
            var verdictClass = hasDeviation ? 'val-crit' : 'val-good';
            bHtml += '<div class="incident-timeline-bnetz-item">';
            bHtml += '<span>' + formatDateDE(m.date) + '</span>';
            bHtml += '<span>\u2193 ' + (m.download_measured_avg || 0).toFixed(1) + ' / ' + (m.download_max_tariff || 0).toFixed(0) + ' Mbps</span>';
            bHtml += '<span>\u2191 ' + (m.upload_measured_avg || 0).toFixed(1) + ' / ' + (m.upload_max_tariff || 0).toFixed(0) + ' Mbps</span>';
            bHtml += '<span class="incident-timeline-bnetz-verdict ' + verdictClass + '">' + verdictText + '</span>';
            bHtml += '</div>';
        });
        bnetzDiv.innerHTML = bHtml;
    }

    // Re-initialize Lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/* A case timeline holds thousands of points; parse each timestamp once. */
function _timelineMs(point) {
    if (point._ms === undefined) point._ms = docsightParseTime(point.timestamp).getTime();
    return point._ms;
}

/* Plot box and scales of the case chart: SNR on the left, speed on the right, time below. */
function journalTimelineScales(data, width, height) {
    var pad = { top: 20, right: 60, bottom: 40, left: 60 };
    var plotW = width - pad.left - pad.right;
    var plotH = height - pad.top - pad.bottom;
    var modem = data.filter(function(d) { return d.source === 'modem'; });
    var speedtest = data.filter(function(d) { return d.source === 'speedtest'; });

    var allTs = data.map(_timelineMs);
    var tMin = Math.min.apply(null, allTs);
    var tMax = Math.max.apply(null, allTs);
    if (tMin === tMax) tMax = tMin + 86400000;

    var snrValues = modem.map(function(d) { return d.ds_snr_min || 0; }).filter(function(v) { return v > 0; });
    var snrMin = snrValues.length ? Math.floor(Math.min.apply(null, snrValues) - 2) : 20;
    var snrMax = snrValues.length ? Math.ceil(Math.max.apply(null, snrValues) + 2) : 45;

    var dlValues = speedtest.map(function(d) { return d.download_mbps || 0; });
    var speedMax = dlValues.length ? Math.ceil(Math.max.apply(null, dlValues) * 1.1) : 500;
    if (speedMax < 10) speedMax = 100;

    return {
        pad: pad, plotW: plotW, plotH: plotH, tMin: tMin, tMax: tMax,
        snrMin: snrMin, snrMax: snrMax, speedMax: speedMax,
        speedStep: speedMax > 400 ? 100 : speedMax > 200 ? 50 : 25,
        xScale: function(ts) { return pad.left + (ts - tMin) / (tMax - tMin) * plotW; },
        ySnr: function(v) { return pad.top + plotH - (v - snrMin) / (snrMax - snrMin) * plotH; },
        yDl: function(v) { return pad.top + plotH - v / speedMax * plotH; }
    };
}

function _renderTimelineChart(data) {
    var canvas = document.getElementById('incident-timeline-canvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    var W = rect.width;
    var H = 280;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    var modem = data.filter(function(d) { return d.source === 'modem'; });
    var speedtest = data.filter(function(d) { return d.source === 'speedtest'; });
    var events = data.filter(function(d) { return d.source === 'event'; });

    if (modem.length === 0 && speedtest.length === 0) {
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
        ctx.font = '13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(T.timeline_no_data || 'No signal data', W / 2, H / 2);
        return;
    }

    var sc = journalTimelineScales(data, W, H);
    var pad = sc.pad, plotW = sc.plotW, plotH = sc.plotH, tMin = sc.tMin, tMax = sc.tMax;
    var snrMin = sc.snrMin, snrMax = sc.snrMax, speedMax = sc.speedMax;
    var xScale = sc.xScale, ySnr = sc.ySnr, yDl = sc.yDl;

    var style = getComputedStyle(document.documentElement);
    var textColor = style.getPropertyValue('--muted').trim() || '#888';
    var gridColor = style.getPropertyValue('--input-border').trim() || '#333';
    var goodColor = style.getPropertyValue('--good').trim() || '#4caf50';
    var warnColor = style.getPropertyValue('--warn').trim() || '#ff9800';
    var critColor = style.getPropertyValue('--crit').trim() || '#f44336';
    var accentColor = style.getPropertyValue('--accent').trim() || '#a855f7';
    var uploadColor = '#06b6d4';

    // Grid
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 0.5;
    ctx.setLineDash([2, 4]);
    for (var s = Math.ceil(snrMin); s <= snrMax; s += 5) {
        var y = ySnr(s);
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + plotW, y); ctx.stroke();
    }
    ctx.setLineDash([]);

    // Time axis labels
    ctx.fillStyle = textColor;
    ctx.font = '12px system-ui, sans-serif';
    ctx.textAlign = 'center';
    var tRange = tMax - tMin;
    var labelCount = Math.min(8, Math.floor(plotW / 80));
    for (var i = 0; i <= labelCount; i++) {
        var t = tMin + tRange * i / labelCount;
        var d = new Date(t);
        var label = docsightFormatAxisTime(d, tRange > 172800000 ? 'monthday-time' : 'time'); // > 2 days
        ctx.fillText(label, xScale(t), H - pad.bottom + 18);
    }

    // Left axis labels (SNR)
    if (modem.length > 0) {
        ctx.textAlign = 'right';
        ctx.fillStyle = accentColor;
        for (var s = Math.ceil(snrMin); s <= snrMax; s += 5) {
            ctx.fillText(s + ' dB', pad.left - 6, ySnr(s) + 3);
        }
    }

    // Right axis labels (Speed)
    if (speedtest.length > 0) {
        ctx.textAlign = 'left';
        ctx.fillStyle = goodColor;
        for (var v = 0; v <= speedMax; v += sc.speedStep) {
            ctx.fillText(v + ' Mbps', pad.left + plotW + 6, yDl(v) + 3);
        }
    }

    // SNR line (modem)
    if (modem.length > 1) {
        var sorted = modem.slice().sort(function(a, b) {
            return _timelineMs(a) - _timelineMs(b);
        });
        ctx.strokeStyle = accentColor;
        ctx.lineWidth = 2;
        ctx.beginPath();
        sorted.forEach(function(d, i) {
            var x = xScale(_timelineMs(d));
            var y = ySnr(d.ds_snr_min || snrMin);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
    }

    // Speed dots
    speedtest.forEach(function(d) {
        var x = xScale(_timelineMs(d));
        // Download dot
        ctx.fillStyle = goodColor;
        ctx.beginPath();
        ctx.arc(x, yDl(d.download_mbps || 0), 4, 0, Math.PI * 2);
        ctx.fill();
        // Upload dot (smaller)
        ctx.fillStyle = uploadColor;
        ctx.beginPath();
        ctx.arc(x, yDl(d.upload_mbps || 0), 3, 0, Math.PI * 2);
        ctx.fill();
    });

    // Event markers
    events.forEach(function(d) {
        var x = xScale(_timelineMs(d));
        var col = d.severity === 'critical' ? critColor : d.severity === 'warning' ? warnColor : textColor;
        ctx.strokeStyle = col;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
        // Triangle marker
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.moveTo(x, pad.top - 2);
        ctx.lineTo(x - 4, pad.top - 8);
        ctx.lineTo(x + 4, pad.top - 8);
        ctx.closePath();
        ctx.fill();
    });

    // Legend
    var legendY = H - 6;
    ctx.font = '12px system-ui, sans-serif';
    ctx.textAlign = 'left';
    var lx = pad.left;
    if (modem.length > 0) {
        ctx.fillStyle = accentColor;
        ctx.fillRect(lx, legendY - 6, 12, 3);
        ctx.fillStyle = textColor;
        ctx.fillText('SNR', lx + 16, legendY);
        lx += 50;
    }
    if (speedtest.length > 0) {
        ctx.fillStyle = goodColor;
        ctx.beginPath(); ctx.arc(lx + 4, legendY - 4, 3, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = textColor;
        ctx.fillText('DL', lx + 12, legendY);
        lx += 36;
        ctx.fillStyle = uploadColor;
        ctx.beginPath(); ctx.arc(lx + 4, legendY - 4, 3, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = textColor;
        ctx.fillText('UL', lx + 12, legendY);
        lx += 36;
    }
    if (events.length > 0) {
        ctx.fillStyle = warnColor;
        ctx.beginPath();
        ctx.moveTo(lx + 4, legendY - 2);
        ctx.lineTo(lx, legendY - 8);
        ctx.lineTo(lx + 8, legendY - 8);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = textColor;
        ctx.fillText(T.timeline_source_event || 'Event', lx + 12, legendY);
    }
}

function _renderTimelineTable(data) {
    var div = document.getElementById('incident-timeline-signals');

    var healthLabels = {
        good: T.health_good || 'Good',
        tolerated: T.health_tolerated || 'Tolerated',
        marginal: T.health_marginal || 'Marginal',
        critical: T.health_critical || 'Critical'
    };

    var tHtml = '<div class="incident-timeline-section-title">';
    tHtml += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
    tHtml += (T.correlation_timeline || 'Unified Timeline');
    tHtml += '</div>';
    tHtml += '<table class="data-table data-table-compact data-table-list" id="incident-timeline-table"><thead><tr>';
    tHtml += '<th>' + (T.timestamp || 'Timestamp') + '</th>';
    tHtml += '<th>' + (T.source || 'Source') + '</th>';
    tHtml += '<th>' + (T.event_details || 'Details') + '</th>';
    tHtml += '</tr></thead><tbody>';

    // Show newest first, limit to 200
    var sorted = data.slice().reverse();
    var modemTransitions = {};
    var lastHealth = null;
    var chrono = data.slice().sort(function(a, b) {
        return _timelineMs(a) - _timelineMs(b);
    });
    for (var i = 0; i < chrono.length; i++) {
        if (chrono[i].source !== 'modem') continue;
        var h = chrono[i].health || 'unknown';
        if (h !== lastHealth) { modemTransitions[chrono[i].timestamp] = true; lastHealth = h; }
    }

    var count = 0;
    for (var i = 0; i < sorted.length && count < 200; i++) {
        var e = sorted[i];
        if (e.source === 'modem' && !modemTransitions[e.timestamp]) continue;

        var ts = escapeHtml(formatDocsightTime(e.timestamp, 'datetime', true));
        var srcBadge = '';
        var details = '';

        if (e.source === 'modem') {
            srcBadge = '<span class="timeline-source-badge timeline-source-badge-modem">' + (T.timeline_source_modem || 'Modem') + '</span>';
            var hLabel = healthLabels[e.health] || e.health;
            details = '<span class="st-health-badge health-' + (e.health || 'unknown') + '">' + hLabel + '</span>';
            details += ' SNR ' + (e.ds_snr_min != null ? e.ds_snr_min + ' dB' : '-');
            details += ' | ' + (T.event_power || 'Power') + ' ' + (e.ds_power_avg != null ? e.ds_power_avg + ' dBmV' : '-');
            if (e.ds_uncorrectable_errors != null) {
                details += ' | ' + (T.correlation_tt_errors || 'Errors') + ' ' + e.ds_uncorrectable_errors;
            }
        } else if (e.source === 'speedtest') {
            srcBadge = '<span class="timeline-source-badge timeline-source-badge-speedtest">' + (T.timeline_source_speedtest || 'Speedtest') + '</span>';
            details = (e.download_mbps ? e.download_mbps.toFixed(1) + ' / ' + (e.upload_mbps || 0).toFixed(1) + ' Mbps' : '');
            if (e.ping_ms) details += ' | Ping ' + e.ping_ms + ' ms';
        } else if (e.source === 'event') {
            srcBadge = '<span class="timeline-source-badge timeline-source-badge-event">' + (T.timeline_source_event || 'Event') + '</span>';
            details = typeof formatEventMessage === 'function' ? formatEventMessage(e) : escapeHtml(e.message || '');
        }

        tHtml += '<tr><td class="timeline-preview-time dt-primary">' + ts + '</td>';
        tHtml += '<td class="dt-primary">' + srcBadge + '</td>';
        tHtml += '<td class="timeline-preview-details">' + details + '</td></tr>';
        count++;
    }

    tHtml += '</tbody></table>';
    div.innerHTML = tHtml;
    labelDataTable(document.getElementById('incident-timeline-table'));
    // Event messages carry arrow icons.
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
