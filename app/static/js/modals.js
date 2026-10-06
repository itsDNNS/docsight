/* ═══ DOCSight modal helpers ═══ */
(function() {
    'use strict';

    var confirmState = null;

    function getDialog(idOrEl) {
        if (!idOrEl) return null;
        if (typeof idOrEl === 'string') {
            return document.getElementById(idOrEl.replace(/^#/, ''));
        }
        return idOrEl;
    }

    function prepareDialog(dialog) {
        if (!dialog || dialog.dataset.docsightDialogReady === 'true') return;
        dialog.dataset.docsightDialogReady = 'true';
        dialog.addEventListener('cancel', function(event) {
            if (dialog.getAttribute('data-modal-dismissible') === 'false') {
                event.preventDefault();
            }
        });
        dialog.addEventListener('close', function() {
            dialog.classList.remove('open');
        });
    }

    function openModal(idOrEl, options) {
        var dialog = getDialog(idOrEl);
        if (!dialog) return null;
        var opts = options || {};
        if (opts.labelledBy && !dialog.getAttribute('aria-labelledby')) {
            dialog.setAttribute('aria-labelledby', opts.labelledBy);
        }
        if (opts.dismissible === false) {
            dialog.setAttribute('data-modal-dismissible', 'false');
        }
        prepareDialog(dialog);
        if (opts.opener && opts.opener !== document.activeElement && typeof opts.opener.focus === 'function') {
            opts.opener.focus({preventScroll: true});
        }
        if (!dialog.open) {
            dialog.showModal();
            focusInitial(dialog);
        }
        dialog.classList.add('open');
        return dialog;
    }

    /* The browser focuses the first focusable element, usually the close
       button. Start at an [autofocus] element, the first field of the body
       or the footer's primary action instead; a dialog whose main action is
       destructive starts on its safe secondary button. */
    var INITIAL_FOCUS = [
        '[autofocus]',
        '.modal-body input:not([type="hidden"]):not([disabled]), .modal-body select:not([disabled]), .modal-body textarea:not([disabled])',
        '.modal-footer > .btn-primary:not([disabled])',
        '.modal-footer > .btn-secondary:not([disabled])'
    ];

    function focusInitial(dialog) {
        for (var i = 0; i < INITIAL_FOCUS.length; i++) {
            var candidates = dialog.querySelectorAll(INITIAL_FOCUS[i]);
            for (var j = 0; j < candidates.length; j++) {
                if (candidates[j].offsetParent !== null) {
                    candidates[j].focus();
                    return;
                }
            }
        }
    }

    function closeModal(idOrEl) {
        var dialog = getDialog(idOrEl);
        if (!dialog) return;
        dialog.classList.remove('open');
        if (dialog.open) dialog.close();
    }

    document.addEventListener('click', function(event) {
        var dialog = event.target;
        if (!dialog || dialog.tagName !== 'DIALOG' || !dialog.open) return;
        if (dialog.getAttribute('data-modal-dismissible') === 'false') return;
        if (dialog.id === 'docsight-confirm-modal' && confirmState) {
            resolveConfirm(false);
        } else {
            closeModal(dialog);
        }
    });

    function createConfirmModal() {
        var existing = document.getElementById('docsight-confirm-modal');
        if (existing) return existing;
        var dialog = document.createElement('dialog');
        dialog.id = 'docsight-confirm-modal';
        dialog.className = 'modal-overlay docsight-confirm-overlay';
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'docsight-confirm-title');
        dialog.innerHTML = [
            '<div class="modal">',
            '  <div class="modal-header">',
            '    <h2 id="docsight-confirm-title"></h2>',
            '    <button type="button" class="modal-close" id="docsight-confirm-x" aria-label="Close">&times;</button>',
            '  </div>',
            '  <div class="modal-body">',
            '    <p id="docsight-confirm-message" class="docsight-confirm-message"></p>',
            '    <label id="docsight-confirm-typed-wrap" class="docsight-confirm-typed-wrap" hidden>',
            '      <span id="docsight-confirm-typed-label"></span>',
            '      <input id="docsight-confirm-typed-input" class="docsight-confirm-typed-input" autocomplete="off" spellcheck="false">',
            '    </label>',
            '  </div>',
            '  <div class="modal-footer">',
            '    <button type="button" class="btn btn-secondary" id="docsight-confirm-cancel"></button>',
            '    <button type="button" class="btn btn-primary" id="docsight-confirm-ok"></button>',
            '  </div>',
            '</div>'
        ].join('');
        dialog.addEventListener('click', function(event) {
            if (event.target === dialog) resolveConfirm(false);
        });
        dialog.addEventListener('cancel', function(event) {
            event.preventDefault();
            resolveConfirm(false);
        });
        document.body.appendChild(dialog);
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
        return dialog;
    }

    function updateConfirmOk() {
        if (!confirmState) return;
        var ok = document.getElementById('docsight-confirm-ok');
        var typed = document.getElementById('docsight-confirm-typed-input');
        ok.disabled = !!confirmState.requireText && typed.value !== confirmState.requireText;
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
        var dialog = createConfirmModal();
        if (confirmState) resolveConfirm(false);
        document.getElementById('docsight-confirm-title').textContent = opts.title || (window.T && T.confirm_title) || 'Confirm action';
        document.getElementById('docsight-confirm-message').textContent = opts.message || '';
        document.getElementById('docsight-confirm-cancel').textContent = opts.cancelText || (window.T && T.cancel) || 'Cancel';
        var ok = document.getElementById('docsight-confirm-ok');
        ok.textContent = opts.confirmText || (window.T && T.confirm) || 'Confirm';
        ok.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-primary');
        var typedWrap = document.getElementById('docsight-confirm-typed-wrap');
        var typedLabel = document.getElementById('docsight-confirm-typed-label');
        var typedInput = document.getElementById('docsight-confirm-typed-input');
        typedInput.value = '';
        if (opts.requireText) {
            typedWrap.hidden = false;
            typedLabel.textContent = opts.requireLabel || ('Type ' + opts.requireText + ' to confirm');
            typedInput.setAttribute('autofocus', '');
        } else {
            typedWrap.hidden = true;
            typedInput.removeAttribute('autofocus');
        }
        return new Promise(function(resolve) {
            confirmState = {resolve: resolve, requireText: opts.requireText || ''};
            updateConfirmOk();
            openModal(dialog);
        });
    }

    window.DOCSightModal = {
        open: openModal,
        close: closeModal,
        confirm: docsightConfirm
    };
    window.docsightConfirm = docsightConfirm;
})();
