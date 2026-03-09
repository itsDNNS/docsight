var _fritzCableLoaded = false;

function _fritzCableText(key, fallback) {
    return (window.T && (window.T[key] || window.T['docsight.fritzbox_cable.' + key])) || fallback;
}

function _fritzCableFormatRate(value) {
    var num = Number(value || 0);
    if (!isFinite(num)) return '0 bps';
    if (num >= 1000000000) return (num / 1000000000).toFixed(2) + ' Gbps';
    if (num >= 1000000) return (num / 1000000).toFixed(2) + ' Mbps';
    if (num >= 1000) return (num / 1000).toFixed(1) + ' Kbps';
    return Math.round(num) + ' bps';
}

function _fritzCablePercent(current, ceiling) {
    if (!ceiling) return '0%';
    return ((current / ceiling) * 100).toFixed(1) + '%';
}

function _fritzCableRenderChart(containerId, series, color) {
    var container = document.getElementById(containerId);
    if (!container) return;
    if (!series || !series.length) {
        container.innerHTML = '<div class="fritz-cable-empty">' + _fritzCableText('no_data', 'No utilization samples available.') + '</div>';
        return;
    }

    var width = 640;
    var height = 220;
    var padding = 16;
    var max = Math.max.apply(null, series.concat([1]));
    var step = series.length > 1 ? (width - padding * 2) / (series.length - 1) : 0;
    var points = series.map(function(value, idx) {
        var x = padding + (step * idx);
        var y = height - padding - (((value || 0) / max) * (height - padding * 2));
        return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');

    var area = 'M ' + padding + ' ' + (height - padding) + ' L ' +
        points.replace(/ /g, ' L ') + ' L ' + (width - padding) + ' ' + (height - padding) + ' Z';

    container.innerHTML =
        '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<defs><linearGradient id="' + containerId + '-fill" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0%" stop-color="' + color + '" stop-opacity="0.35"></stop>' +
        '<stop offset="100%" stop-color="' + color + '" stop-opacity="0.04"></stop>' +
        '</linearGradient></defs>' +
        '<path d="' + area + '" fill="url(#' + containerId + '-fill)"></path>' +
        '<polyline points="' + points + '" fill="none" stroke="' + color + '" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>' +
        '</svg>';
}

function loadFritzCableUtilization() {
    var message = document.getElementById('fritz-cable-message');
    var content = document.getElementById('fritz-cable-content');
    if (message) {
        message.style.display = '';
        message.textContent = _fritzCableText('loading', 'Loading cable utilization...');
    }
    if (content) content.style.display = 'none';

    fetch('/api/fritzbox/cable-utilization')
        .then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); })
        .then(function(res) {
            var data = res.data || {};
            if (!data.supported) {
                if (message) message.textContent = data.message || _fritzCableText('unsupported_driver', 'This view is only available for FRITZ!Box cable devices.');
                return;
            }

            if (message) message.style.display = 'none';
            if (content) content.style.display = '';

            document.getElementById('fritz-cable-status').textContent = data.status || '-';
            document.getElementById('fritz-cable-duration').textContent = data.duration || '-';
            document.getElementById('fritz-cable-ds-rate').textContent = data.downstream_rate || '-';
            document.getElementById('fritz-cable-us-rate').textContent = data.upstream_rate || '-';
            document.getElementById('fritz-cable-mode').textContent = data.mode || '-';
            document.getElementById('fritz-cable-channel-counts').textContent =
                (data.channel_counts.downstream || 0) + ' DS / ' + (data.channel_counts.upstream || 0) + ' US';

            document.getElementById('fritz-cable-ds-title').textContent = data.downstream.title || _fritzCableText('downstream', 'Downstream');
            document.getElementById('fritz-cable-ds-subtitle').textContent = data.downstream.subtitle || '';
            document.getElementById('fritz-cable-us-title').textContent = data.upstream.title || _fritzCableText('upstream', 'Upstream');
            document.getElementById('fritz-cable-us-subtitle').textContent = data.upstream.subtitle || '';

            document.getElementById('fritz-cable-ds-current').textContent =
                _fritzCableText('current', 'Current') + ': ' + _fritzCableFormatRate(data.downstream.current_bps) +
                ' (' + _fritzCablePercent(data.downstream.current_bps, data.downstream.window_max_bps) + ')';
            document.getElementById('fritz-cable-ds-peak').textContent =
                _fritzCableText('peak', 'Peak') + ': ' + _fritzCableFormatRate(data.downstream.peak_bps);

            document.getElementById('fritz-cable-us-current').textContent =
                _fritzCableText('current', 'Current') + ': ' + _fritzCableFormatRate(data.upstream.current_bps) +
                ' (' + _fritzCablePercent(data.upstream.current_bps, data.upstream.window_max_bps) + ')';
            document.getElementById('fritz-cable-us-peak').textContent =
                _fritzCableText('peak', 'Peak') + ': ' + _fritzCableFormatRate(data.upstream.peak_bps);

            document.getElementById('fritz-cable-model').textContent = data.model || '-';
            document.getElementById('fritz-cable-docsis').textContent = data.docsis_software_version || '-';
            document.getElementById('fritz-cable-cm-mac').textContent = data.cm_mac || '-';
            document.getElementById('fritz-cable-sampling').textContent =
                (data.sampling_interval_seconds || 0) + 's / ' + (data.downstream.samples_bps || []).length + ' ' +
                _fritzCableText('samples', 'samples');

            _fritzCableRenderChart('fritz-cable-ds-chart', data.downstream.samples_bps || [], '#4f8cff');
            _fritzCableRenderChart('fritz-cable-us-chart', data.upstream.samples_bps || [], '#ff8f5a');
        })
        .catch(function() {
            if (message) {
                message.style.display = '';
                message.textContent = _fritzCableText('fetch_failed', 'Cable utilization could not be loaded from the FRITZ!Box right now.');
            }
        });
}

(function() {
    var refresh = document.getElementById('fritz-cable-refresh');
    if (refresh) {
        refresh.addEventListener('click', loadFritzCableUtilization);
    }

    var originalSwitchView = window.switchView;
    if (typeof originalSwitchView === 'function' && !window._fritzCableSwitchWrapped) {
        window.switchView = function(view, skipHash) {
            originalSwitchView(view, skipHash);
            if (view === 'mod-docsight-fritzbox_cable') {
                loadFritzCableUtilization();
                _fritzCableLoaded = true;
            }
        };
        window._fritzCableSwitchWrapped = true;
    }

    var view = document.getElementById('view-mod-docsight-fritzbox_cable');
    if (view && view.classList.contains('active') && !_fritzCableLoaded) {
        loadFritzCableUtilization();
        _fritzCableLoaded = true;
    }
})();
