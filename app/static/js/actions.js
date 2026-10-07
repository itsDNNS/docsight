/* ═══ DOCSight delegated actions ═══
   Server-rendered markup names its handlers in data attributes instead of
   inline on* attributes:
     data-action="fn"          click calls window.fn(...args)
     data-change-action="fn"   change calls window.fn(...args)
     data-action-args="[...]"  JSON arguments for either (optional)
     data-action-pass="element" either also gets the element as its first argument
     data-pill-action="fn"     on a .segmented group: a tab click selects the tab, then calls fn
     data-dialog-close="fn"    on a <dialog>: a backdrop click or Escape calls fn
     data-click-target="sel"   click forwards to the first element matching the selector
     data-focus-target="sel"   click focuses the first element matching the selector
     data-toggle-open          click toggles the "open" class and aria-expanded
     data-toggle-open="parent" the same, with the "open" class on the parent element
     data-toggle-open="<sel>"  the same, with the "open" class on the closest match
   Elements with role="button" also run their click action on Enter and Space.
   A click on a control nested inside an action element (a link, button, form
   field or glossary hint) belongs to that control, not to the outer action. */
(function() {
    'use strict';

    var NESTED_CONTROLS = 'a[href], button, input, select, textarea, .glossary-hint';

    function callNamed(el, attr) {
        var fn = window[el.getAttribute(attr)];
        if (typeof fn !== 'function') return;
        var args = el.getAttribute('data-action-args');
        args = args ? JSON.parse(args) : [];
        if (el.getAttribute('data-action-pass') === 'element') args.unshift(el);
        fn.apply(null, args);
    }

    function targetOf(el, attr) {
        return document.querySelector(el.getAttribute(attr));
    }

    document.addEventListener('click', function(event) {
        var target = event.target;
        if (!(target instanceof Element)) return;

        var dialog = target.closest('dialog[data-dialog-close]');
        if (dialog && target === dialog) {
            callNamed(dialog, 'data-dialog-close');
            return;
        }

        var tab = target.closest('[data-pill-action] > .segmented-option');
        if (tab) {
            window.selectPill(tab, window[tab.parentElement.getAttribute('data-pill-action')]);
            return;
        }

        var el = target.closest('[data-action], [data-click-target], [data-focus-target], [data-toggle-open]');
        if (!el) return;
        var control = target.closest(NESTED_CONTROLS);
        if (control && control !== el && el.contains(control)) return;
        if (el.hasAttribute('data-action')) {
            callNamed(el, 'data-action');
        } else if (el.hasAttribute('data-click-target')) {
            var forwardTo = targetOf(el, 'data-click-target');
            if (forwardTo) forwardTo.click();
        } else if (el.hasAttribute('data-focus-target')) {
            var focusOn = targetOf(el, 'data-focus-target');
            if (focusOn) focusOn.focus();
        } else {
            var scope = el.getAttribute('data-toggle-open');
            var holder = scope === 'parent' ? el.parentElement : (scope ? el.closest(scope) : el) || el;
            holder.classList.toggle('open');
            el.setAttribute('aria-expanded', String(holder.classList.contains('open')));
        }
    });

    document.addEventListener('change', function(event) {
        var el = event.target instanceof Element && event.target.closest('[data-change-action]');
        if (el) callNamed(el, 'data-change-action');
    });

    document.addEventListener('keydown', function(event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        var el = event.target;
        if (!(el instanceof Element) || el.getAttribute('role') !== 'button') return;
        if (!el.matches('[data-action], [data-toggle-open]')) return;
        event.preventDefault();
        el.click();
    });

    /* "cancel" does not bubble; listen while it travels down to the dialog. */
    document.addEventListener('cancel', function(event) {
        var dialog = event.target;
        if (!(dialog instanceof Element) || !dialog.matches('dialog[data-dialog-close]')) return;
        event.preventDefault();
        callNamed(dialog, 'data-dialog-close');
    }, true);
})();
