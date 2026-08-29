"""Visual QA tests for in-app glossary feature.

Screenshots saved to tests/e2e/screenshots/glossary/ for manual review.
"""

import os

import pytest
from playwright.sync_api import expect


SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots", "glossary")


@pytest.fixture(autouse=True, scope="module")
def ensure_screenshot_dir():
    """Create screenshot output directory."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


class TestGlossaryVisualDesktop:
    """Desktop screenshots of glossary popovers."""

    def test_screenshot_dashboard_with_hints(self, demo_page):
        demo_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "dashboard_hints.png"),
            full_page=False,
        )
        hints = demo_page.locator('#view-dashboard .glossary-hint')
        assert hints.count() >= 4

    def test_screenshot_popover_open(self, demo_page):
        hint = demo_page.locator('#view-dashboard .glossary-hint').first
        hint.click()
        demo_page.wait_for_timeout(300)
        expect(demo_page.locator('body > .glossary-popover')).to_be_visible()
        demo_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "popover_open.png"),
            full_page=False,
        )

    def test_screenshot_channel_popover(self, demo_page):
        """Screenshot channel group header with glossary popover (on dashboard)."""
        hint = demo_page.locator('#view-dashboard .docsis-group-header .glossary-hint').first
        hint.click()
        demo_page.wait_for_timeout(300)
        demo_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "channel_popover.png"),
            full_page=False,
        )

    def test_screenshot_modulation_popovers(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.wait_for_timeout(2000)
        hint = demo_page.locator('#view-modulation .glossary-hint').first
        hint.click()
        demo_page.wait_for_timeout(300)
        demo_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "modulation_popover.png"),
            full_page=False,
        )


class TestGlossaryVisualMobile:
    """Mobile viewport screenshots of glossary popovers."""

    @pytest.fixture()
    def mobile_page(self, page, live_server):
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(live_server)
        page.wait_for_load_state("networkidle")
        return page

    def test_screenshot_mobile_dashboard(self, mobile_page):
        mobile_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "mobile_dashboard.png"),
            full_page=False,
        )

    def test_screenshot_mobile_popover(self, mobile_page):
        hint = mobile_page.locator('#view-dashboard .glossary-hint').first
        hint.click()
        mobile_page.wait_for_timeout(300)
        mobile_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "mobile_popover.png"),
            full_page=False,
        )

    def test_screenshot_mobile_tkg_law_appendix(self, mobile_page):
        origin = mobile_page.evaluate("location.origin")
        mobile_page.goto(f"{origin}/?lang=de&term=tkg_rights_de#glossary?term=tkg_rights_de")
        mobile_page.wait_for_selector("#view-glossary.active", state="visible")
        mobile_page.locator(
            '#view-glossary .glossary-term-article[data-term-id="tkg_rights_de"] summary'
        ).click()
        mobile_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "mobile_tkg_law_appendix.png"),
            full_page=True,
        )


class TestGlossaryVisualLightTheme:
    """Light theme screenshots."""

    @pytest.fixture()
    def light_page(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("networkidle")
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.wait_for_timeout(300)
        return page

    def test_screenshot_light_popover(self, light_page):
        hint = light_page.locator('#view-dashboard .glossary-hint').first
        hint.click()
        light_page.wait_for_timeout(300)
        light_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "light_popover.png"),
            full_page=False,
        )

    def test_screenshot_light_tkg_law_appendix(self, light_page):
        light_page.set_viewport_size({"width": 1440, "height": 950})
        origin = light_page.evaluate("location.origin")
        light_page.goto(f"{origin}/?lang=de&term=tkg_rights_de#glossary?term=tkg_rights_de")
        light_page.wait_for_selector("#view-glossary.active", state="visible")
        light_page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        light_page.locator(
            '#view-glossary .glossary-term-article[data-term-id="tkg_rights_de"] summary'
        ).click()
        light_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "light_tkg_law_appendix.png"),
            full_page=True,
        )
