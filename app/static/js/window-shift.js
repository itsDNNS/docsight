/* ── Window shift ──
   A time-range window ends now unless the user moves it into the past with
   the arrows next to the range picker (or a swipe over the charts on a phone).
   Each step moves it by its own length. A window in the past shows its span
   and a "Back to now" button. The end travels as wall-clock time in DOCSight's
   zone ("YYYY-MM-DDTHH:MM"), the same as in the deep link and the APIs. */
/* global DOCSightBrowserContracts, DOCSIGHT_TIME_ZONE, formatDocsightTime */
var DOCSightWindowShift = (function() {
    'use strict';

    var MINUTE_MS = 60000;
    var SWIPE_MIN_PX = 60;
    var SWIPE_MAX_MS = 800;
    var HINT_STORAGE_KEY = 'docsight.windowShift.swiped';

    function toParam(ms) {
        return DOCSightBrowserContracts.localInputValue(ms, DOCSIGHT_TIME_ZONE, false);
    }

    function fromParam(value) {
        if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return null;
        var ms = DOCSightBrowserContracts.parseTimestamp(value, DOCSIGHT_TIME_ZONE).getTime();
        return isNaN(ms) ? null : ms;
    }

    function swiped() {
        try { return window.localStorage.getItem(HINT_STORAGE_KEY) === '1'; } catch (e) { return false; }
    }

    function rememberSwipe() {
        try { window.localStorage.setItem(HINT_STORAGE_KEY, '1'); } catch (e) { /* optional */ }
    }

    /**
     * prefix: id prefix of the window_shift and window_past macros.
     * opts.hours(): length of the selected range in hours.
     * opts.onChange(): called after the user moved the window.
     * opts.swipeArea: element whose charts take a horizontal swipe.
     * opts.swipeTarget: selector of the chart surfaces in it (uPlot plots by default).
     */
    function create(prefix, opts) {
        var earlier = document.getElementById(prefix + '-window-earlier');
        var later = document.getElementById(prefix + '-window-later');
        var bar = document.getElementById(prefix + '-window-past');
        var range = document.getElementById(prefix + '-window-range');
        var now = document.getElementById(prefix + '-window-now');
        var hint = document.getElementById(prefix + '-window-hint');
        var end = null;
        var leftNowAt = null; // the minute the window left "now", for the way back

        function sync() {
            var past = end !== null;
            if (later) later.disabled = !past;
            if (bar) bar.hidden = !past;
            if (past && range) {
                var start = end - opts.hours() * 3600 * 1000;
                range.textContent = formatDocsightTime(start, 'monthday-time') + ' – ' + formatDocsightTime(end, 'monthday-time');
            }
            if (hint) hint.hidden = !(window.matchMedia && window.matchMedia('(pointer: coarse)').matches) || swiped();
        }

        // An end within a minute of now is now, so the window follows new polls again.
        function set(value) {
            end = value !== null && value !== undefined && value < Date.now() - MINUTE_MS
                ? Math.floor(value / MINUTE_MS) * MINUTE_MS : null;
            if (end === null) leftNowAt = null;
            sync();
        }

        function step(direction) {
            if (direction > 0 && end === null) return false;
            var length = opts.hours() * 3600 * 1000;
            if (end === null) leftNowAt = Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
            var next = (end === null ? Date.now() : end) + direction * length;
            // Stepping forward to where the window left "now" is "now" again, however
            // long the user looked at the past windows.
            set(direction > 0 && leftNowAt !== null && next >= leftNowAt ? null : next);
            opts.onChange();
            return true;
        }

        if (earlier) earlier.addEventListener('click', function() { step(-1); });
        if (later) later.addEventListener('click', function() { step(1); });
        if (now) now.addEventListener('click', function() { set(null); opts.onChange(); });

        // A quick horizontal swipe steps the window: right for earlier, left for
        // later. Press and hold reads values instead (.is-scrubbing), not a swipe.
        var area = opts.swipeArea;
        var surface = opts.swipeTarget || '.u-over';
        if (area) {
            var start = null;
            area.addEventListener('touchstart', function(event) {
                var touch = event.touches.length === 1 ? event.touches[0] : null;
                start = touch && touch.target.closest && touch.target.closest(surface)
                    ? {x: touch.clientX, y: touch.clientY, time: Date.now(), scrub: false} : null;
            }, {passive: true});
            area.addEventListener('touchmove', function() {
                if (start && area.querySelector('.is-scrubbing')) start.scrub = true;
            }, {passive: true});
            area.addEventListener('touchend', function(event) {
                var from = start;
                start = null;
                if (!from || from.scrub || Date.now() - from.time > SWIPE_MAX_MS) return;
                var touch = event.changedTouches[0];
                var dx = touch.clientX - from.x;
                var dy = touch.clientY - from.y;
                if (Math.abs(dx) < SWIPE_MIN_PX || Math.abs(dy) > Math.abs(dx) / 2) return;
                if (step(dx > 0 ? -1 : 1)) rememberSwipe();
                sync();
            }, {passive: true});
        }

        return {
            /** End of the window as a URL/API parameter, or null while it ends now. */
            param: function() { return end === null ? null : toParam(end); },
            /** Restore the end from a deep link parameter without notifying. */
            restore: function(value) { set(fromParam(value)); },
            /** Redraw the span, e.g. after the range changed. */
            sync: sync,
            step: step
        };
    }

    return {create: create, toParam: toParam, fromParam: fromParam};
})();
