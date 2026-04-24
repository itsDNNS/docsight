/* ── FRITZ!Box Cable Segment Utilization ── */

var _fritzCableRange = 'all';

/* ── Range Tab Switching ── */
var fritzCableTabs = document.querySelectorAll('#fritz-cable-range-tabs .trend-tab');
fritzCableTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _fritzCableRange = this.getAttribute('data-range');
        fritzCableTabs.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-range') === _fritzCableRange);
        });
        loadFritzCableData();
    });
});

/* ── i18n helper ── */
function _fcT(key, fallback) {
    return T['seg_' + key] || T[key] || fallback || key;
}

/* ── Data Loading ── */
function loadFritzCableData() {
    var skel = document.getElementById('fritz-cable-skeleton');
    var msg = document.getElementById('fritz-cable-message');
    var content = document.getElementById('fritz-cable-content');
    if (!msg || !content) return;

    if (skel) skel.style.display = '';
    msg.style.display = 'none';
    content.style.display = 'none';

    fetch('/api/fritzbox/segment-utilization?range=' + encodeURIComponent(_fritzCableRange))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (skel) skel.style.display = 'none';
            if (data.error) {
                msg.textContent = data.error;
                msg.style.display = 'block';
                return;
            }
            if (!data.samples || data.samples.length === 0) {
                msg.textContent = _fcT('no_data', 'No segment utilization data collected yet.');
                msg.style.display = 'block';
                return;
            }
            content.style.display = '';
            _fritzCableUpdateKPIs(data);
            _fritzCableRenderChart('fritz-cable-ds-chart', data.samples, 'ds_total', 'ds_own');
            _fritzCableRenderChart('fritz-cable-us-chart', data.samples, 'us_total', 'us_own');
            _fritzCableLoadEvents();
        })
        .catch(function() {
            if (skel) skel.style.display = 'none';
            msg.textContent = _fcT('unavailable', 'Configuration unavailable.');
            msg.style.display = 'block';
        });
}

/* ── Events Widget ── */
var _FRITZ_EVENT_THRESHOLD = 80;
var _FRITZ_EVENT_MIN_MINUTES = 3;

function _fritzCableLoadEvents() {
    var list = document.getElementById('fritz-cable-events-list');
    var status = document.getElementById('fritz-cable-events-status');
    var meta = document.getElementById('fritz-cable-events-meta');
    if (!list || !status) return;

    while (list.firstChild) list.removeChild(list.firstChild);
    list.style.display = 'none';
    if (meta) meta.textContent = '';
    status.textContent = _fcT('events_loading', 'Loading saturation events...');
    status.className = 'fritz-cable-events-status is-loading';
    status.style.display = 'block';

    var url = '/api/fritzbox/segment-utilization/events'
        + '?range=' + encodeURIComponent(_fritzCableRange)
        + '&threshold=' + _FRITZ_EVENT_THRESHOLD
        + '&min_minutes=' + _FRITZ_EVENT_MIN_MINUTES;

    fetch(url)
        .then(function(r) { return r.json().then(function(body) { return { ok: r.ok, body: body }; }); })
        .then(function(resp) {
            if (!resp.ok || resp.body.error) {
                status.textContent = (resp.body && resp.body.error) || _fcT('events_error', 'Could not load saturation events.');
                status.className = 'fritz-cable-events-status is-error';
                return;
            }
            var events = resp.body.events || [];
            var threshold = resp.body.threshold != null ? resp.body.threshold : _FRITZ_EVENT_THRESHOLD;
            var minMinutes = resp.body.min_minutes != null ? resp.body.min_minutes : _FRITZ_EVENT_MIN_MINUTES;
            if (meta) {
                meta.textContent = _fcT('events_meta', 'Threshold {th}% for {min}+ min')
                    .replace('{th}', threshold)
                    .replace('{min}', minMinutes);
            }
            if (events.length === 0) {
                status.textContent = _fcT('events_empty', 'No saturation events detected in this range.');
                status.className = 'fritz-cable-events-status is-empty';
                return;
            }
            status.style.display = 'none';
            list.style.display = '';
            events.forEach(function(ev) { list.appendChild(_fritzCableRenderEvent(ev)); });
        })
        .catch(function() {
            status.textContent = _fcT('events_error', 'Could not load saturation events.');
            status.className = 'fritz-cable-events-status is-error';
        });
}

function _fritzCableFormatTs(ts, compact) {
    if (!ts) return '';
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    var pad = function(n) { return (n < 10 ? '0' : '') + n; };
    var hh = pad(d.getHours());
    var mm = pad(d.getMinutes());
    var dd = pad(d.getDate());
    var mo = pad(d.getMonth() + 1);
    if (compact) return hh + ':' + mm;
    return dd + '.' + mo + ' ' + hh + ':' + mm;
}

function _fritzCableFormatDuration(minutes) {
    if (minutes == null) return '';
    var m = Math.max(0, minutes | 0);
    if (m < 60) return m + ' ' + _fcT('events_min_short', 'min');
    var h = Math.floor(m / 60);
    var rem = m % 60;
    if (rem === 0) return h + ' ' + _fcT('events_h_short', 'h');
    return h + ' ' + _fcT('events_h_short', 'h') + ' ' + rem + ' ' + _fcT('events_min_short', 'min');
}

function _fritzCablePct(v) {
    if (v == null || isNaN(v)) return '-';
    return (+v).toFixed(1) + '%';
}

function _fcMakeStat(labelKey, labelFallback, valueText) {
    var span = document.createElement('span');
    var em = document.createElement('em');
    em.textContent = _fcT(labelKey, labelFallback) + ':';
    span.appendChild(em);
    span.appendChild(document.createTextNode(' ' + valueText));
    return span;
}

function _fritzCableRenderEvent(ev) {
    var li = document.createElement('li');
    li.className = 'fritz-cable-event';

    var directionKey = ev.direction === 'upstream' ? 'events_direction_us' : 'events_direction_ds';
    var directionLabel = _fcT(directionKey, ev.direction === 'upstream' ? 'Upstream' : 'Downstream');
    var directionCls = ev.direction === 'upstream' ? 'is-upstream' : 'is-downstream';

    var sameDay = false;
    if (ev.start && ev.end) {
        var ds = new Date(ev.start);
        var de = new Date(ev.end);
        sameDay = !isNaN(ds) && !isNaN(de)
            && ds.getFullYear() === de.getFullYear()
            && ds.getMonth() === de.getMonth()
            && ds.getDate() === de.getDate();
    }
    var rangeText;
    if (ev.start && ev.end && ev.start !== ev.end) {
        rangeText = _fritzCableFormatTs(ev.start, false) + ' – ' + _fritzCableFormatTs(ev.end, sameDay);
    } else {
        rangeText = _fritzCableFormatTs(ev.start, false) + ' (+' + _fritzCableFormatDuration(ev.duration_minutes) + ')';
    }

    var header = document.createElement('div');
    header.className = 'fritz-cable-event-header';
    var dirSpan = document.createElement('span');
    dirSpan.className = 'fritz-cable-event-direction ' + directionCls;
    dirSpan.textContent = directionLabel;
    header.appendChild(dirSpan);
    var timeSpan = document.createElement('span');
    timeSpan.className = 'fritz-cable-event-time';
    timeSpan.textContent = rangeText;
    header.appendChild(timeSpan);
    var durSpan = document.createElement('span');
    durSpan.className = 'fritz-cable-event-duration';
    durSpan.textContent = _fritzCableFormatDuration(ev.duration_minutes);
    header.appendChild(durSpan);
    li.appendChild(header);

    var neighbor = ev.peak_neighbor_load;
    if (neighbor == null && ev.peak_total != null && ev.peak_own != null) {
        neighbor = ev.peak_total - ev.peak_own;
    }
    var stats = document.createElement('div');
    stats.className = 'fritz-cable-event-stats';
    stats.appendChild(_fcMakeStat('events_peak_total', 'Peak total', _fritzCablePct(ev.peak_total)));
    stats.appendChild(_fcMakeStat('events_peak_own', 'Peak own', _fritzCablePct(ev.peak_own)));
    stats.appendChild(_fcMakeStat('events_peak_neighbor', 'Peak neighbor load', _fritzCablePct(neighbor)));
    var confKey = 'events_confidence_' + (ev.confidence || 'high');
    var confVal = _fcT(confKey, ev.confidence || 'high');
    stats.appendChild(_fcMakeStat('events_confidence', 'Confidence', confVal));
    li.appendChild(stats);

    var actions = document.createElement('div');
    actions.className = 'fritz-cable-event-actions';
    var hours = _fritzCablePickCorrelationHours(ev.start, ev.end, Date.now());
    if (hours != null) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'fritz-cable-event-link';
        btn.textContent = _fcT('events_correlate', 'Open in correlation');
        btn.addEventListener('click', function() {
            _fritzCableOpenInCorrelation(hours);
        });
        actions.appendChild(btn);
    } else {
        var note = document.createElement('span');
        note.className = 'fritz-cable-event-note';
        note.textContent = _fcT('events_correlate_out_of_range', 'Correlation view supports up to 7 days.');
        actions.appendChild(note);
    }
    li.appendChild(actions);

    return li;
}

/* ── Correlation Navigation ──
 * The correlation view has a fixed set of "hours" pills (24 / 48 / 168).
 * Pick the smallest pill whose window contains the entire event (start
 * through end). If the event's start predates the largest pill, return
 * null so the caller can hide the action — a narrower window would crop
 * the event. Pure function of its inputs. */
var _FRITZ_CORRELATION_PILLS = [24, 48, 168];
function _fritzCablePickCorrelationHours(eventStartIso, eventEndIso, nowMs) {
    if (!eventStartIso) return null;
    var startMs = Date.parse(eventStartIso);
    if (isNaN(startMs)) return null;
    var ageHours = Math.max(0, (nowMs - startMs) / 3600000);
    // +1h pad so the event is comfortably inside the window even after
    // rounding the correlation range to the nearest hour.
    var needed = Math.ceil(ageHours) + 1;
    for (var i = 0; i < _FRITZ_CORRELATION_PILLS.length; i++) {
        if (_FRITZ_CORRELATION_PILLS[i] >= needed) return _FRITZ_CORRELATION_PILLS[i];
    }
    return null;
}

/* Activating the correlation pill BEFORE switchView is load-bearing:
 * switchView synchronously calls loadCorrelationData(), which reads the
 * active pill via getPillValue(). If we switched first and activated the
 * pill afterwards, two fetches would race and stale data could win. */
function _fritzCableOpenInCorrelation(hours) {
    if (hours == null) return;
    var tabs = document.querySelectorAll('#correlation-tabs .trend-tab');
    tabs.forEach(function(tab) {
        var match = parseInt(tab.getAttribute('data-value'), 10) === hours;
        tab.classList.toggle('active', match);
    });
    if (typeof window.switchView === 'function') {
        window.switchView('correlation');
    } else {
        location.hash = 'correlation';
    }
}

window._fritzCablePickCorrelationHours = _fritzCablePickCorrelationHours;
window._fritzCableOpenInCorrelation = _fritzCableOpenInCorrelation;

/* ── KPI Update ── */
function _fritzCableUpdateKPIs(data) {
    var latest = data.latest && data.latest[0];
    var stats = data.stats || {};

    var dsEl = document.getElementById('fritz-cable-ds-total');
    var usEl = document.getElementById('fritz-cable-us-total');
    var statusEl = document.getElementById('fritz-cable-status');
    var dsStats = document.getElementById('fritz-cable-ds-stats');
    var usStats = document.getElementById('fritz-cable-us-stats');
    var countEl = document.getElementById('fritz-cable-count');

    if (dsEl) dsEl.textContent = latest ? (latest.ds_total != null ? latest.ds_total.toFixed(1) + '%' : '-') : '-';
    if (usEl) usEl.textContent = latest ? (latest.us_total != null ? latest.us_total.toFixed(1) + '%' : '-') : '-';
    if (statusEl) statusEl.textContent = stats.count > 0 ? _fcT('status_polling', 'Collecting') : _fcT('status_disabled', 'Disabled');

    if (dsStats && stats.count > 0) {
        dsStats.textContent = _fcT('min', 'Min') + ' ' + (stats.ds_total_min != null ? stats.ds_total_min.toFixed(1) : '-') + '% · '
            + _fcT('avg', 'Avg') + ' ' + (stats.ds_total_avg != null ? stats.ds_total_avg.toFixed(1) : '-') + '% · '
            + _fcT('max', 'Max') + ' ' + (stats.ds_total_max != null ? stats.ds_total_max.toFixed(1) : '-') + '%';
    }
    if (usStats && stats.count > 0) {
        usStats.textContent = _fcT('min', 'Min') + ' ' + (stats.us_total_min != null ? stats.us_total_min.toFixed(1) : '-') + '% · '
            + _fcT('avg', 'Avg') + ' ' + (stats.us_total_avg != null ? stats.us_total_avg.toFixed(1) : '-') + '% · '
            + _fcT('max', 'Max') + ' ' + (stats.us_total_max != null ? stats.us_total_max.toFixed(1) : '-') + '%';
    }
    if (countEl) countEl.textContent = stats.count + ' samples';
}

/* ── Chart Rendering via chart-engine (uPlot) ── */
function _fritzCableRenderChart(containerId, samples, totalKey, ownKey) {
    var container = document.getElementById(containerId);
    if (!container || typeof renderChart === 'undefined') return;

    var labels = samples.map(function(s) {
        var d = new Date(s.timestamp);
        var hh = (d.getHours() < 10 ? '0' : '') + d.getHours();
        var mm = (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();
        if (_fritzCableRange === '24h') return hh + ':' + mm;
        var dd = (d.getDate() < 10 ? '0' : '') + d.getDate();
        var mo = ((d.getMonth() + 1) < 10 ? '0' : '') + (d.getMonth() + 1);
        return dd + '.' + mo + ' ' + hh + ':' + mm;
    });

    var datasets = [
        {
            label: _fcT('total', 'Total'),
            data: samples.map(function(s) { return s[totalKey]; }),
            color: 'rgba(168,85,247,0.9)', fill: 'rgba(168,85,247,0.15)'
        },
        {
            label: _fcT('own', 'Own Share'),
            data: samples.map(function(s) { return s[ownKey]; }),
            color: '#6366f1',
            dashed: true
        }
    ];

    renderChart(containerId, labels, datasets, 'line', null, {
        yMin: 0,
        yMax: 100,
        tooltipLabelCallback: function(ctx) {
            var val = ctx.parsed.y;
            if (val == null) return '';
            return ctx.dataset.label + ': ' + val.toFixed(1) + '%';
        }
    });
}

window.loadFritzCableData = loadFritzCableData;

/* Auto-load if the view is already active (script loads after deferred routing) */
if (typeof currentView !== 'undefined' && currentView === 'segment-utilization') {
    setTimeout(loadFritzCableData, 0);
}
