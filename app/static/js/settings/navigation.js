'use strict';
DOCSightSettings.navigation = function({syncSaveFooter, onSection}) {
/* ── Section Controller ── */
var _currentSection = 'connection';
var _mobileSidebarFocusReturn = null;
var _mobileSidebarMedia = window.matchMedia ? window.matchMedia('(max-width: 768px)') : null;

function _isMobileSidebarMode() {
    return !!(_mobileSidebarMedia && _mobileSidebarMedia.matches);
}

function _setSidebarAccessibility(sidebar, isOpen) {
    if (!sidebar) return;
    if (_isMobileSidebarMode() && !isOpen) {
        sidebar.setAttribute('aria-hidden', 'true');
        sidebar.setAttribute('inert', '');
    } else {
        sidebar.removeAttribute('aria-hidden');
        sidebar.removeAttribute('inert');
    }
}

function syncMobileSidebarAccessibility() {
    var sidebar = document.getElementById('settings-sidebar');
    _setSidebarAccessibility(sidebar, !!(sidebar && sidebar.classList.contains('open')));
}

function _applySection(id) {
    _currentSection = id;

    /* Sidebar: update active link */
    document.querySelectorAll('.nav-item[data-section]').forEach(function(link) {
        var isActive = link.getAttribute('data-section') === id;
        link.classList.toggle('active', isActive);
        if (isActive) {
            link.setAttribute('aria-current', 'page');
        } else {
            link.removeAttribute('aria-current');
        }
    });

    /* Panels: show selected */
    document.querySelectorAll('.settings-panel').forEach(function(panel) {
        panel.classList.remove('active');
    });
    var target = document.getElementById('panel-' + id);
    if (target) target.classList.add('active');

    /* Mobile title */
    var mobileTitle = document.getElementById('mobile-title');
    if (mobileTitle) mobileTitle.textContent = SECTION_TITLES[id] || id;

    /* Save footer: hide on support/modules, otherwise respect dirty state */
    syncSaveFooter();

    /* Auto-load data for certain panels */
    onSection(id, target);

    /* Mobile: close sidebar after selection */
    closeMobileSidebar();
}

/* User-initiated section change: apply and add a browser history entry so
   Back/Forward move between previously viewed settings sections. Re-selecting
   the current section replaces state instead of stacking a duplicate entry. */
function switchSection(id) {
    var isNewSection = id !== _currentSection;
    _applySection(id);
    if (isNewSection) {
        history.pushState(null, '', '#' + id);
    } else {
        history.replaceState(null, '', '#' + id);
    }
}

/* Resolve the section referenced by the current URL hash (default: connection). */
function _sectionFromHash() {
    var hash = location.hash.replace('#', '');
    return (hash && document.getElementById('panel-' + hash)) ? hash : 'connection';
}

/* Non-pushing variant for Back/Forward and manual hash edits: the browser has
   already updated the URL, so only reflect it in the UI. The guard also makes
   the popstate+hashchange double-fire on navigation a no-op the second time. */
function _syncSectionFromHash() {
    var id = _sectionFromHash();
    if (id === _currentSection) return;
    _applySection(id);
}

window.addEventListener('popstate', _syncSectionFromHash);
window.addEventListener('hashchange', _syncSectionFromHash);

/* ── Mobile Sidebar ── */
function openMobileSidebar() {
    var sidebar = document.getElementById('settings-sidebar');
    var backdrop = document.getElementById('sidebar-backdrop');
    var menuButton = document.getElementById('mobile-menu-button');
    _mobileSidebarFocusReturn = document.activeElement || menuButton;
    if (sidebar) {
        sidebar.classList.add('open');
        _setSidebarAccessibility(sidebar, true);
    }
    if (backdrop) backdrop.classList.add('active');
    if (menuButton) menuButton.setAttribute('aria-expanded', 'true');
    var activeNav = sidebar ? sidebar.querySelector('.nav-item.active[data-section]') : null;
    var firstNav = sidebar ? sidebar.querySelector('.nav-item[data-section]') : null;
    var focusTarget = activeNav || firstNav;
    if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus();
}

function closeMobileSidebar(options) {
    options = options || {};
    var sidebar = document.getElementById('settings-sidebar');
    var backdrop = document.getElementById('sidebar-backdrop');
    var menuButton = document.getElementById('mobile-menu-button');
    var wasOpen = !!(sidebar && sidebar.classList.contains('open'));
    if (sidebar) {
        sidebar.classList.remove('open');
        _setSidebarAccessibility(sidebar, false);
    }
    if (backdrop) backdrop.classList.remove('active');
    if (menuButton) menuButton.setAttribute('aria-expanded', 'false');
    var shouldRestoreFocus = options.restoreFocus !== false;
    if (wasOpen && shouldRestoreFocus) {
        var focusTarget = _mobileSidebarFocusReturn;
        if (!focusTarget || typeof focusTarget.focus !== 'function' || !document.contains(focusTarget)) {
            focusTarget = menuButton;
        }
        if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus();
    }
    _mobileSidebarFocusReturn = null;
}

document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape') return;
    var sidebar = document.getElementById('settings-sidebar');
    if (sidebar && sidebar.classList.contains('open')) {
        event.preventDefault();
        closeMobileSidebar();
    }
});

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
    syncMobileSidebarAccessibility();
    if (_mobileSidebarMedia) {
        if (_mobileSidebarMedia.addEventListener) _mobileSidebarMedia.addEventListener('change', syncMobileSidebarAccessibility);
        else if (_mobileSidebarMedia.addListener) _mobileSidebarMedia.addListener(syncMobileSidebarAccessibility);
    }
    var initialSection = _sectionFromHash();
    _applySection(initialSection);
    history.replaceState(null, '', '#' + initialSection);
}
function showsSaveFooter() {
    return _currentSection !== 'support' && _currentSection !== 'about';
}
return {init, showsSaveFooter, switchSection, openMobileSidebar, closeMobileSidebar, toggleCardCollapse, syncCard: _syncCardCollapseAria};
};
