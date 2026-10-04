/* ── Home line status: tap a channel segment to see its last 24 hours ──
   Depends on: T, window.DOCSightStatusTrack (channels.js).
   The dashboard refresh replaces the markup, so all handlers are delegated. */
(function() {
    'use strict';

    function strip(seg) {
        return seg.closest('.line-status-strip');
    }

    function segments(group) {
        return Array.prototype.slice.call(group.querySelectorAll('.ls-seg[data-selector]'));
    }

    function panelFor(seg) {
        return document.getElementById(seg.getAttribute('aria-controls'));
    }

    function close(panel, focusSegment) {
        if (!panel || panel.hidden) return;
        var open = document.querySelector('.ls-seg[aria-controls="' + panel.id + '"][aria-expanded="true"]');
        panel.hidden = true;
        panel.textContent = '';
        if (open) {
            open.setAttribute('aria-expanded', 'false');
            open.classList.remove('ls-selected');
            if (focusSegment) open.focus();
        }
    }

    function show(seg) {
        var panel = panelFor(seg);
        if (!panel || !window.DOCSightStatusTrack) return;
        if (seg.getAttribute('aria-expanded') === 'true') {
            close(panel, false);
            return;
        }
        close(panel, false);
        seg.setAttribute('aria-expanded', 'true');
        seg.classList.add('ls-selected');

        var head = document.createElement('div');
        head.className = 'ls-detail-head';
        var title = document.createElement('span');
        title.className = 'ls-detail-title';
        title.textContent = (T.line_status_last_day || 'Last 24 hours') + ' · ' + seg.getAttribute('aria-label');
        var dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.className = 'ls-detail-close';
        dismiss.setAttribute('aria-label', T.close || 'Close');
        dismiss.textContent = '×';
        dismiss.addEventListener('click', function() { close(panel, true); });
        var stepper = document.createElement('span');
        stepper.className = 'ls-detail-actions';
        var list = segments(strip(seg));
        var index = list.indexOf(seg);
        // Segments are narrow on phones; stepping is easier than hitting the neighbour.
        [[-1, '\u2039', T.line_status_previous_channel || 'Previous channel'],
         [1, '\u203a', T.line_status_next_channel || 'Next channel']].forEach(function(step) {
            var target = list[index + step[0]];
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'ls-detail-step';
            button.dataset.step = step[0];
            button.setAttribute('aria-label', step[2]);
            button.textContent = step[1];
            button.disabled = !target;
            if (target) button.addEventListener('click', function() { select(target, step[0]); });
            stepper.appendChild(button);
        });
        stepper.appendChild(dismiss);
        head.appendChild(title);
        head.appendChild(stepper);

        var track = document.createElement('div');
        track.className = 'status-track ls-detail-track';
        track.id = panel.id + '-track';
        panel.textContent = '';
        panel.appendChild(head);
        panel.appendChild(track);
        panel.hidden = false;
        window.DOCSightStatusTrack.loadChannelDay(track, seg.dataset.direction, seg.dataset.selector);
    }

    /* Moves the open detail to another segment and keeps the roving tab stop on it. */
    function select(target, step) {
        segments(strip(target)).forEach(function(item) { item.tabIndex = item === target ? 0 : -1; });
        show(target);
        var panel = panelFor(target);
        if (!panel) return;
        // Keep focus on the button that was used; at the end of the strip fall back to the other one.
        var same = panel.querySelector('.ls-detail-step[data-step="' + step + '"]:not([disabled])')
            || panel.querySelector('.ls-detail-step:not([disabled])');
        if (same) same.focus();
    }

    /* Roving focus: one tab stop per strip, arrow keys move between channels. */
    function move(seg, key) {
        var list = segments(strip(seg));
        var index = list.indexOf(seg);
        var next = index;
        if (key === 'ArrowRight' || key === 'ArrowDown') next = Math.min(list.length - 1, index + 1);
        else if (key === 'ArrowLeft' || key === 'ArrowUp') next = Math.max(0, index - 1);
        else if (key === 'Home') next = 0;
        else if (key === 'End') next = list.length - 1;
        else return false;
        list.forEach(function(item, i) { item.tabIndex = i === next ? 0 : -1; });
        list[next].focus();
        return true;
    }

    document.addEventListener('click', function(event) {
        var seg = event.target.closest ? event.target.closest('.line-status .ls-seg[data-selector]') : null;
        if (seg) show(seg);
    });

    document.addEventListener('keydown', function(event) {
        var target = event.target;
        if (!target || !target.closest) return;
        var seg = target.closest('.line-status .ls-seg[data-selector]');
        if (seg && move(seg, event.key)) {
            event.preventDefault();
            return;
        }
        if (event.key === 'Escape') {
            var panel = target.closest('.ls-detail') || (seg && panelFor(seg));
            if (panel && !panel.hidden) {
                event.preventDefault();
                close(panel, true);
            }
        }
    });
})();
