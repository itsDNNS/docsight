"""E2E tests for the Before/After Comparison feature."""

from playwright.sync_api import expect


def navigate_to_comparison(page):
    """Open the comparison view and wait for the control bar."""
    page.locator('a.nav-item[data-view="comparison"]').click()
    expect(page.locator("#comparison-controls")).to_be_visible()


class TestComparisonView:
    def test_nav_item_visible(self, demo_page):
        nav = demo_page.locator('a.nav-item[data-view="comparison"]')
        assert nav.count() == 1

    def test_run_comparison_shows_health_distribution(self, demo_page):
        navigate_to_comparison(demo_page)
        demo_page.locator("#comparison-run-btn").click()

        expect(demo_page.locator("#comparison-health")).to_be_visible()
        assert demo_page.locator("#comparison-health-bars-a .comparison-health-row").count() == 5
        assert demo_page.locator("#comparison-health-bars-b .comparison-health-row").count() == 5

    def test_comparison_can_open_report_modal_with_attached_evidence(self, demo_page):
        navigate_to_comparison(demo_page)
        demo_page.locator("#comparison-run-btn").click()
        expect(demo_page.locator("#comparison-health")).to_be_visible()

        demo_page.locator("button.comparison-report-btn").click()
        expect(demo_page.locator("#report-modal")).to_have_class("modal-overlay open")

        comparison_toggle = demo_page.locator("#report-include-comparison")
        expect(comparison_toggle).to_be_enabled()
        expect(comparison_toggle).to_be_checked()

        note = demo_page.locator("#report-comparison-note")
        expect(note).to_contain_text("attached")
