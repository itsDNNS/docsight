/* ── Shared empty state ──
   One look for every view without content: an icon, a title, one sentence on
   why the view is empty, one primary action and an optional glossary link.
   Templates render the same markup through partials/empty_state.html; views
   switch states at runtime with show(), showRange(), showError() and hide(). */
(function (root, factory) {
    'use strict';
    var api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) Object.defineProperty(root, 'DOCSightEmptyState', {
        configurable: false,
        writable: false,
        value: api
    });
})(typeof window !== 'undefined' ? window : null, function () {
    'use strict';

    function text(key, fallback) {
        return (typeof T !== 'undefined' && T && T[key]) || fallback;
    }

    function url(path) {
        return typeof docsightUrl === 'function' ? docsightUrl(path) : path;
    }

    /* Range tabs are ordered short to long. The longest one is the useful next
       step unless it is already selected. */
    function widerRange(tabs) {
        if (!tabs || !tabs.length) return null;
        var longest = tabs[tabs.length - 1];
        return longest.active ? null : longest;
    }

    function rangeTabs(tabsId) {
        var group = typeof document !== 'undefined' && document.getElementById(tabsId);
        if (!group) return [];
        return Array.prototype.slice.call(group.querySelectorAll('.trend-tab[data-value], .trend-tab[data-range], .trend-tab[data-days], .trend-tab[data-cm-range]'))
            .map(function (tab) {
                return {el: tab, label: tab.textContent.trim(), active: tab.classList.contains('active')};
            });
    }

    function element(tag, className, content) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (content) node.textContent = content;
        return node;
    }

    function show(el, opts) {
        if (!el) return;
        var options = opts || {};
        el.classList.add('view-empty');
        el.setAttribute('role', 'status');
        el.textContent = '';

        var icon = element('span', 'view-empty-icon');
        icon.setAttribute('aria-hidden', 'true');
        var glyph = document.createElement('i');
        glyph.setAttribute('data-lucide', options.icon || 'info');
        icon.appendChild(glyph);
        el.appendChild(icon);
        el.appendChild(element('p', 'view-empty-title', options.title || ''));
        if (options.text) el.appendChild(element('p', 'view-empty-text', options.text));

        var actions = element('div', 'view-empty-actions');
        var action = options.action;
        if (action && action.label) {
            var control;
            if (action.href) {
                control = element('a', 'btn btn-primary view-empty-action', action.label);
                control.href = action.href;
            } else {
                control = element('button', 'btn btn-primary view-empty-action', action.label);
                control.type = 'button';
                control.addEventListener('click', action.onClick);
            }
            actions.appendChild(control);
        }
        if (options.glossary) {
            var link = element('a', 'view-empty-link', text('empty_glossary_link', 'What does this view show?'));
            link.href = '#glossary?term=' + encodeURIComponent(options.glossary);
            actions.appendChild(link);
        }
        if (actions.childNodes.length) el.appendChild(actions);

        el.style.display = '';
        el.hidden = false;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    function hide(el) {
        if (!el) return;
        el.hidden = true;
        el.style.display = '';
    }

    /* No data in the selected range: offer the longest range, or, when that is
       already selected, point at the modem connection. Views whose data comes
       from elsewhere pass their own `none` state for that second case. */
    function showRange(el, opts) {
        var options = opts || {};
        var wider = widerRange(rangeTabs(options.tabs));
        if (wider) {
            show(el, {
                icon: 'clock',
                title: options.title || text('empty_range_title', 'No data in this period'),
                text: options.text || text('empty_range_text', 'There are no measurements for the selected period. A longer period may contain older data.'),
                action: {
                    label: text('empty_action_range', 'Show {range}').replace('{range}', wider.label),
                    onClick: function () { wider.el.click(); }
                },
                glossary: options.glossary
            });
            return;
        }
        var none = options.none || {};
        show(el, {
            icon: none.icon || 'plug',
            title: none.title || text('empty_none_title', 'No measurements yet'),
            text: none.text || text('empty_none_text', 'Measurements start with the first successful modem poll. If this stays empty, check the modem connection.'),
            action: none.action || {label: text('empty_action_connection', 'Check modem connection'), href: url('/settings#connection')},
            glossary: options.glossary
        });
    }

    function showError(el, opts) {
        var options = opts || {};
        show(el, {
            icon: 'triangle-alert',
            title: text('empty_error_title', 'Could not load the data'),
            text: options.text || text('empty_error_text', 'The request failed. This is usually temporary.'),
            action: options.retry ? {label: text('empty_action_retry', 'Try again'), onClick: options.retry} : null,
            glossary: options.glossary
        });
    }

    return {
        widerRange: widerRange,
        show: show,
        showRange: showRange,
        showError: showError,
        hide: hide
    };
});
