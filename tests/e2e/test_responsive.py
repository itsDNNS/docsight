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
