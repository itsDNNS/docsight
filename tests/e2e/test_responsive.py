"""E2E tests for responsive / mobile layout."""

import pytest


@pytest.fixture()
def mobile_page(page, live_server):
    """Page with a mobile viewport (375x667, iPhone SE)."""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(live_server)
    page.wait_for_load_state("networkidle")
    return page


class TestMobileLayout:
    """Mobile viewport behavior."""

    def test_hamburger_visible_on_mobile(self, mobile_page):
        hamburger = mobile_page.locator("#hamburger")
        assert hamburger.is_visible()

    def test_sidebar_hidden_on_mobile(self, mobile_page):
        sidebar = mobile_page.locator("nav.sidebar")
        # Sidebar is positioned off-screen (x < 0) on mobile
        box = sidebar.bounding_box()
        assert box is None or box["x"] + box["width"] <= 0

    def test_mobile_header_visible(self, mobile_page):
        header = mobile_page.locator(".mobile-header")
        assert header.is_visible()

    def test_hamburger_opens_sidebar(self, mobile_page):
        mobile_page.locator("#hamburger").click()
        mobile_page.wait_for_timeout(300)
        sidebar = mobile_page.locator("nav.sidebar")
        box = sidebar.bounding_box()
        # Allow tiny subpixel drift from browser layout math around x=0.
        assert box is not None and box["x"] >= -0.5

    def test_closed_mobile_sidebar_removes_nav_from_tab_order(self, mobile_page):
        """Closed off-canvas navigation must not expose hidden focus targets."""
        focusable_in_closed_sidebar = mobile_page.evaluate(
            """
            () => Array.from(document.querySelectorAll(
                '#sidebar a[href], #sidebar button, #sidebar input, '
                + '#sidebar [role="button"], #sidebar [tabindex]'
            )).filter((el) => {
                const tabindex = el.getAttribute('tabindex');
                return !el.disabled && tabindex !== '-1';
            }).map((el) => el.textContent.trim() || el.getAttribute('aria-label') || el.id)
            """
        )

        assert focusable_in_closed_sidebar == []

    def test_mobile_sidebar_focus_moves_in_and_returns_on_escape(self, mobile_page):
        """Opening mobile nav should expose links, focus them, and close accessibly."""
        hamburger = mobile_page.locator("#hamburger")
        hamburger.focus()
        hamburger.click()
        mobile_page.wait_for_timeout(300)

        active_id = mobile_page.evaluate("document.activeElement && document.activeElement.id")
        active_view = mobile_page.evaluate(
            "document.activeElement && document.activeElement.getAttribute('data-view')"
        )
        assert active_id == "sidebar" or active_view == "live"
        assert mobile_page.locator("#sidebar").get_attribute("aria-hidden") == "false"

        mobile_page.keyboard.press("Escape")
        mobile_page.wait_for_timeout(300)

        assert mobile_page.locator("#sidebar").get_attribute("aria-hidden") == "true"
        assert mobile_page.evaluate("document.activeElement && document.activeElement.id") == "hamburger"

    def test_mobile_sidebar_close_control_and_labels_are_touch_friendly(self, mobile_page):
        """Mobile drawer should have an obvious close control and contained labels."""
        hamburger = mobile_page.locator("#hamburger")
        hamburger.focus()
        hamburger.click()
        mobile_page.wait_for_timeout(300)

        close_button = mobile_page.get_by_role("button", name="Close menu")
        assert close_button.is_visible()
        close_box = close_button.bounding_box()
        assert close_box is not None
        assert close_box["width"] >= 44
        assert close_box["height"] >= 44

        sidebar_geometry = mobile_page.locator("#sidebar").evaluate(
            """
            (sidebar) => {
                const sidebarRect = sidebar.getBoundingClientRect();
                const items = Array.from(sidebar.querySelectorAll('.nav-item'));
                const overflowingItems = items.filter((item) => item.scrollWidth - item.clientWidth > 1).map((item) => item.textContent.trim());
                return {
                    background: getComputedStyle(sidebar).backgroundColor,
                    overflowingItems,
                    outsideItems: items.filter((item) => {
                        const rect = item.getBoundingClientRect();
                        return rect.left < sidebarRect.left - 1 || rect.right > sidebarRect.right + 1;
                    }).map((item) => item.textContent.trim()),
                };
            }
            """
        )
        assert sidebar_geometry["overflowingItems"] == []
        assert sidebar_geometry["outsideItems"] == []
        assert "rgba" not in sidebar_geometry["background"]

        close_button.click()
        mobile_page.wait_for_timeout(300)
        assert mobile_page.locator("#sidebar").get_attribute("aria-hidden") == "true"
        assert mobile_page.evaluate("document.activeElement && document.activeElement.id") == "hamburger"

    def test_primary_nav_items_in_sidebar(self, mobile_page):
        mobile_page.locator("#hamburger").click()
        mobile_page.wait_for_timeout(300)
        nav_items = mobile_page.locator(
            '.nav-section[data-nav-section="monitoring"] .nav-item'
        )
        assert nav_items.count() >= 4

    def test_analysis_section_collapsible(self, mobile_page):
        mobile_page.locator("#hamburger").click()
        mobile_page.wait_for_timeout(300)
        analysis = mobile_page.locator(
            '.nav-section[data-nav-section="analysis"]'
        )
        if analysis.count() > 0:
            toggle = analysis.locator(".nav-group-toggle")
            toggle.click()
            mobile_page.wait_for_timeout(200)
            items = analysis.locator(".nav-section-items .nav-item")
            assert items.count() >= 1

    def test_bnetz_measurements_are_readable_and_actionable_on_mobile(self, mobile_page):
        """BNetzA evidence rows should not hide values or actions off-screen."""
        mobile_page.evaluate("switchView('bnetz')")
        mobile_page.wait_for_selector("#bnetz-table-card", state="visible")
        mobile_page.wait_for_selector("#bnetz-tbody tr[data-bnetz-idx]")

        overflow = mobile_page.locator("#bnetz-table-card").evaluate(
            "el => el.scrollWidth - el.clientWidth"
        )
        assert overflow <= 1

        action_rects = mobile_page.locator("#bnetz-tbody tr[data-bnetz-idx] .bnetz-action-btn").evaluate_all(
            """
            buttons => buttons.map((btn) => {
                const rect = btn.getBoundingClientRect();
                return {left: rect.left, right: rect.right, width: rect.width, visible: rect.width > 0 && rect.height > 0};
            })
            """
        )
        assert action_rects, "expected BNetzA row actions to be rendered"
        viewport_width = mobile_page.evaluate("window.innerWidth")
        assert all(rect["visible"] for rect in action_rects)
        assert all(rect["left"] >= 0 and rect["right"] <= viewport_width for rect in action_rects)

    def test_correlation_timeline_wraps_mobile_evidence_rows(self, mobile_page):
        """Correlation timeline rows should expose details without hidden horizontal scrolling."""
        mobile_page.evaluate("switchView('correlation')")
        mobile_page.wait_for_selector("#correlation-table-card", state="visible")
        mobile_page.wait_for_selector("#correlation-tbody tr[data-ts]")

        overflow = mobile_page.locator("#correlation-table-wrap").evaluate(
            "el => el.scrollWidth - el.clientWidth"
        )
        assert overflow <= 1

        row_geometry = mobile_page.locator("#correlation-tbody tr[data-ts]").first.evaluate(
            """
            (row) => {
                const rowRect = row.getBoundingClientRect();
                const details = row.querySelector('td:last-child').getBoundingClientRect();
                return {
                    rowLeft: rowRect.left,
                    rowRight: rowRect.right,
                    detailsLeft: details.left,
                    detailsRight: details.right,
                    viewportWidth: window.innerWidth,
                };
            }
            """
        )
        assert row_geometry["rowLeft"] >= 0
        assert row_geometry["rowRight"] <= row_geometry["viewportWidth"]
        assert row_geometry["detailsLeft"] >= 0
        assert row_geometry["detailsRight"] <= row_geometry["viewportWidth"]

    def test_incident_journal_mobile_actions_chips_and_rows_are_scannable(self, mobile_page):
        """Incident Journal should use mobile-first actions, wrapping chips, and card rows."""
        mobile_page.evaluate("switchView('journal')")
        mobile_page.wait_for_selector("#journal-table-card", state="visible")
        mobile_page.wait_for_selector("#journal-tbody tr[data-id]")
        mobile_page.evaluate(
            """
            () => {
                window._incidentsData = [
                    {id: 501, name: 'Upstream Noise Issue with very long mobile label', status: 'open', entry_count: 3},
                    {id: 502, name: 'Firmware Update Issues and repeated support calls', status: 'escalated', entry_count: 1}
                ];
                window.renderIncidentBar(window._incidentsData);
            }
            """
        )

        geometry = mobile_page.evaluate(
            """
            () => {
                const viewportWidth = window.innerWidth;
                const visibleRows = Array.from(document.querySelectorAll('#journal-tbody tr[data-id]'));
                const firstRow = visibleRows[0];
                const titleCell = firstRow.querySelector('td:nth-child(3)');
                const clipCell = firstRow.querySelector('.journal-clip');
                const actionRects = Array.from(document.querySelectorAll('.journal-header-actions > button, .journal-export-wrapper > button')).map((button) => {
                    const rect = button.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, height: rect.height, width: rect.width};
                });
                const chipRects = Array.from(document.querySelectorAll('#incident-filter-bar .incident-pill')).map((pill) => {
                    const rect = pill.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, width: rect.width};
                });
                return {
                    viewportWidth,
                    viewOverflow: document.querySelector('#view-journal').scrollWidth - document.querySelector('#view-journal').clientWidth,
                    actionsOverflow: document.querySelector('.journal-header-actions').scrollWidth - document.querySelector('.journal-header-actions').clientWidth,
                    tableOverflow: document.querySelector('#journal-table-card').scrollWidth - document.querySelector('#journal-table-card').clientWidth,
                    chipWrap: getComputedStyle(document.querySelector('#incident-filter-bar')).flexWrap,
                    rowDisplay: getComputedStyle(firstRow).display,
                    titleWidth: titleCell.getBoundingClientRect().width,
                    clipDisplay: getComputedStyle(clipCell).display,
                    actionRects,
                    chipRects,
                };
            }
            """
        )

        assert geometry["viewOverflow"] <= 1
        assert geometry["actionsOverflow"] <= 1
        assert geometry["tableOverflow"] <= 1
        assert geometry["chipWrap"] == "wrap"
        assert geometry["rowDisplay"] in {"block", "grid"}
        assert geometry["titleWidth"] >= 220
        assert geometry["clipDisplay"] == "none"
        assert all(rect["height"] >= 44 for rect in geometry["actionRects"])
        assert all(rect["left"] >= 0 and rect["right"] <= geometry["viewportWidth"] for rect in geometry["actionRects"])
        assert all(rect["left"] >= 0 and rect["right"] <= geometry["viewportWidth"] for rect in geometry["chipRects"])

    def test_incident_journal_mobile_bulk_selection_remains_accessible(self, mobile_page):
        """Bulk mode controls should remain reachable in mobile card rows."""
        mobile_page.evaluate("switchView('journal')")
        mobile_page.wait_for_selector("#journal-table-card", state="visible")
        mobile_page.wait_for_selector("#journal-tbody tr[data-id]")
        mobile_page.locator("#btn-bulk-toggle").click()
        mobile_page.wait_for_selector(".journal-row-check")

        checkbox_geometry = mobile_page.locator("#journal-tbody tr[data-id] .journal-check-cell").first.evaluate(
            """
            (cell) => {
                const rect = cell.getBoundingClientRect();
                const inputRect = cell.querySelector('input').getBoundingClientRect();
                return {
                    cellLeft: rect.left,
                    cellRight: rect.right,
                    cellHeight: rect.height,
                    inputLeft: inputRect.left,
                    inputRight: inputRect.right,
                    viewportWidth: window.innerWidth,
                };
            }
            """
        )

        assert checkbox_geometry["cellLeft"] >= 0
        assert checkbox_geometry["cellRight"] <= checkbox_geometry["viewportWidth"]
        assert checkbox_geometry["cellHeight"] >= 44
        assert checkbox_geometry["inputLeft"] >= 0
        assert checkbox_geometry["inputRight"] <= checkbox_geometry["viewportWidth"]

    def test_incident_journal_mobile_export_and_attachment_badges_fit_viewport(self, mobile_page):
        """Export choices and attachment badges should remain usable in the mobile layout."""
        mobile_page.evaluate("switchView('journal')")
        mobile_page.wait_for_selector("#journal-table-card", state="visible")
        mobile_page.evaluate(
            """
            () => {
                window._journalSortCol = 'date';
                window._journalSortAsc = false;
                window.T = Object.assign({}, window.T, {
                    attachments: 'Attachments "screenshots"',
                    incident_date: 'Date "local"'
                });
                window.renderJournalTable([{
                    id: 9001,
                    date: '2026-05-02',
                    title: 'Mobile evidence entry with attached screenshots and modem exports',
                    description: 'Includes screenshots and diagnostics for the support case.',
                    attachment_count: 2,
                    icon: 'documentation'
                }]);
            }
            """
        )
        mobile_page.locator(".journal-export-wrapper > button").click()

        geometry = mobile_page.evaluate(
            """
            () => {
                const viewportWidth = window.innerWidth;
                const dropdown = document.querySelector('#journal-export-dropdown');
                const dropdownRect = dropdown.getBoundingClientRect();
                const optionRects = Array.from(dropdown.querySelectorAll('button')).map((button) => {
                    const rect = button.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, height: rect.height};
                });
                const clip = document.querySelector('#journal-tbody tr[data-id] .journal-clip');
                const clipRect = clip.getBoundingClientRect();
                return {
                    viewportWidth,
                    dropdownLeft: dropdownRect.left,
                    dropdownRight: dropdownRect.right,
                    optionRects,
                    clipDisplay: getComputedStyle(clip).display,
                    clipText: clip.textContent.trim(),
                    clipLeft: clipRect.left,
                    clipRight: clipRect.right,
                    clipLabel: clip.getAttribute('data-label'),
                    dateLabel: document.querySelector('#journal-tbody tr[data-id] .journal-date-cell').getAttribute('data-label'),
                };
            }
            """
        )

        assert geometry["dropdownLeft"] >= 0
        assert geometry["dropdownRight"] <= geometry["viewportWidth"]
        assert all(rect["left"] >= 0 and rect["right"] <= geometry["viewportWidth"] for rect in geometry["optionRects"])
        assert all(rect["height"] >= 40 for rect in geometry["optionRects"])
        assert geometry["clipDisplay"] == "inline-flex"
        assert geometry["clipText"] == "📎 2"
        assert geometry["clipLabel"] == 'Attachments "screenshots"'
        assert geometry["dateLabel"] == 'Date "local"'
        assert geometry["clipLeft"] >= 0
        assert geometry["clipRight"] <= geometry["viewportWidth"]

    def test_mobile_chart_tabs_help_and_close_targets_are_comfortable(self, mobile_page):
        """Chart controls, tabs, help hints, and modal close buttons should meet mobile hit targets."""
        mobile_page.evaluate("switchView('trends')")
        mobile_page.wait_for_selector("#view-trends.active .chart-expand-btn", state="attached")
        mobile_page.evaluate(
            """
            () => document.querySelectorAll(
                '#view-trends.active .chart-card, #view-trends.active .chart-card canvas, #view-trends.active .chart-expand-btn'
            ).forEach((el) => { el.style.display = el.matches('.chart-expand-btn') ? 'inline-flex' : 'block'; })
            """
        )

        mobile_page.evaluate(
            """
            () => {
                const fixture = document.createElement('div');
                fixture.id = '__touch-target-fixture';
                fixture.style.position = 'fixed';
                fixture.style.left = '8px';
                fixture.style.top = '80px';
                fixture.style.zIndex = '9999';
                fixture.innerHTML = '<button class="chart-expand-btn" type="button" aria-label="Expand chart">⛶</button><span class="glossary-hint" tabindex="0" aria-label="Help"><i>?</i></span>';
                document.body.appendChild(fixture);
            }
            """
        )

        trends_targets = mobile_page.evaluate(
            """
            () => {
                const viewportWidth = window.innerWidth;
                const groups = {
                    expand: '#__touch-target-fixture .chart-expand-btn',
                    tabs: '#view-trends.active #trend-tabs .trend-tab',
                    glossary: '#__touch-target-fixture .glossary-hint'
                };
                return Object.fromEntries(Object.entries(groups).map(([group, selector]) => [
                    group,
                    Array.from(document.querySelectorAll(selector)).map((el) => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return {
                            width: rect.width,
                            height: rect.height,
                            left: rect.left,
                            right: rect.right,
                            viewportWidth,
                            opacity: Number(style.opacity),
                            visibility: style.visibility,
                            pointerEvents: style.pointerEvents,
                        };
                    }).filter((rect) => rect.width > 0 && rect.height > 0)
                ]));
            }
            """
        )

        mobile_page.evaluate("switchView('speedtest')")
        mobile_page.wait_for_selector("#view-speedtest.active #speedtest-tabs .trend-tab")
        speedtest_tabs = mobile_page.locator("#view-speedtest.active #speedtest-tabs .trend-tab").evaluate_all(
            """
            tabs => tabs.map((tab) => {
                const rect = tab.getBoundingClientRect();
                return {width: rect.width, height: rect.height, left: rect.left, right: rect.right, viewportWidth: window.innerWidth};
            })
            """
        )

        mobile_page.evaluate("switchView('correlation')")
        mobile_page.wait_for_selector("#view-correlation.active #correlation-tabs .trend-tab")
        mobile_page.evaluate("document.querySelector('#correlation-chart-container').style.display = 'block'")
        correlation_controls = mobile_page.evaluate(
            """
            () => Array.from(document.querySelectorAll(
                '#view-correlation.active #correlation-tabs .trend-tab, #view-correlation.active .chart-export-btn'
            )).map((el) => {
                const rect = el.getBoundingClientRect();
                return {width: rect.width, height: rect.height, left: rect.left, right: rect.right, viewportWidth: window.innerWidth};
            })
            """
        )

        mobile_page.locator("#view-correlation.active .chart-export-btn").first.click()
        mobile_page.evaluate("window.DOCSightModal.open('bqm-import-modal')")
        mobile_page.wait_for_selector("#bqm-import-modal.open .modal-header .modal-close")
        modal_close_rect = mobile_page.locator("#bqm-import-modal.open .modal-header .modal-close").evaluate(
            """
            (button) => {
                const rect = button.getBoundingClientRect();
                return {width: rect.width, height: rect.height, left: rect.left, right: rect.right, viewportWidth: window.innerWidth};
            }
            """
        )

        assert trends_targets["expand"], "expected visible trend chart expand buttons"
        assert trends_targets["tabs"], "expected visible trend tabs"
        assert trends_targets["glossary"], "expected visible trend glossary hints"
        assert speedtest_tabs, "expected visible speedtest tabs"
        assert correlation_controls, "expected visible correlation tabs/export controls"
        assert modal_close_rect, "expected visible modal close button"

        all_targets = (
            trends_targets["expand"]
            + trends_targets["tabs"]
            + trends_targets["glossary"]
            + speedtest_tabs
            + correlation_controls
            + [modal_close_rect]
        )
        too_small = [rect for rect in all_targets if rect["width"] < 44 or rect["height"] < 44]
        assert too_small == []
        assert all(rect["left"] >= 0 and rect["right"] <= rect["viewportWidth"] for rect in all_targets)
        assert all(rect["opacity"] > 0 for rect in trends_targets["glossary"])
        assert all(rect["visibility"] == "visible" for rect in trends_targets["glossary"])
        assert all(rect["pointerEvents"] != "none" for rect in trends_targets["glossary"])

class TestDesktopCorrelationLayout:
    """Desktop correlation timeline layout behavior."""

    def test_correlation_timeline_sticky_header_uses_opaque_backdrop(self, page, live_server):
        """Sticky Unified Timeline headers should mask rows while scrolling."""
        page.set_viewport_size({"width": 1366, "height": 768})
        page.goto(live_server)
        page.wait_for_load_state("networkidle")
        page.evaluate("switchView('correlation')")
        page.wait_for_selector("#correlation-table-card", state="visible")
        page.wait_for_selector("#correlation-tbody tr[data-ts]")
        page.locator("#correlation-table-wrap").evaluate("wrap => { wrap.style.maxHeight = '96px'; }")

        header_state = page.locator("#correlation-table thead th").first.evaluate(
            r"""
            (th) => {
                const wrap = document.querySelector('#correlation-table-wrap');
                const canScroll = wrap.scrollHeight > wrap.clientHeight;
                wrap.scrollTop = 80;
                const style = getComputedStyle(th);
                const bg = style.backgroundColor;
                const match = bg.match(/rgba?\(([^)]+)\)/);
                let alpha = 1;
                if (match) {
                    const parts = match[1].split(',').map((part) => part.trim());
                    if (parts.length === 4) alpha = Number(parts[3]);
                }
                const rect = th.getBoundingClientRect();
                const topElement = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
                return {
                    backgroundColor: bg,
                    alpha,
                    canScroll,
                    position: style.position,
                    scrollTop: wrap.scrollTop,
                    zIndex: Number(style.zIndex) || 0,
                    topElementTag: topElement ? topElement.tagName : null,
                };
            }
            """
        )

        assert header_state["canScroll"] is True
        assert header_state["scrollTop"] > 0
        assert header_state["position"] == "sticky"
        assert header_state["topElementTag"] == "TH"
        assert header_state["alpha"] >= 0.98, header_state["backgroundColor"]
