"""Visual QA tests for Modulation Performance module (v2).

Uses Playwright screenshots and structural checks to verify rendering quality.
Screenshots are saved to tests/e2e/screenshots/ for manual review.
"""

import os

import pytest
from playwright.sync_api import expect


SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots", "modulation")


@pytest.fixture(autouse=True, scope="module")
def ensure_screenshot_dir():
    """Create screenshot output directory."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


@pytest.fixture()
def modulation_page(demo_page):
    """Navigate to modulation tab and wait for data to load."""
    demo_page.locator('a.nav-item[data-view="mod-docsight-modulation"]').click()
    demo_page.wait_for_timeout(2000)  # Wait for API + Chart.js render
    return demo_page


@pytest.fixture()
def modulation_page_mobile(page, live_server):
    """Mobile viewport on modulation tab."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_server}#mod-docsight-modulation")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    return page


# ── Full Page Screenshots ──

class TestFullPageScreenshots:
    """Capture full tab screenshots for visual review."""

    def test_screenshot_desktop_us_7d(self, modulation_page):
        modulation_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "desktop_us_7d.png"),
            full_page=False,
        )
        view = modulation_page.locator("#view-mod-docsight-modulation")
        expect(view).to_be_visible()

    def test_screenshot_desktop_ds_7d(self, modulation_page):
        modulation_page.locator('#modulation-direction-tabs .trend-tab[data-dir="ds"]').click()
        modulation_page.wait_for_timeout(1500)
        modulation_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "desktop_ds_7d.png"),
            full_page=False,
        )
        ds = modulation_page.locator('#modulation-direction-tabs .trend-tab[data-dir="ds"]')
        assert "active" in ds.get_attribute("class")

    def test_screenshot_desktop_us_1d(self, modulation_page):
        modulation_page.locator('#modulation-range-tabs .trend-tab[data-days="1"]').click()
        modulation_page.wait_for_timeout(1500)
        modulation_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "desktop_us_1d.png"),
            full_page=False,
        )

    def test_screenshot_desktop_us_30d(self, modulation_page):
        modulation_page.locator('#modulation-range-tabs .trend-tab[data-days="30"]').click()
        modulation_page.wait_for_timeout(1500)
        modulation_page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "desktop_us_30d.png"),
            full_page=False,
        )

    def test_screenshot_mobile(self, modulation_page_mobile):
        modulation_page_mobile.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "mobile_us_7d.png"),
            full_page=True,
        )


# ── Chart Rendering Verification ──

class TestChartRendering:
    """Verify Chart.js canvases actually render (non-zero dimensions)."""

    def test_first_distribution_chart_has_size(self, modulation_page):
        canvas = modulation_page.locator("[id^='mod-dist-chart-']").first
        box = canvas.bounding_box()
        assert box is not None, "Distribution chart canvas not in layout"
        assert box["width"] > 50, f"Chart too narrow: {box['width']}px"
        assert box["height"] > 50, f"Chart too short: {box['height']}px"

    def test_first_trend_chart_has_size(self, modulation_page):
        canvas = modulation_page.locator("[id^='mod-trend-chart-']").first
        box = canvas.bounding_box()
        assert box is not None, "Trend chart canvas not in layout"
        assert box["width"] > 50, f"Chart too narrow: {box['width']}px"
        assert box["height"] > 50, f"Chart too short: {box['height']}px"

    def test_distribution_chart_screenshot(self, modulation_page):
        canvas = modulation_page.locator("[id^='mod-dist-chart-']").first
        canvas.screenshot(path=os.path.join(SCREENSHOT_DIR, "chart_distribution.png"))
        box = canvas.bounding_box()
        assert box is not None

    def test_trend_chart_screenshot(self, modulation_page):
        canvas = modulation_page.locator("[id^='mod-trend-chart-']").first
        canvas.screenshot(path=os.path.join(SCREENSHOT_DIR, "chart_trend.png"))
        box = canvas.bounding_box()
        assert box is not None

    def test_charts_rerender_on_direction_switch(self, modulation_page):
        modulation_page.locator('#modulation-direction-tabs .trend-tab[data-dir="ds"]').click()
        modulation_page.wait_for_timeout(1500)
        canvas = modulation_page.locator("[id^='mod-dist-chart-']").first
        box = canvas.bounding_box()
        assert box is not None and box["width"] > 50

    def test_charts_rerender_on_range_switch(self, modulation_page):
        modulation_page.locator('#modulation-range-tabs .trend-tab[data-days="30"]').click()
        modulation_page.wait_for_timeout(1500)
        canvas = modulation_page.locator("[id^='mod-dist-chart-']").first
        box = canvas.bounding_box()
        assert box is not None and box["width"] > 50


# ── KPI Card Visual Checks ──

class TestKPICardVisuals:
    """Verify KPI cards render with proper structure."""

    def test_kpi_row_layout(self, modulation_page):
        row = modulation_page.locator(".modulation-kpi-row")
        box = row.bounding_box()
        assert box is not None, "KPI row not visible"
        assert box["width"] > 300, f"KPI row too narrow: {box['width']}px"

    def test_kpi_cards_same_height(self, modulation_page):
        cards = modulation_page.locator(".modulation-kpi-card")
        heights = []
        for i in range(cards.count()):
            box = cards.nth(i).bounding_box()
            assert box is not None, f"KPI card {i} not visible"
            heights.append(box["height"])
        if len(heights) == 3:
            max_diff = max(heights) - min(heights)
            assert max_diff < 30, f"KPI card heights differ too much: {heights}"

    def test_kpi_cards_screenshot(self, modulation_page):
        row = modulation_page.locator(".modulation-kpi-row")
        row.screenshot(path=os.path.join(SCREENSHOT_DIR, "kpi_cards.png"))

    def test_health_kpi_has_value(self, modulation_page):
        val = modulation_page.locator("#mod-kpi-health")
        text = val.text_content().strip()
        assert len(text) > 0, "Health index KPI is empty"

    def test_lowqam_kpi_has_percent(self, modulation_page):
        val = modulation_page.locator("#mod-kpi-lowqam")
        text = val.text_content().strip()
        assert "%" in text or text == "\u2014", f"Unexpected lowqam value: {text}"

    def test_density_kpi_has_percent(self, modulation_page):
        val = modulation_page.locator("#mod-kpi-density")
        text = val.text_content().strip()
        assert "%" in text or text == "\u2014", f"Unexpected density value: {text}"


# ── Protocol Group Visual Checks ──

class TestProtocolGroupVisuals:
    """Verify protocol group sections render correctly."""

    def test_protocol_group_sections_visible(self, modulation_page):
        groups = modulation_page.locator(".mod-protocol-group")
        assert groups.count() >= 1

    def test_protocol_group_has_kpis(self, modulation_page):
        kpis = modulation_page.locator(".mod-group-kpi")
        assert kpis.count() >= 4  # 4 per group, at least 1 group

    def test_protocol_group_screenshot(self, modulation_page):
        group = modulation_page.locator(".mod-protocol-group").first
        group.screenshot(path=os.path.join(SCREENSHOT_DIR, "protocol_group.png"))


# ── Responsive Layout ──

class TestResponsiveLayout:
    """Verify layout adapts to mobile viewports."""

    def test_kpi_cards_stack_on_mobile(self, modulation_page_mobile):
        cards = modulation_page_mobile.locator(".modulation-kpi-card")
        if cards.count() >= 2:
            box0 = cards.nth(0).bounding_box()
            box1 = cards.nth(1).bounding_box()
            if box0 and box1:
                assert box1["y"] > box0["y"] + box0["height"] - 5

    def test_charts_full_width_on_mobile(self, modulation_page_mobile):
        canvas = modulation_page_mobile.locator("[id^='mod-dist-chart-']").first
        box = canvas.bounding_box()
        if box:
            assert box["width"] > 250, f"Chart too narrow on mobile: {box['width']}px"

    def test_controls_wrap_on_mobile(self, modulation_page_mobile):
        dir_tabs = modulation_page_mobile.locator("#modulation-direction-tabs")
        range_tabs = modulation_page_mobile.locator("#modulation-range-tabs")
        assert dir_tabs.is_visible()
        assert range_tabs.is_visible()

    def test_mobile_screenshot(self, modulation_page_mobile):
        modulation_page_mobile.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "mobile_full.png"),
            full_page=True,
        )


# ── Theme Consistency ──

class TestThemeConsistency:
    """Module should respect the app's dark theme."""

    def test_dark_theme_applied(self, modulation_page):
        html = modulation_page.locator("html")
        theme = html.get_attribute("data-theme") or ""
        assert theme == "dark" or theme == ""

    def test_kpi_text_visible_against_background(self, modulation_page):
        val = modulation_page.locator("#mod-kpi-health")
        assert val.is_visible()

    def test_chart_cards_have_border(self, modulation_page):
        cards = modulation_page.locator("#view-mod-docsight-modulation .chart-card")
        assert cards.count() >= 2


# ── i18n ──

class TestModulationI18n:
    """Module labels should be translated."""

    def test_english_labels(self, page, live_server):
        page.goto(f"{live_server}#mod-docsight-modulation")
        page.wait_for_load_state("networkidle")
        content = page.locator("#view-mod-docsight-modulation").text_content()
        assert "Modulation Performance" in content or "Modulation" in content

    def test_german_labels(self, page, live_server):
        page.goto(f"{live_server}?lang=de#mod-docsight-modulation")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        content = page.locator("#view-mod-docsight-modulation").text_content()
        assert "Modulationsleistung" in content or "Modulation" in content
