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

    def test_bottom_nav_visible_on_mobile(self, mobile_page):
        bottom_nav = mobile_page.locator("nav.bottom-nav")
        assert bottom_nav.is_visible()

    def test_bottom_nav_has_tabs(self, mobile_page):
        tabs = mobile_page.locator(".bottom-nav-item")
        assert tabs.count() >= 4

    def test_mobile_nav_customization_updates_sidebar_and_bottom_bar(self, mobile_page):
        mobile_page.locator("#hamburger").click()
        mobile_page.get_by_role("button", name="Customize Navigation").click()

        modal = mobile_page.locator("#nav-customize-overlay.open")
        modal.wait_for()

        comparison_row = modal.locator(".nav-customize-row").filter(
            has_text="Before/After Comparison"
        ).first
        comparison_row.locator('button[data-nav-action="toggle-pin"]').click()
        mobile_page.wait_for_timeout(150)

        bottom_labels = mobile_page.locator(".bottom-nav-item span").all_inner_texts()
        assert "Before/After Comparison" in bottom_labels
        assert bottom_labels[-1] == "More"

        channels_row = modal.locator(".nav-customize-row").filter(
            has_text="Channels"
        ).first
        channels_row.locator('button[data-nav-action="move-up"]').click()
        mobile_page.wait_for_timeout(150)

        modal.get_by_role("button", name="Done").click()
        mobile_page.wait_for_timeout(150)

        monitoring_texts = [
            text.strip()
            for text in mobile_page.locator(
                '.nav-section[data-nav-section="monitoring"] .nav-section-items > .nav-item'
            ).all_inner_texts()
        ]
        assert monitoring_texts.index("Channels") < monitoring_texts.index("Signal Trends")
