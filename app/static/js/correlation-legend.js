/* ── Correlation legend and event filter ──
   The legend toggles the chart's series; its events entry opens a filter by
   event type and severity. eventFilter(), items() and toggle() are pure and run
   in Node tests; render() builds the legend and the filter popover in the page. */
(function (root, factory) {
    'use strict';
    var api = factory(root && root.DOCSightCorrelationData
        ? root.DOCSightCorrelationData
        : require('./correlation-data.js'));
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) Object.defineProperty(root, 'DOCSightCorrelationLegend', {
        configurable: false,
        writable: false,
        value: api
    });
})(typeof window !== 'undefined' ? window : null, function (CorrelationData) {
    'use strict';

    /* Operational events are hidden until the user turns them on. */
    var OPERATIONAL_EVENTS = { monitoring_started: true, monitoring_stopped: true };

    /* Filter state by event type and, per type, by severity. New types and
       severities get their default the first time they are seen. */
    function eventFilter() {
        var types = {};
        var severities = {};
        function severity(type) {
            if (!(type in severities)) severities[type] = { info: true, warning: true, critical: true };
            return severities[type];
        }
        function allowed(e) {
            var type = e.event_type || 'unknown';
            if (!(type in types)) types[type] = !OPERATIONAL_EVENTS[type];
            var bySeverity = severity(type);
            var sev = CorrelationData.normalizeSeverity(e);
            if (!(sev in bySeverity)) bySeverity[sev] = true;
            return types[type] && bySeverity[sev] !== false;
        }
        /* Counts per type and per type and severity, and how many pass the filter. */
        function summary(events) {
            var counts = {}, severityCounts = {}, visible = 0;
            events.forEach(function (e) {
                var type = e.event_type || 'unknown';
                var sev = CorrelationData.normalizeSeverity(e);
                counts[type] = (counts[type] || 0) + 1;
                if (!(type in severityCounts)) severityCounts[type] = {};
                severityCounts[type][sev] = (severityCounts[type][sev] || 0) + 1;
                if (allowed(e)) visible++;
            });
            return { types: counts, severities: severityCounts, visible: visible, total: events.length };
        }
        return { types: types, severity: severity, allowed: allowed, summary: summary };
    }

    /* Legend entries for what the chart state holds, in display order. */
    function items(st, filter, T, fahrenheit) {
        var c = st.colors;
        var list = [];
        function add(metric, color, label) { list.push({ metric: metric, color: color, label: label }); }
        if (st.modem.length > 0) {
            if (st.hasPowerData) add('dsPower', c.dsPower, '&#183;&#183; ' + (T.chart_ds_power || 'DS Power (dBmV)'));
            if (st.hasTxData) add('txPower', c.txPower, '&#9476; ' + (T.chart_us_power || 'US Power (dBmV)'));
            add('snr', c.snr, '&#9644; ' + (T.chart_snr || 'SNR (dB)'));
            add('signalState', c.health.good, '&#9646; ' + (T.correlation_lane_state || 'Signal state'));
            if (st.hasErrorData) add('errors', 'rgba(239,68,68,0.8)', '&#9612; ' + (T.correlation_errors || 'Errors'));
        }
        if (st.speedtest.length > 0) {
            add('download', c.download, '&#9474;&#9679; ' + (T.correlation_download || 'Download (Mbps)'));
            add('upload', c.upload, '&#9474;&#9679; ' + (T.correlation_upload || 'Upload (Mbps)'));
        }
        if (st.events.length > 0) {
            add('events', c.warn, '&#9650; ' + (T.correlation_events || 'Events'));
            list[list.length - 1].events = filter.summary(st.events);
        }
        if (st.weather.length > 0) {
            add('temperature', c.temperature, '- - ' + (T.temperature || 'Temperature') + ' (' + (fahrenheit ? '°F' : '°C') + ')');
        }
        if (st.segment.length > 0) {
            add('segmentDs', c.segmentDs, '&#9644; ' + (T.seg_correlation_ds || 'Segment DS (%)'));
            add('segmentUs', c.segmentUs, '&#9644; ' + (T.seg_correlation_us || 'Segment US (%)'));
        }
        if (st.reachabilityBuckets.length > 0) {
            add('reachability', c.accent, '&#9646; ' + (T.correlation_reachability || 'Reachability'));
        }
        return list;
    }

    /* Flips one series; the last visible one stays on. Returns whether it changed. */
    function toggle(visible, metric) {
        var shown = Object.keys(visible).filter(function (key) { return visible[key]; }).length;
        if (visible[metric] && shown <= 1) return false;
        visible[metric] = !visible[metric];
        return true;
    }

    function escapeAttr(value) {
        return escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    /* Colors computed at runtime reach CSS as --corr-color through the CSSOM,
       never as inline style attributes in built HTML. */
    function applyColors(root) {
        root.querySelectorAll('[data-color]').forEach(function (el) {
            el.style.setProperty('--corr-color', el.getAttribute('data-color'));
        });
    }

    function closePopover() {
        var pop = document.getElementById('corr-event-popover');
        if (pop && pop.matches(':popover-open')) pop.hidePopover();
    }

    function positionPopover(pop, anchor) {
        var margin = 8;
        var anchorRect = anchor.getBoundingClientRect();
        pop.style.maxHeight = Math.max(160, window.innerHeight - (margin * 2)) + 'px';
        // Measure after attaching to the body so positioning is based on the real viewport.
        var popRect = pop.getBoundingClientRect();
        var left = anchorRect.left;
        if (left + popRect.width > window.innerWidth - margin) left = window.innerWidth - margin - popRect.width;
        var top = anchorRect.bottom + margin;
        if (top + popRect.height > window.innerHeight - margin) top = anchorRect.top - popRect.height - margin;
        pop.style.left = Math.max(margin, left) + 'px';
        pop.style.top = Math.max(margin, top) + 'px';
    }

    function popoverHtml(events, filter, color, T) {
        var typeLabel = {
            health_change: T.event_type_health_change || 'Health Change',
            power_change: T.event_type_power_change || 'Power Change',
            snr_change: T.event_type_snr_change || 'SNR Change',
            channel_change: T.event_type_channel_change || 'Channel Change',
            modulation_change: T.event_type_modulation_change || 'Modulation Change',
            error_spike: T.event_type_error_spike || 'Error Spike',
            monitoring_started: T.event_type_monitoring_started || 'Monitoring Started',
            monitoring_stopped: T.event_type_monitoring_stopped || 'Monitoring Stopped'
        };
        var severityLabel = {
            info: T.event_severity_info || 'Info',
            warning: T.event_severity_warning || 'Warning',
            critical: T.event_severity_critical || 'Critical'
        };
        var colorAttr = ' data-color="' + escapeAttr(color) + '"';
        var html = '<div class="corr-event-filter-title">' + (T.event_filter_title || 'Event Types') + '</div>';
        Object.keys(events.types).sort().forEach(function (type) {
            var label = typeLabel[type] || type.replace(/_/g, ' ').replace(/\b\w/g, function (ch) { return ch.toUpperCase(); });
            var bySeverity = filter.severity(type);
            html += '<div class="corr-event-filter-group">' +
                '<label class="corr-event-filter-type">' +
                '<input type="checkbox" data-event-type="' + escapeAttr(type) + '"' + (filter.types[type] ? ' checked' : '') + colorAttr + '> ' +
                '<span class="corr-event-filter-name">' + escapeHtml(label) + '</span> <span class="corr-event-filter-count">(' + events.types[type] + ')</span></label>' +
                '<div class="corr-event-filter-severities">';
            CorrelationData.SEVERITIES.forEach(function (sev) {
                var count = (events.severities[type] && events.severities[type][sev]) || 0;
                html += '<label class="corr-event-filter-severity">' +
                    '<input type="checkbox" data-event-type="' + escapeAttr(type) + '" data-event-severity="' + escapeAttr(sev) + '"' + (bySeverity[sev] !== false ? ' checked' : '') + colorAttr + '> ' +
                    escapeHtml(severityLabel[sev] || sev) + ' <span class="corr-event-filter-count">(' + count + ')</span></label>';
            });
            html += '</div></div>';
        });
        return html;
    }

    /* One native popover next to the legend: the gear opens it through popovertarget, so
       Escape, outside clicks, focus return and the expanded state come from the browser.
       It sits outside the legend, which is rebuilt on every redraw. */
    function eventPopover(legend) {
        var pop = document.getElementById('corr-event-popover');
        if (pop) return pop;
        pop = document.createElement('div');
        pop.id = 'corr-event-popover';
        pop.className = 'corr-event-popover';
        pop.setAttribute('popover', 'auto');
        legend.after(pop);
        var position = function () { positionPopover(pop, pop._corr.button); };
        pop.addEventListener('beforetoggle', function (e) {
            if (e.newState !== 'open') return;
            var state = pop._corr;
            pop.innerHTML = docsightHTML(popoverHtml(state.events, state.options.filter, state.options.eventColor, state.options.T));
            applyColors(pop);
            var first = pop.querySelector('input');
            if (first) first.setAttribute('autofocus', '');
            // Placed before the first frame; the toggle event below arrives later.
            requestAnimationFrame(position);
        });
        // The gear that opened it may have been rebuilt meanwhile; Escape returns to the current one.
        pop.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') pop._corrEscape = true;
        });
        pop.addEventListener('toggle', function (e) {
            var open = e.newState === 'open';
            if (!open && pop._corrEscape && pop._corr.button.isConnected) pop._corr.button.focus();
            pop._corrEscape = false;
            if (open) position();
            window[open ? 'addEventListener' : 'removeEventListener']('resize', position);
            window[open ? 'addEventListener' : 'removeEventListener']('scroll', position, true);
        });
        pop.addEventListener('change', function (e) {
            var box = e.target;
            var type = box.getAttribute('data-event-type') || 'unknown';
            var sev = box.getAttribute('data-event-severity');
            if (sev) pop._corr.options.filter.severity(type)[sev] = box.checked;
            else pop._corr.options.filter.types[type] = box.checked;
            pop._corr.options.onFilterChange();
        });
        return pop;
    }

    /* Renders the legend into el. options: {visible, filter, T, eventColor, onToggle(), onFilterChange()}. */
    function render(el, list, options) {
        var T = options.T;
        var hint = T.correlation_toggle_hint || 'Click to toggle';
        var filterLabel = escapeAttr(T.correlation_event_filter || 'Event Filter');
        // The legend is rebuilt on every redraw; keyboard focus stays on the same control.
        var focused = el.contains(document.activeElement) ? document.activeElement : null;
        var focusSelector = focused && focused.classList.contains('corr-event-filter-btn') ? '.corr-event-filter-btn'
            : focused && focused.getAttribute('data-metric') ? '[data-metric="' + focused.getAttribute('data-metric') + '"]' : null;
        el.innerHTML = docsightHTML(list.map(function (item) {
            var on = !!options.visible[item.metric];
            var attrs = 'data-metric="' + item.metric + '" tabindex="0" role="button" aria-pressed="' + on + '"';
            var extra = '';
            var gear = '';
            var cls = on ? '' : 'disabled';
            if (item.events) {
                cls = cls ? cls + ' corr-legend-events' : 'corr-legend-events';
                if (item.events.visible < item.events.total) {
                    extra = ' <span class="corr-legend-filter-count">(' + item.events.visible + '/' + item.events.total + ')</span>';
                }
                gear = '<button type="button" class="corr-event-filter-btn" popovertarget="corr-event-popover" aria-label="' + filterLabel +
                    '" title="' + filterLabel + '"><i data-lucide="sliders-horizontal" aria-hidden="true"></i></button>';
            }
            return '<span ' + attrs + ' class="' + cls + '" title="' + hint + '" data-color="' + escapeAttr(item.color) + '">' + item.label + extra + '</span>' + gear;
        }).join(''));
        applyColors(el);
        if (typeof lucide !== 'undefined') lucide.createIcons({nodes: [el]});

        var button = el.querySelector('.corr-event-filter-btn');
        var eventsItem = list.filter(function (item) { return item.events; })[0];
        if (button && eventsItem) {
            eventPopover(el)._corr = {button: button, events: eventsItem.events, options: options};
        }
        el.querySelectorAll('span[data-metric]').forEach(function (span) {
            span.addEventListener('click', function () {
                if (toggle(options.visible, this.getAttribute('data-metric'))) options.onToggle();
            });
            span.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.click();
                }
            });
        });
        var refocus = focusSelector && el.querySelector(focusSelector);
        if (refocus) refocus.focus();
    }

    return {
        eventFilter: eventFilter,
        items: items,
        toggle: toggle,
        escapeAttr: escapeAttr,
        applyColors: applyColors,
        closePopover: closePopover,
        render: render
    };
});
