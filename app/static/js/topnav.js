/* Shared by the dashboard and settings. */
(function() {
    'use strict';

    /* ── Top navigation ──
       One DOM for both layouts: a top bar with dropdown panels on desktop and
       a bottom bar with sheets on mobile. Groups follow the disclosure pattern
       (toggle button with aria-expanded controlling a panel). */
    var topnav = document.getElementById('topnav');
    var navBackdrop = document.getElementById('topnav-backdrop');
    var openNavGroup = null;

    function isMobile() { return window.matchMedia('(max-width: 1023px)').matches; }

    function navGroups() { return Array.from(topnav.querySelectorAll('.topnav-group')); }
    function groupToggle(group) { return group.querySelector('.topnav-toggle'); }
    function groupPanel(group) { return group.querySelector('.topnav-panel'); }
    function panelItems(group) {
        return Array.from(groupPanel(group).querySelectorAll('.nav-item, a[href], input')).filter(function(el) {
            return !el.disabled && el.offsetParent !== null;
        });
    }

    function closeNavGroup(options) {
        options = options || {};
        if (!openNavGroup) return;
        var group = openNavGroup;
        openNavGroup = null;
        group.classList.remove('open');
        groupToggle(group).setAttribute('aria-expanded', 'false');
        groupPanel(group).hidden = true;
        if (navBackdrop) navBackdrop.hidden = true;
        document.body.classList.remove('nav-sheet-open');
        if (options.restoreFocus) groupToggle(group).focus({ preventScroll: true });
    }

    function openGroup(group, focusFirst) {
        if (openNavGroup !== group) {
            closeNavGroup();
            openNavGroup = group;
            group.classList.add('open');
            groupToggle(group).setAttribute('aria-expanded', 'true');
            groupPanel(group).hidden = false;
            if (isMobile()) {
                if (navBackdrop) navBackdrop.hidden = false;
                document.body.classList.add('nav-sheet-open');
            }
        }
        if (focusFirst) {
            var items = panelItems(group);
            if (items.length) items[0].focus({ preventScroll: true });
        }
    }

    topnav.addEventListener('click', function(event) {
        var toggle = event.target.closest('.topnav-toggle');
        if (toggle && topnav.contains(toggle)) {
            var group = toggle.closest('.topnav-group');
            if (openNavGroup === group) closeNavGroup(); else openGroup(group, false);
            return;
        }
        var link = event.target.closest('.nav-item[data-view]');
        if (link && topnav.contains(link)) {
            closeNavGroup();
            // Pages that show the destinations themselves switch in place; elsewhere they are links.
            if (nav.onView && !link.hasAttribute('href')) nav.onView(link.getAttribute('data-view'));
            return;
        }
        /* Panel actions (setup dialogs, report, export) also close the panel */
        if (event.target.closest('.topnav-panel .nav-item')) closeNavGroup();
    });

    topnav.addEventListener('keydown', function(event) {
        var toggle = event.target.closest('.topnav-toggle');
        if (toggle && event.key === 'ArrowDown') {
            event.preventDefault();
            openGroup(toggle.closest('.topnav-group'), true);
            return;
        }
        if (!openNavGroup) return;
        var items = panelItems(openNavGroup);
        var index = items.indexOf(document.activeElement);
        if (index < 0) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            var next = event.key === 'ArrowDown' ? index + 1 : index - 1;
            items[(next + items.length) % items.length].focus();
        } else if (event.key === 'Home' || event.key === 'End') {
            event.preventDefault();
            items[event.key === 'Home' ? 0 : items.length - 1].focus();
        }
    });

    topnav.addEventListener('focusout', function(event) {
        if (openNavGroup && event.relatedTarget && !openNavGroup.contains(event.relatedTarget)) closeNavGroup();
    });
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && openNavGroup) {
            event.preventDefault();
            closeNavGroup({ restoreFocus: true });
        }
    });
    document.addEventListener('click', function(event) {
        if (openNavGroup && !openNavGroup.contains(event.target)) closeNavGroup();
    });
    if (navBackdrop) navBackdrop.addEventListener('click', function() { closeNavGroup(); });
    window.addEventListener('resize', function() { closeNavGroup(); });

    function getNavLinks() {
        return Array.from(topnav.querySelectorAll('.nav-item[data-view]'));
    }

    function syncNavActiveState(view) {
        getNavLinks().forEach(function(link) {
            var active = link.getAttribute('data-view') === view;
            link.classList.toggle('active', active);
            if (active) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        });
        navGroups().forEach(function(group) {
            groupToggle(group).classList.toggle('active', !!groupPanel(group).querySelector('.nav-item.active'));
        });
    }

    var nav = window.DOCSightNav = { close: closeNavGroup, sync: syncNavActiveState, onView: null };
})();
