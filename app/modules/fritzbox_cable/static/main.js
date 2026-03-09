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
    return T[key] || T['docsight.fritzbox_cable.' + key] || fallback || key;
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
        })
        .catch(function() {
            if (skel) skel.style.display = 'none';
            msg.textContent = _fcT('unavailable', 'Configuration unavailable.');
            msg.style.display = 'block';
        });
}

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
            color: '#a855f7'
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

/* Auto-load if the view is already active (module script loads after deferred routing) */
if (typeof currentView !== 'undefined' && currentView === 'mod-docsight-fritzbox_cable') {
    setTimeout(loadFritzCableData, 0);
}
