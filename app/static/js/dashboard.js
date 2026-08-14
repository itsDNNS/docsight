var dashboardBootstrapElement = document.getElementById('docsight-dashboard-bootstrap');
var dashboardBootstrap = DOCSightBrowserContracts.parseDashboardBootstrapText(
    dashboardBootstrapElement && dashboardBootstrapElement.textContent
);
var T = dashboardBootstrap.translations;
var currentLang = dashboardBootstrap.language;
var TEMPERATURE_UNIT = dashboardBootstrap.temperatureUnit;
var CORRELATION_CM_AVAILABLE = dashboardBootstrap.connectionMonitorAvailable;

(function() {
    var LAST_KNOWN_STORAGE_KEY = 'docsight:last-known-dashboard-shell';

    function rememberOnlineShell() {
        if (!navigator.onLine) return;
        try {
            localStorage.setItem(LAST_KNOWN_STORAGE_KEY, new Date().toISOString());
        } catch (err) {
            /* Storage can be unavailable in hardened/private browser contexts. */
        }
    }

    function updateOfflineStatus() {
        var offlineMarker = document.querySelector('meta[name="docsight-offline-shell"][content="true"]');
        var offline = !navigator.onLine || !!offlineMarker || window.__DOCSIGHT_OFFLINE_SHELL__ === true;
        var banner = document.getElementById('offline-status-banner');
        var lastKnown = document.getElementById('offline-last-known');
        var refreshButton = document.getElementById('refresh-btn');
        document.documentElement.classList.toggle('is-offline', offline);
        document.body.classList.toggle('is-offline', offline);
        if (banner) banner.hidden = !offline;
        if (refreshButton) refreshButton.disabled = offline;
        if (lastKnown) {
            var stored = '';
            try { stored = localStorage.getItem(LAST_KNOWN_STORAGE_KEY) || ''; } catch (err) {}
            lastKnown.textContent = stored ? 'Last-known shell: ' + DOCSightBrowserContracts.formatLastKnownTimestamp(stored) : 'Last-known shell timestamp unavailable';
        }
        if (!offline) rememberOnlineShell();
    }

    window.updateOfflineStatus = updateOfflineStatus;
    window.addEventListener('online', updateOfflineStatus);
    window.addEventListener('offline', updateOfflineStatus);
    document.addEventListener('DOMContentLoaded', updateOfflineStatus);
    updateOfflineStatus();
})();

(function() {
    'use strict';

    /* ── Theme ── */
    var saved = localStorage.getItem('docsis-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);

    var themeToggle = document.getElementById('theme-toggle-sidebar');
    function updateThemeState() {
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        themeToggle.checked = isDark;
        var mc = document.querySelector('meta[name="theme-color"]');
        if (mc) mc.setAttribute('content', isDark ? '#06080f' : '#f8f6f3');
    }
    updateThemeState();
    themeToggle.addEventListener('change', function() {
        var next = this.checked ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('docsis-theme', next);
        var mc = document.querySelector('meta[name="theme-color"]');
        if (mc) mc.setAttribute('content', next === 'dark' ? '#06080f' : '#f8f6f3');
        // Re-render charts with updated theme colors
        if (typeof window.refreshDonuts === 'function') {
            setTimeout(window.refreshDonuts, 50);
        }
    });

    /* ── State ── */
    /* currentView is global — defined in chart-engine.js */
    /* charts registry is global — defined in chart-engine.js */
    /* _trendRange → trends.js */
    /* BQM state variables → bqm.js */
    /* todayStr, pad, formatDateDE → chart-engine.js */

    /* ── Sortable Tables ── */
    function initSortableTables() {
        document.querySelectorAll('table.sortable').forEach(function(table) {
            var headers = table.querySelectorAll('th');
            headers.forEach(function(th, colIdx) {
                th.addEventListener('click', function() {
                    sortTable(table, colIdx, th);
                });
            });
        });
    }
    initSortableTables();

    function sortTable(table, colIdx, th) {
        var tbody = table.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        var asc = th.getAttribute('data-sort-dir') !== 'asc';

        table.querySelectorAll('th').forEach(function(h) {
            h.removeAttribute('data-sort-dir');
            h.removeAttribute('aria-sort');
            h.classList.remove('sort-asc', 'sort-desc');
        });
        th.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        th.classList.add(asc ? 'sort-asc' : 'sort-desc');

        rows.sort(function(a, b) {
            var cellA = a.cells[colIdx];
            var cellB = b.cells[colIdx];
            var valA = cellA.getAttribute('data-sort') || cellA.textContent.trim();
            var valB = cellB.getAttribute('data-sort') || cellB.textContent.trim();
            var numA = parseFloat(valA);
            var numB = parseFloat(valB);
            if (!isNaN(numA) && !isNaN(numB)) {
                return asc ? numA - numB : numB - numA;
            }
            return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        });
        rows.forEach(function(row) { tbody.appendChild(row); });
    }

    /* ── Sidebar ── */
    var sidebar = document.getElementById('sidebar');
    var sidebarBackdrop = document.getElementById('sidebar-backdrop');

    function isMobile() { return window.matchMedia('(max-width: 1023px)').matches; }

    var sidebarLastOpener = null;
    var sidebarFocusableSelector = 'a[href], button, input, select, textarea, [role="button"], [tabindex]';

    function getSidebarFocusables() {
        return Array.from(sidebar.querySelectorAll(sidebarFocusableSelector));
    }

    function setSidebarFocusSuppressed(suppressed) {
        getSidebarFocusables().forEach(function(el) {
            if (suppressed) {
                if (!el.hasAttribute('data-sidebar-prev-tabindex')) {
                    el.setAttribute('data-sidebar-prev-tabindex', el.getAttribute('tabindex') || '');
                }
                el.setAttribute('tabindex', '-1');
            } else if (el.hasAttribute('data-sidebar-prev-tabindex')) {
                var previous = el.getAttribute('data-sidebar-prev-tabindex');
                if (previous) {
                    el.setAttribute('tabindex', previous);
                } else {
                    el.removeAttribute('tabindex');
                }
                el.removeAttribute('data-sidebar-prev-tabindex');
            }
        });
        if ('inert' in sidebar) {
            sidebar.inert = suppressed;
        }
    }

    function syncSidebarAccessibility() {
        var closedOnMobile = isMobile() && !sidebar.classList.contains('open');
        sidebar.setAttribute('aria-hidden', closedOnMobile ? 'true' : 'false');
        setSidebarFocusSuppressed(closedOnMobile);
        var hamburger = document.getElementById('hamburger');
        if (hamburger) {
            hamburger.setAttribute('aria-expanded', sidebar.classList.contains('open') ? 'true' : 'false');
        }
    }

    function focusFirstSidebarItem() {
        var first = getSidebarFocusables().find(function(el) {
            return el.classList && el.classList.contains('nav-item') && !el.disabled && el.offsetParent !== null;
        }) || getSidebarFocusables().find(function(el) {
            return !el.disabled && el.offsetParent !== null;
        });
        if (first) first.focus({ preventScroll: true });
    }

    function getSidebarLinks() {
        return Array.from(sidebar.querySelectorAll('.nav-section .nav-item[data-view]'));
    }

    function syncNavActiveState(view) {
        getSidebarLinks().forEach(function(link) {
            link.classList.toggle('active', link.getAttribute('data-view') === view);
        });
    }

    window.toggleNavSection = function(labelEl) {
        var section = labelEl.closest('.nav-section-collapsible');
        if (section) {
            section.classList.toggle('collapsed');
            labelEl.setAttribute('aria-expanded', labelEl.getAttribute('aria-expanded') === 'true' ? 'false' : 'true');
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    };

    window.openSidebar = function() {
        sidebarLastOpener = document.activeElement;
        sidebar.classList.add('open');
        sidebarBackdrop.style.display = 'block';
        document.body.classList.add('sidebar-open');
        syncSidebarAccessibility();
        window.requestAnimationFrame(focusFirstSidebarItem);
    };
    window.closeSidebar = function(options) {
        options = options || {};
        sidebar.classList.remove('open');
        sidebarBackdrop.style.display = 'none';
        document.body.classList.remove('sidebar-open');
        syncSidebarAccessibility();
        if (options.restoreFocus !== false && sidebarLastOpener && typeof sidebarLastOpener.focus === 'function') {
            window.requestAnimationFrame(function() { sidebarLastOpener.focus({ preventScroll: true }); });
        }
    };

    syncSidebarAccessibility();
    window.addEventListener('resize', syncSidebarAccessibility);
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && sidebar.classList.contains('open') && isMobile()) {
            event.preventDefault();
            closeSidebar();
        }
    });

    /* Swipe-to-close sidebar (mobile) */
    (function() {
        var startX = 0, startY = 0, currentX = 0, swiping = false, locked = false;
        sidebar.addEventListener('touchstart', function(e) {
            if (!isMobile()) return;
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
            currentX = startX;
            swiping = true;
            locked = false;
        }, { passive: true });
        sidebar.addEventListener('touchmove', function(e) {
            if (!swiping) return;
            currentX = e.touches[0].clientX;
            var dx = currentX - startX;
            var dy = e.touches[0].clientY - startY;
            /* Lock direction on first significant movement */
            if (!locked && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) {
                locked = true;
                /* If vertical movement dominates, cancel swipe */
                if (Math.abs(dy) > Math.abs(dx)) { swiping = false; return; }
            }
            if (locked && dx < -10) {
                sidebar.style.transform = 'translateX(' + Math.max(dx, -280) + 'px)';
            }
        }, { passive: true });
        sidebar.addEventListener('touchend', function() {
            if (!swiping) { sidebar.style.transform = ''; return; }
            swiping = false;
            var dx = currentX - startX;
            if (dx < -80) { closeSidebar(); }
            sidebar.style.transform = '';
        }, { passive: true });
    })();

    sidebar.addEventListener('click', function(event) {
        var link = event.target.closest('.nav-item[data-view]');
        if (!link || !sidebar.contains(link)) return;
        if (isMobile()) { closeSidebar({ restoreFocus: false }); }
        switchView(link.getAttribute('data-view'));
    });
    /* Nav items are now <button>, so Enter/Space fires click natively */

    /* ── Pill tab helpers ── */
    window.selectPill = function(btn, callback) {
        btn.parentElement.querySelectorAll('.trend-tab').forEach(function(t) { t.classList.remove('active'); });
        btn.classList.add('active');
        if (callback) callback();
    };
    window.getPillValue = function(containerId) {
        var active = document.querySelector('#' + containerId + ' .trend-tab.active');
        return active ? active.dataset.value : null;
    };

    function switchView(view, skipHash) {
        currentView = view;
        if (!skipHash) location.hash = view === 'live' ? '' : view;
        syncNavActiveState(view);
        // Generic: remove active from all views, add to target
        document.querySelectorAll('.main-content > .view').forEach(function(v) {
            v.classList.remove('active');
        });
        var targetId = view === 'live' ? 'view-dashboard' : 'view-' + view;
        var target = document.getElementById(targetId);
        if (target) target.classList.add('active');

        stopAutoRefresh();
        if (typeof stopBqmLiveRefresh === 'function') stopBqmLiveRefresh();

        // View-specific init callbacks
        if (view === 'live') {
            startAutoRefresh();
        } else if (view === 'bqm') {
            if (typeof initBqmView === 'function') initBqmView();
        } else if (view === 'smokeping') {
            if (typeof loadSmokepingGraphs === 'function') loadSmokepingGraphs();
        } else if (view === 'speedtest') {
            loadSpeedtestHistory();
        } else if (view === 'journal') {
            if (typeof _timelineActive !== 'undefined' && _timelineActive && typeof closeIncidentTimeline === 'function') closeIncidentTimeline();
            if (typeof loadIncidents === 'function') loadIncidents();
            if (typeof loadJournal === 'function') loadJournal();
        } else if (view === 'events') {
            if (typeof loadEvents === 'function') loadEvents();
        } else if (view === 'channels') {
            if (typeof initChannelView === 'function') initChannelView();
        } else if (view === 'correlation') {
            loadCorrelationData();
        } else if (view === 'bnetz') {
            if (typeof loadBnetzData === 'function') loadBnetzData();
        } else if (view === 'trends') {
            if (typeof updateTrendTabs === 'function') updateTrendTabs();
            if (typeof loadTrends === 'function') loadTrends(_trendRange);
        } else if (view === 'modulation') {
            if (typeof initModulation === 'function') initModulation();
        } else if (view === 'comparison') {
            if (typeof initComparison === 'function') initComparison();
        } else if (view === 'evidence') {
            if (typeof initEvidence === 'function') initEvidence();
        } else if (view.indexOf('mod-') === 0) {
            /* Generic module init: mod-docsight-comparison → initComparison */
            var parts = view.replace('mod-docsight-', '').split('-');
            var fnName = 'init' + parts.map(function(w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join('');
            if (typeof window[fnName] === 'function') window[fnName]();
        } else if (view === 'segment-utilization') {
            if (typeof loadFritzCableData === 'function') loadFritzCableData();
        }

        // Re-initialize Lucide icons after view switch
        lucide.createIcons();

        // Refresh event badge to reflect view context (filtered vs global)
        if (typeof refreshEventBadge === 'function') refreshEventBadge();
    }
    window.switchView = switchView;

    /* Trend Tabs → trends.js */

    /* ── Hash-based view routing ── */
    function viewFromHash() {
        var h = location.hash.replace('#', '');
        if (!h) return null;
        // Strip query params (e.g. #channels?mode=timeline → channels)
        var view = h.split('?')[0];
        // Accept any view that exists in DOM (supports module views)
        var el = document.getElementById('view-' + view) || (view === 'live' && document.getElementById('view-dashboard'));
        return el ? view : null;
    }
    window.addEventListener('hashchange', function() {
        var v = viewFromHash();
        if (v && v !== currentView) switchView(v, true);
    });

    /* BNetzA Breitbandmessung → integrations.js */

    /* BQM Calendar, Live → bqm.js */

    /* ── Auto Refresh with Countdown ── */
    var refreshTimer = null;
    var countdownTimer = null;
    var countdownSeconds = 60;
    var secondsSinceUpdate = 0;
    var REFRESH_INTERVAL = 60;
    function updateCountdown() {
        var countdownEl = document.getElementById('topbar-countdown');
        var desktopCountdownEl = document.getElementById('desktop-countdown');
        if (countdownEl) countdownEl.textContent = countdownSeconds + 's';
        if (desktopCountdownEl) desktopCountdownEl.textContent = countdownSeconds + 's';
    }

    function startAutoRefresh() {
        stopAutoRefresh();
        countdownSeconds = REFRESH_INTERVAL;
        secondsSinceUpdate = 0;
        updateCountdown();
        countdownTimer = setInterval(function() {
            if (currentView !== 'live' || document.hidden) return;
            countdownSeconds--;
            secondsSinceUpdate++;
            if (countdownSeconds <= 0) {
                countdownSeconds = REFRESH_INTERVAL;
                refreshData();
            }
            updateCountdown();
        }, 1000);
    }
    function stopAutoRefresh() {
        if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
        if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
    }

    function refreshData() {
        fetch(window.location.href)
            .then(function(r) {
                if (r.headers && r.headers.get('X-DOCSight-Offline-Shell') === 'true') {
                    window.__DOCSIGHT_OFFLINE_SHELL__ = true;
                    if (typeof window.updateOfflineStatus === 'function') window.updateOfflineStatus();
                    throw new Error('Offline shell fallback');
                }
                return r.text();
            })
            .then(function(html) {
                var doc = new DOMParser().parseFromString(html, 'text/html');

                // Save expanded metric cards by index
                var openCardIndices = [];
                document.querySelectorAll('.metric-card').forEach(function(el, i) {
                    if (el.classList.contains('open')) openCardIndices.push(i);
                });

                // Save expanded channel groups by label text
                var openGroupLabels = [];
                document.querySelectorAll('details.channel-group[open], .docsis-group.open').forEach(function(el) {
                    var s = el.querySelector('summary, .docsis-group-header');
                    if (s) openGroupLabels.push(s.textContent.trim());
                });

                // Replace dashboard content
                var freshDash = doc.querySelector('#view-dashboard');
                var currentDash = document.querySelector('#view-dashboard');
                if (freshDash && currentDash) {
                    currentDash.innerHTML = freshDash.innerHTML;
                }

                // Update topbar timestamp
                var freshMeta = doc.querySelector('#topbar-meta');
                var currentMeta = document.querySelector('#topbar-meta');
                if (freshMeta && currentMeta) {
                    currentMeta.innerHTML = freshMeta.innerHTML;
                }

                // Reset countdown after refresh
                countdownSeconds = REFRESH_INTERVAL;
                secondsSinceUpdate = 0;
                updateCountdown();

                // Restore expanded metric cards
                document.querySelectorAll('.metric-card').forEach(function(el, i) {
                    if (openCardIndices.indexOf(i) !== -1) el.classList.add('open');
                });

                // Restore expanded channel groups
                document.querySelectorAll('details.channel-group, .docsis-group').forEach(function(el) {
                    var s = el.querySelector('summary, .docsis-group-header');
                    if (s && openGroupLabels.indexOf(s.textContent.trim()) !== -1) {
                        if (el.matches('details.channel-group')) el.setAttribute('open', '');
                        else el.classList.add('open');
                    }
                });

                // Re-init sortable tables (event listeners lost on innerHTML replace)
                initSortableTables();

                // Re-init hero chart (instance lost on innerHTML replace)
                if (typeof window.refreshHeroChart === 'function') {
                    window.refreshHeroChart();
                }

                // Re-init sparklines (canvas lost on innerHTML replace)
                if (typeof window.refreshSparklines === 'function') {
                    window.refreshSparklines();
                }

                // Re-init channel health donuts (instances lost on innerHTML replace)
                if (typeof window.refreshDonuts === 'function') {
                    window.refreshDonuts();
                }

                // Re-init Lucide icons (lost on innerHTML replace)
                lucide.createIcons();

                // Re-init glossary keyboard a11y (lost on innerHTML replace)
                if (typeof window.initGlossaryHints === 'function') window.initGlossaryHints();

                // Refresh event badge count (respecting current filters)
                if (typeof window.refreshEventBadge === 'function') {
                    window.refreshEventBadge();
                }
            })
            .catch(function(err) {
                console.warn('Auto-refresh failed:', err);
            });
    }

    if (currentView === 'live') startAutoRefresh();

    /* ── Fast initial refresh while waiting for first poll ── */
    (function() {
        var waiting = document.querySelector('#view-dashboard .waiting');
        if (!waiting) return;
        var fastTimer = setInterval(function() {
            if (document.hidden) return;
            refreshData();
            /* Stop fast polling once waiting spinner is gone */
            if (!document.querySelector('#view-dashboard .waiting')) {
                clearInterval(fastTimer);
            }
        }, 5000);
        /* Safety: stop after 5 minutes regardless */
        setTimeout(function() { clearInterval(fastTimer); }, 300000);
    })();

    /* ── Manual Poll (Refresh Button) ── */
    var refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', function() {
            if (refreshBtn.disabled) return;
            refreshBtn.disabled = true;
            refreshBtn.classList.add('spinning');
            fetch(docsightUrl('/api/poll'), {method: 'POST'})
                .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
                .then(function(res) {
                    if (res.data.success) {
                        showToast(T.refresh_success || 'Data updated', 'success');
                        refreshData();
                    } else {
                        showToast(res.data.error || 'Error', res.status === 429 ? 'error' : 'error');
                    }
                })
                .catch(function() { showToast(T.network_error || 'Error', 'error'); })
                .finally(function() {
                    refreshBtn.classList.remove('spinning');
                    setTimeout(function() {
                        if (navigator.onLine && window.__DOCSIGHT_OFFLINE_SHELL__ !== true) refreshBtn.disabled = false;
                    }, 10000);
                });
        });
    }

    function showToast(msg, type) {
        var toast = document.getElementById('toast');
        toast.textContent = msg;
        toast.className = 'toast toast-' + (type || 'success') + ' show';
        setTimeout(function() { toast.classList.remove('show'); }, 3000);
    }
    window.showToast = showToast;

    /* Trend Charts, expand buttons, zoom shortcuts → trends.js */

    /* BQM keyboard shortcuts → bqm.js */

    /* BQM Graph + Import → bqm.js */

    /* Smokeping Graphs → integrations.js */

    /* ── Init ── */
    // Store initial hash for deferred routing (after external scripts load)
    var _initHash = viewFromHash();
    window._pendingView = (_initHash && _initHash !== 'live') ? _initHash : null;


    /* ── Incident Journal, Incidents, Timeline, Import, Bulk, Search → journal.js ── */


    // Sidebar resize handler (clean up state on viewport change)
    window.addEventListener('resize', function() {
        if (isMobile()) {
            sidebar.classList.remove('collapsed');
            closeSidebar();
        } else {
            sidebar.classList.remove('mobile-open');
            sidebarBackdrop.classList.remove('active');
        }
    });

    document.addEventListener('DOMContentLoaded', function() {
        syncNavActiveState(currentView || 'live');
    });

})();
