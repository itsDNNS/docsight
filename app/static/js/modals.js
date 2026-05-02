/* ═══ DOCSight modal helpers ═══ */
(function() {
    'use strict';

    var activeStack = [];
    var lastOpener = new WeakMap();
    var confirmState = null;

    var FOCUSABLE = [
        'a[href]',
        'area[href]',
        'button:not([disabled])',
        'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        'iframe',
        '[tabindex]:not([tabindex="-1"])',
        '[contenteditable="true"]'
    ].join(',');

    function getModal(idOrEl) {
        if (!idOrEl) return null;
        if (typeof idOrEl === 'string') return document.getElementById(idOrEl.replace(/^#/, ''));
        return idOrEl;
    }

    function isOpen(modal) {
        return !!modal && (modal.classList.contains('open') || modal.style.display === 'flex' || modal.getAttribute('data-modal-open') === 'true');
    }

    function focusables(modal) {
        return Array.prototype.slice.call(modal.querySelectorAll(FOCUSABLE)).filter(function(el) {
            return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && el.getAttribute('aria-hidden') !== 'true';
        });
    }

    function firstFocusTarget(modal) {
        return modal.querySelector('[data-modal-initial-focus]') || focusables(modal)[0] || modal;
    }

    function ensureModalSemantics(modal) {
        if (!modal) return;
        if (!modal.hasAttribute('role')) modal.setAttribute('role', 'dialog');
        if (!modal.hasAttribute('aria-modal')) modal.setAttribute('aria-modal', 'true');
        if (!modal.hasAttribute('tabindex')) modal.setAttribute('tabindex', '-1');
        modal.querySelectorAll('.modal-close, .btn-icon').forEach(function(btn) {
            if (!btn.getAttribute('aria-label')) {
                btn.setAttribute('aria-label', (window.T && (T.close || T.cancel)) || 'Close');
            }
        });
    }

    function activate(modal, opener) {
        if (!modal) return;
        ensureModalSemantics(modal);
        if (opener) lastOpener.set(modal, opener);
        if (activeStack.indexOf(modal) === -1) activeStack.push(modal);
        window.setTimeout(function() {
            if (!isOpen(modal)) return;
            var target = firstFocusTarget(modal);
            if (target && typeof target.focus === 'function') target.focus({preventScroll: true});
        }, 0);
    }

    function deactivate(modal) {
        if (!modal) return;
        activeStack = activeStack.filter(function(item) { return item !== modal; });
        var opener = lastOpener.get(modal);
        if (opener && document.contains(opener) && typeof opener.focus === 'function') {
            window.setTimeout(function() { opener.focus({preventScroll: true}); }, 0);
        }
    }

    function openModal(idOrEl, options) {
        var modal = getModal(idOrEl);
        if (!modal) return null;
        var opts = options || {};
        if (opts.labelledBy && !modal.getAttribute('aria-labelledby')) {
            modal.setAttribute('aria-labelledby', opts.labelledBy);
        }
        if (opts.dismissible === false) modal.setAttribute('data-modal-dismissible', 'false');
        modal.classList.add('open');
        modal.style.display = modal.classList.contains('browse-modal-overlay') ? 'flex' : '';
        modal.setAttribute('data-modal-open', 'true');
        activate(modal, opts.opener || document.activeElement);
        return modal;
    }

    function closeModal(idOrEl, options) {
        var modal = getModal(idOrEl);
        if (!modal) return;
        var opts = options || {};
        modal.classList.remove('open');
        modal.removeAttribute('data-modal-open');
        if (modal.classList.contains('browse-modal-overlay') || opts.hideDisplay) modal.style.display = 'none';
        deactivate(modal);
    }

    function topModal() {
        for (var i = activeStack.length - 1; i >= 0; i--) {
            if (isOpen(activeStack[i])) return activeStack[i];
        }
        return null;
    }

    function handleTab(event, modal) {
        var items = focusables(modal);
        if (!items.length) {
            event.preventDefault();
            modal.focus({preventScroll: true});
            return;
        }
        var first = items[0];
        var last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus({preventScroll: true});
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus({preventScroll: true});
        } else if (!modal.contains(document.activeElement)) {
            event.preventDefault();
            first.focus({preventScroll: true});
        }
    }

    document.addEventListener('keydown', function(event) {
        var modal = topModal();
        if (!modal) return;
        if (event.key === 'Tab') {
            handleTab(event, modal);
            return;
        }
        if (event.key === 'Escape' && modal.getAttribute('data-modal-dismissible') !== 'false') {
            event.preventDefault();
            if (modal.id === 'docsight-confirm-modal' && confirmState) {
                resolveConfirm(false);
            } else if (modal.id) {
                closeModal(modal, {hideDisplay: modal.classList.contains('browse-modal-overlay')});
            }
        }
    }, true);

    document.addEventListener('focusin', function() {
        var modal = topModal();
        if (!modal || modal.contains(document.activeElement)) return;
        var target = firstFocusTarget(modal);
        if (target && typeof target.focus === 'function') target.focus({preventScroll: true});
    });

    document.addEventListener('click', function(event) {
        var modal = topModal();
        if (!modal || event.target !== modal || modal.getAttribute('data-modal-dismissible') === 'false') return;
        closeModal(modal, {hideDisplay: modal.classList.contains('browse-modal-overlay')});
    });

    function createConfirmModal() {
        var existing = document.getElementById('docsight-confirm-modal');
        if (existing) return existing;
        var modal = document.createElement('div');
        modal.id = 'docsight-confirm-modal';
        modal.className = 'modal-overlay docsight-confirm-overlay';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', 'docsight-confirm-title');
        modal.innerHTML = [
            '<div class="modal docsight-confirm-modal" style="max-width:520px;">',
            '  <div class="modal-header">',
            '    <h2 id="docsight-confirm-title"></h2>',
            '    <button type="button" class="modal-close" id="docsight-confirm-x" aria-label="Close">&times;</button>',
            '  </div>',
            '  <div class="modal-body">',
            '    <p id="docsight-confirm-message" class="docsight-confirm-message"></p>',
            '    <label id="docsight-confirm-typed-wrap" class="docsight-confirm-typed-wrap" style="display:none;">',
            '      <span id="docsight-confirm-typed-label"></span>',
            '      <input id="docsight-confirm-typed-input" class="docsight-confirm-typed-input" autocomplete="off" spellcheck="false">',
            '    </label>',
            '  </div>',
            '  <div class="incident-modal-footer">',
            '    <div class="modal-footer-left"></div>',
            '    <div style="display:flex; gap:10px;">',
            '      <button type="button" class="btn btn-muted" id="docsight-confirm-cancel"></button>',
            '      <button type="button" class="btn btn-accent" id="docsight-confirm-ok"></button>',
            '    </div>',
            '  </div>',
            '</div>'
        ].join('');
        modal.addEventListener('click', function(event) {
            if (event.target === modal) resolveConfirm(false);
        });
        document.body.appendChild(modal);
        document.getElementById('docsight-confirm-x').addEventListener('click', function() { resolveConfirm(false); });
        document.getElementById('docsight-confirm-cancel').addEventListener('click', function() { resolveConfirm(false); });
        document.getElementById('docsight-confirm-ok').addEventListener('click', function() { resolveConfirm(true); });
        var typedInput = document.getElementById('docsight-confirm-typed-input');
        typedInput.addEventListener('input', updateConfirmOk);
        typedInput.addEventListener('keydown', function(event) {
            if (event.key !== 'Enter' || !confirmState) return;
            updateConfirmOk();
            if (document.getElementById('docsight-confirm-ok').disabled) return;
            event.preventDefault();
            resolveConfirm(true);
        });
        return modal;
    }

    function updateConfirmOk() {
        if (!confirmState) return;
        var ok = document.getElementById('docsight-confirm-ok');
        var typed = document.getElementById('docsight-confirm-typed-input');
        if (confirmState.requireText) {
            ok.disabled = typed.value !== confirmState.requireText;
        } else {
            ok.disabled = false;
        }
    }

    function resolveConfirm(value) {
        if (!confirmState) return;
        var state = confirmState;
        confirmState = null;
        closeModal('docsight-confirm-modal');
        state.resolve(value);
    }

    function docsightConfirm(options) {
        var opts = typeof options === 'string' ? {message: options} : (options || {});
        var modal = createConfirmModal();
        if (confirmState) resolveConfirm(false);
        document.getElementById('docsight-confirm-title').textContent = opts.title || (window.T && T.confirm_title) || 'Confirm action';
        document.getElementById('docsight-confirm-message').textContent = opts.message || '';
        document.getElementById('docsight-confirm-cancel').textContent = opts.cancelText || (window.T && T.cancel) || 'Cancel';
        var ok = document.getElementById('docsight-confirm-ok');
        ok.textContent = opts.confirmText || (window.T && T.confirm) || 'Confirm';
        ok.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-accent');
        var typedWrap = document.getElementById('docsight-confirm-typed-wrap');
        var typedLabel = document.getElementById('docsight-confirm-typed-label');
        var typedInput = document.getElementById('docsight-confirm-typed-input');
        typedInput.value = '';
        if (opts.requireText) {
            typedWrap.style.display = '';
            typedLabel.textContent = opts.requireLabel || ('Type ' + opts.requireText + ' to confirm');
            typedInput.setAttribute('data-modal-initial-focus', '');
        } else {
            typedWrap.style.display = 'none';
            typedInput.removeAttribute('data-modal-initial-focus');
        }
        return new Promise(function(resolve) {
            confirmState = {resolve: resolve, requireText: opts.requireText || ''};
            updateConfirmOk();
            openModal(modal, {opener: document.activeElement});
        });
    }

    function observeExistingModals() {
        document.querySelectorAll('.modal-overlay, .browse-modal-overlay, .chart-zoom-overlay').forEach(function(modal) {
            ensureModalSemantics(modal);
            var observer = new MutationObserver(function() {
                if (isOpen(modal)) activate(modal, document.activeElement);
                else deactivate(modal);
            });
            observer.observe(modal, {attributes: true, attributeFilter: ['class', 'style', 'data-modal-open']});
        });
    }

    document.addEventListener('DOMContentLoaded', observeExistingModals);

    window.DOCSightModal = {
        open: openModal,
        close: closeModal,
        confirm: docsightConfirm
    };
    window.docsightConfirm = docsightConfirm;
})();
