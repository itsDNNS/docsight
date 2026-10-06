'use strict';
DOCSightSettings.navigation = function({syncSaveFooter, onSection}) {
/* ── Section Controller ──
   Desktop shows the section index next to the content. Below 768px the index
   is a list and a section opens as its own view with a back button. */
var _currentSection = 'connection';
var _compactMedia = window.matchMedia ? window.matchMedia('(max-width: 768px)') : null;
var _openedFromList = false;

function _isCompact() {
    return !!(_compactMedia && _compactMedia.matches);
}

function _setDetail(detail) {
    var page = document.querySelector('.settings-page');
    if (page) page.classList.toggle('is-detail', detail);
}

function _applySection(id) {
    _currentSection = id;

    document.querySelectorAll('.settings-index-item[data-section]').forEach(function(link) {
        var isActive = link.getAttribute('data-section') === id;
        link.classList.toggle('active', isActive);
        if (isActive) {
            link.setAttribute('aria-current', 'page');
        } else {
            link.removeAttribute('aria-current');
        }
    });

    document.querySelectorAll('.settings-panel').forEach(function(panel) {
        panel.classList.remove('active');
    });
    var target = document.getElementById('panel-' + id);
    if (target) target.classList.add('active');

    var title = document.getElementById('settings-section-title');
    if (title) title.textContent = SECTION_TITLES[id] || id;
    var hint = document.getElementById('settings-save-hint');
    if (hint) {
        hint.textContent = target && target.getAttribute('data-save-hint') || T.settings_save_hint_manual || '';
        hint.hidden = !hint.textContent;
    }
    _setDetail(true);

    /* Save footer: hide on support/modules, otherwise respect dirty state */
    syncSaveFooter();

    /* Auto-load data for certain panels */
    onSection(id, target);
}

function _focusSectionTitle() {
    var title = document.getElementById('settings-section-title');
    if (!title) return;
    title.setAttribute('tabindex', '-1');
    title.focus({preventScroll: true});
}

/* User-initiated section change: apply and add a browser history entry so
   Back/Forward move between previously viewed settings sections. Re-selecting
   the current section replaces state instead of stacking a duplicate entry. */
function switchSection(id) {
    var isNewSection = id !== _currentSection || !location.hash;
    _applySection(id);
    if (isNewSection) {
        history.pushState(null, '', '#' + id);
    } else {
        history.replaceState(null, '', '#' + id);
    }
}

/* The compact list: no section is open. */
function showSectionList() {
    _setDetail(false);
    var active = document.querySelector('.settings-index-item.active') || document.querySelector('.settings-index-item');
    if (active) active.focus({preventScroll: true});
}

/* Resolve the section referenced by the current URL hash (default: connection).
   Addresses of earlier sections and module pages point at a block inside a
   section (id "block-<address>"); they open that section and scroll to it. */
var _pendingBlock = null;

function _sectionFromHash() {
    var hash = location.hash.replace('#', '');
    if (hash && document.getElementById('panel-' + hash)) return hash;
    var block = hash && document.getElementById('block-' + hash);
    var panel = block && block.closest('.settings-panel');
    if (panel) {
        _pendingBlock = block;
        return panel.id.replace(/^panel-/, '');
    }
    return 'connection';
}

function _revealPendingBlock() {
    var block = _pendingBlock;
    _pendingBlock = null;
    if (!block) return;
    history.replaceState(null, '', '#' + _currentSection);
    block.scrollIntoView({block: 'start'});
}

/* Non-pushing variant for Back/Forward and manual hash edits: the browser has
   already updated the URL, so only reflect it in the UI. The guard also makes
   the popstate+hashchange double-fire on navigation a no-op the second time. */
function _syncSectionFromHash() {
    if (!location.hash && _isCompact()) {
        _setDetail(false);
        return;
    }
    var id = _sectionFromHash();
    if (id === _currentSection && !_pendingBlock && document.querySelector('.settings-page.is-detail')) return;
    _applySection(id);
    _revealPendingBlock();
}

window.addEventListener('popstate', _syncSectionFromHash);
window.addEventListener('hashchange', _syncSectionFromHash);

function _initIndex() {
    var index = document.getElementById('settings-index');
    if (index) {
        index.addEventListener('click', function(event) {
            var item = event.target.closest('.settings-index-item[data-section]');
            if (!item) return;
            _openedFromList = _isCompact();
            switchSection(item.getAttribute('data-section'));
            if (_openedFromList) {
                window.scrollTo(0, 0);
                _focusSectionTitle();
            }
        });
    }
    var back = document.getElementById('settings-back');
    if (back) {
        back.addEventListener('click', function() {
            // Return to the list entry that opened this section, or replace a deep link.
            if (_openedFromList) history.back();
            else history.replaceState(null, '', location.pathname + location.search);
            _openedFromList = false;
            showSectionList();
        });
    }
}

/* ── Collapsible Cards ── */
function _syncCardCollapseAria(card) {
    if (!card) return;
    var expanded = !card.classList.contains('collapsed');
    card.querySelectorAll('.card-collapse-toggle[aria-expanded]').forEach(function(toggle) {
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    });
    if (card.classList.contains('notification-channel-card')) {
        var body = card.querySelector('.card-collapse-body');
        if (body) {
            body.setAttribute('aria-hidden', expanded ? 'false' : 'true');
            if (expanded) {
                body.removeAttribute('inert');
            } else {
                body.setAttribute('inert', '');
            }
        }
    }
}

function toggleCardCollapse(headerEl) {
    var card = headerEl.closest('.collapsible-card');
    if (card) {
        card.classList.toggle('collapsed');
        _syncCardCollapseAria(card);
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function init() {
    _initIndex();
    var deepLink = !!location.hash;
    _applySection(_sectionFromHash());
    if (_isCompact() && !deepLink) {
        _setDetail(false);
        return;
    }
    history.replaceState(null, '', '#' + _currentSection);
    _revealPendingBlock();
}
function showsSaveFooter() {
    return _currentSection !== 'about';
}
return {init, showsSaveFooter, switchSection, toggleCardCollapse, syncCard: _syncCardCollapseAria};
};
