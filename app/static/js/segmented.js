/* ── Segmented control ──
   One group of mutually exclusive options (`.segmented` in components.css). The
   chosen option carries .active for the look and aria-pressed for assistive tech. */
(function(global) {
    'use strict';

    function options(group) {
        return group ? Array.prototype.slice.call(group.querySelectorAll('.segmented-option')) : [];
    }

    function mark(option, selected) {
        option.classList.toggle('active', selected);
        option.setAttribute('aria-pressed', selected ? 'true' : 'false');
    }

    /* Select one option and clear the others in its group. */
    global.selectSegment = function(option) {
        options(option.closest('.segmented') || option.parentElement).forEach(function(other) {
            mark(other, other === option);
        });
    };

    /* Mark the options of a group (element or id) whose state changed without a click. */
    global.syncSegments = function(group, isSelected) {
        if (typeof group === 'string') group = document.getElementById(group);
        options(group).forEach(function(option) { mark(option, Boolean(isSelected(option))); });
    };
})(window);
