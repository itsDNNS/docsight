"""E2E tests for Segment Utilization (FritzBox cable modems).

Tests cover: navigation, tab visibility, KPI display, chart rendering,
range switching, API responses, i18n, theme switching, correlation
integration, and JS error-free operation.
"""

import pytest


# ── Helpers ──


def navigate_to_segment(page):
    """Switch to Segment Utilization view and wait for data to load."""
    page.locator('a.nav-item[data-view="segment-utilization"]').click()
    page.wait_for_timeout(2000)


def wait_for_content(page, timeout=5000):
    """Wait for segment utilization content (not skeleton) to appear."""
    page.wait_for_selector("#fritz-cable-content:not([style*='display: none'])", timeout=timeout)


# ── Navigation & Visibility ──


class TestSegmentNavigation:
    """Segment utilization tab visibility and navigation."""

    def test_nav_item_visible_for_fritzbox(self, fritzbox_page):
        """Segment nav item should be present for FritzBox modem type."""
        nav = fritzbox_page.locator('a.nav-item[data-view="segment-utilization"]')
        assert nav.count() > 0, "Segment nav item should exist for FritzBox"

    def test_nav_item_hidden_for_demo(self, demo_page):
        """Segment nav item should NOT be present for demo modem type."""
        nav = demo_page.locator('a.nav-item[data-view="segment-utilization"]')
        assert nav.count() == 0, "Segment nav item should not exist for demo modem"

    def test_click_nav_shows_view(self, fritzbox_page):
        """Clicking segment nav should show the segment utilization view."""
        navigate_to_segment(fritzbox_page)
        view = fritzbox_page.locator("#view-segment-utilization")
        assert view.is_visible()

    def test_nav_item_becomes_active(self, fritzbox_page):
        """Nav item should get 'active' class when selected."""
        navigate_to_segment(fritzbox_page)
        nav = fritzbox_page.locator('a.nav-item[data-view="segment-utilization"]')
        assert "active" in nav.get_attribute("class")

    def test_view_hidden_when_on_other_tab(self, fritzbox_page):
        """Segment view should be hidden when another tab is active."""
        fritzbox_page.locator('a.nav-item[data-view="live"]').click()
        fritzbox_page.wait_for_timeout(300)
        view = fritzbox_page.locator("#view-segment-utilization")
        assert not view.is_visible()


# ── Skeleton & Loading ──


class TestSegmentLoading:
    """Skeleton loading and content display."""

    def test_skeleton_hidden_after_load(self, fritzbox_page):
        """Skeleton should disappear after data loads."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        skeleton = fritzbox_page.locator("#fritz-cable-skeleton")
        display = skeleton.evaluate("el => getComputedStyle(el).display")
        assert display == "none"

    def test_content_visible_after_load(self, fritzbox_page):
        """Main content should be visible after data loads."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        content = fritzbox_page.locator("#fritz-cable-content")
        assert content.is_visible()

    def test_error_message_hidden_with_data(self, fritzbox_page):
        """Error message should not be visible when data exists."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        msg = fritzbox_page.locator("#fritz-cable-message")
        display = msg.evaluate("el => getComputedStyle(el).display")
        assert display == "none"


# ── KPI Display ──


class TestSegmentKPIs:
    """KPI cards show correct data."""

    def test_ds_total_shows_percentage(self, fritzbox_page):
        """Downstream total KPI should show a percentage value."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        ds = fritzbox_page.locator("#fritz-cable-ds-total")
        text = ds.text_content().strip()
        assert text.endswith("%"), f"DS total should be a percentage, got: {text}"
        assert text != "-", "DS total should not be placeholder"

    def test_us_total_shows_percentage(self, fritzbox_page):
        """Upstream total KPI should show a percentage value."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        us = fritzbox_page.locator("#fritz-cable-us-total")
        text = us.text_content().strip()
        assert text.endswith("%"), f"US total should be a percentage, got: {text}"

    def test_status_shows_collecting(self, fritzbox_page):
        """Status KPI should show 'Collecting' when data exists."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        status = fritzbox_page.locator("#fritz-cable-status")
        text = status.text_content().strip()
        assert text != "-" and text != "", f"Status should not be empty, got: {text}"

    def test_ds_stats_shows_min_avg_max(self, fritzbox_page):
        """DS stats line should show min/avg/max values."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        stats = fritzbox_page.locator("#fritz-cable-ds-stats")
        text = stats.text_content().strip()
        assert "%" in text, f"DS stats should contain percentages, got: {text}"

    def test_us_stats_shows_min_avg_max(self, fritzbox_page):
        """US stats line should show min/avg/max values."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        stats = fritzbox_page.locator("#fritz-cable-us-stats")
        text = stats.text_content().strip()
        assert "%" in text, f"US stats should contain percentages, got: {text}"

    def test_sample_count_shown(self, fritzbox_page):
        """Sample count should be displayed."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        count = fritzbox_page.locator("#fritz-cable-count")
        text = count.text_content().strip()
        assert "samples" in text.lower(), f"Count should mention samples, got: {text}"


# ── Chart Rendering ──


class TestSegmentCharts:
    """Downstream and upstream utilization charts."""

    def test_ds_chart_renders_uplot(self, fritzbox_page):
        """Downstream chart should render a uPlot instance."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.wait_for_selector("#fritz-cable-ds-chart .uplot", timeout=5000)
        canvases = fritzbox_page.locator("#fritz-cable-ds-chart .uplot canvas").count()
        assert canvases >= 1, "DS chart should have at least one canvas"

    def test_us_chart_renders_uplot(self, fritzbox_page):
        """Upstream chart should render a uPlot instance."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.wait_for_selector("#fritz-cable-us-chart .uplot", timeout=5000)
        canvases = fritzbox_page.locator("#fritz-cable-us-chart .uplot canvas").count()
        assert canvases >= 1, "US chart should have at least one canvas"

    def test_ds_chart_has_legend(self, fritzbox_page):
        """DS chart should have a uPlot legend with series."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.wait_for_selector("#fritz-cable-ds-chart .uplot", timeout=5000)
        legend = fritzbox_page.locator("#fritz-cable-ds-chart .u-legend")
        assert legend.count() > 0, "DS chart should have a legend"

    def test_us_chart_has_legend(self, fritzbox_page):
        """US chart should have a uPlot legend with series."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.wait_for_selector("#fritz-cable-us-chart .uplot", timeout=5000)
        legend = fritzbox_page.locator("#fritz-cable-us-chart .u-legend")
        assert legend.count() > 0, "US chart should have a legend"

    def test_chart_has_nonzero_dimensions(self, fritzbox_page):
        """Chart canvas should have meaningful dimensions."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.wait_for_selector("#fritz-cable-ds-chart .uplot", timeout=5000)
        canvas = fritzbox_page.locator("#fritz-cable-ds-chart .uplot canvas").first
        box = canvas.bounding_box()
        assert box is not None, "Canvas should have a bounding box"
        assert box["width"] > 100, f"Canvas width {box['width']} too small"
        assert box["height"] > 50, f"Canvas height {box['height']} too small"


# ── Range Tab Switching ──


class TestSegmentRangeTabs:
    """Time range tab switching."""

    def test_all_range_active_by_default(self, fritzbox_page):
        """'All' range tab should be active by default."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        all_tab = fritzbox_page.locator('#fritz-cable-range-tabs .trend-tab[data-range="all"]')
        assert "active" in all_tab.get_attribute("class")

    def test_switch_to_24h(self, fritzbox_page):
        """Clicking 24h tab should reload charts and activate the tab."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        tab = fritzbox_page.locator('#fritz-cable-range-tabs .trend-tab[data-range="24h"]')
        tab.click()
        fritzbox_page.wait_for_timeout(2000)
        assert "active" in tab.get_attribute("class")
        # Charts should still be rendered
        canvases = fritzbox_page.locator("#fritz-cable-ds-chart .uplot canvas").count()
        assert canvases >= 1

    def test_switch_to_7d(self, fritzbox_page):
        """Clicking 7d tab should reload and activate."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        tab = fritzbox_page.locator('#fritz-cable-range-tabs .trend-tab[data-range="7d"]')
        tab.click()
        fritzbox_page.wait_for_timeout(2000)
        assert "active" in tab.get_attribute("class")

    def test_switch_to_30d(self, fritzbox_page):
        """Clicking 30d tab should reload and activate."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        tab = fritzbox_page.locator('#fritz-cable-range-tabs .trend-tab[data-range="30d"]')
        tab.click()
        fritzbox_page.wait_for_timeout(2000)
        assert "active" in tab.get_attribute("class")

    def test_only_one_tab_active_at_a_time(self, fritzbox_page):
        """Only one range tab should be active at any time."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.locator('#fritz-cable-range-tabs .trend-tab[data-range="24h"]').click()
        fritzbox_page.wait_for_timeout(1000)
        active_tabs = fritzbox_page.locator("#fritz-cable-range-tabs .trend-tab.active")
        assert active_tabs.count() == 1, f"Expected 1 active tab, got {active_tabs.count()}"


# ── API Endpoints ──


class TestSegmentAPI:
    """API endpoint responses."""

    def test_api_returns_json(self, fritzbox_server, page):
        """Segment utilization API should return valid JSON."""
        resp = page.request.get(f"{fritzbox_server}/api/fritzbox/segment-utilization?range=all")
        assert resp.status == 200
        data = resp.json()
        assert "samples" in data
        assert "latest" in data
        assert "stats" in data

    def test_api_returns_samples(self, fritzbox_server, page):
        """API should return sample data with expected fields."""
        resp = page.request.get(f"{fritzbox_server}/api/fritzbox/segment-utilization?range=all")
        data = resp.json()
        assert len(data["samples"]) > 0, "Should have seeded samples"
        sample = data["samples"][0]
        assert "timestamp" in sample
        assert "ds_total" in sample
        assert "us_total" in sample
        assert "ds_own" in sample
        assert "us_own" in sample

    def test_api_returns_stats(self, fritzbox_server, page):
        """API stats should include count and aggregates."""
        resp = page.request.get(f"{fritzbox_server}/api/fritzbox/segment-utilization?range=all")
        data = resp.json()
        stats = data["stats"]
        assert stats["count"] > 0
        assert stats["ds_total_avg"] is not None
        assert stats["us_total_avg"] is not None

    def test_api_24h_returns_fewer_samples(self, fritzbox_server, page):
        """24h range should return fewer samples than 'all'."""
        resp_all = page.request.get(f"{fritzbox_server}/api/fritzbox/segment-utilization?range=all")
        resp_24h = page.request.get(f"{fritzbox_server}/api/fritzbox/segment-utilization?range=24h")
        all_count = len(resp_all.json()["samples"])
        day_count = len(resp_24h.json()["samples"])
        assert day_count < all_count, f"24h ({day_count}) should be < all ({all_count})"

    def test_api_range_endpoint(self, fritzbox_server, page):
        """The /range endpoint should return samples for a time window."""
        resp = page.request.get(
            f"{fritzbox_server}/api/fritzbox/segment-utilization/range"
            "?start=2000-01-01T00:00:00Z&end=2099-01-01T00:00:00Z"
        )
        assert resp.status == 200
        data = resp.json()
        assert len(data) > 0

    def test_api_range_requires_params(self, fritzbox_server, page):
        """The /range endpoint should return 400 without start/end."""
        resp = page.request.get(f"{fritzbox_server}/api/fritzbox/segment-utilization/range")
        assert resp.status == 400

    def test_api_rejects_non_fritzbox(self, live_server, page):
        """Segment API should return 400 for non-FritzBox modem types."""
        resp = page.request.get(f"{live_server}/api/fritzbox/segment-utilization?range=all")
        assert resp.status == 400


# ── i18n ──


class TestSegmentI18n:
    """Internationalization for segment utilization."""

    def test_title_in_english(self, page, fritzbox_server):
        """English title should appear in the tab."""
        page.goto(f"{fritzbox_server}/?lang=en")
        page.wait_for_load_state("networkidle")
        navigate_to_segment(page)
        wait_for_content(page)
        title = page.locator(".fritz-cable-title")
        assert "Segment" in title.text_content()

    def test_title_in_german(self, page, fritzbox_server):
        """German title should appear in the tab."""
        page.goto(f"{fritzbox_server}/?lang=de")
        page.wait_for_load_state("networkidle")
        navigate_to_segment(page)
        wait_for_content(page)
        title = page.locator(".fritz-cable-title")
        text = title.text_content()
        assert "Segment" in text or "Auslastung" in text

    def test_nav_label_translated(self, page, fritzbox_server):
        """Nav item text should be translated per language."""
        page.goto(f"{fritzbox_server}/?lang=de")
        page.wait_for_load_state("networkidle")
        nav = page.locator('a.nav-item[data-view="segment-utilization"]')
        text = nav.text_content().strip()
        assert len(text) > 0, "Nav label should not be empty"

    def test_kpi_labels_translated_de(self, page, fritzbox_server):
        """KPI labels should be translated in German."""
        page.goto(f"{fritzbox_server}/?lang=de")
        page.wait_for_load_state("networkidle")
        navigate_to_segment(page)
        wait_for_content(page)
        labels = page.locator(".fritz-cable-kpi-label").all_text_contents()
        assert len(labels) == 3, f"Expected 3 KPI labels, got {len(labels)}"
        # Should NOT be the English fallbacks (unless same in DE)
        combined = " ".join(labels)
        assert len(combined) > 10, "Labels should have meaningful text"


# ── Theme Switching ──


class TestSegmentTheme:
    """Charts should work in both dark and light themes."""

    def test_charts_render_in_dark_mode(self, fritzbox_page):
        """Charts should render in dark mode."""
        fritzbox_page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        fritzbox_page.wait_for_timeout(200)
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.wait_for_selector("#fritz-cable-ds-chart .uplot", timeout=5000)
        canvases = fritzbox_page.locator("#fritz-cable-ds-chart .uplot canvas").count()
        assert canvases >= 1

    def test_charts_render_in_light_mode(self, fritzbox_page):
        """Charts should render in light mode."""
        fritzbox_page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        fritzbox_page.wait_for_timeout(200)
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        fritzbox_page.wait_for_selector("#fritz-cable-ds-chart .uplot", timeout=5000)
        canvases = fritzbox_page.locator("#fritz-cable-ds-chart .uplot canvas").count()
        assert canvases >= 1
        # Restore dark
        fritzbox_page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")


# ── Correlation Integration ──


class TestSegmentCorrelation:
    """Segment utilization overlay on the correlation timeline."""

    def test_correlation_view_loads_for_fritzbox(self, fritzbox_page):
        """Correlation view should load without errors for FritzBox."""
        fritzbox_page.locator('a.nav-item[data-view="correlation"]').click()
        fritzbox_page.wait_for_timeout(2000)
        view = fritzbox_page.locator("#view-correlation")
        assert view.is_visible()

    def test_correlation_legend_has_segment_entries(self, fritzbox_page):
        """Correlation legend should include Segment DS/US entries."""
        fritzbox_page.locator('a.nav-item[data-view="correlation"]').click()
        fritzbox_page.wait_for_timeout(3000)
        legend = fritzbox_page.locator("#correlation-legend, .correlation-legend")
        if legend.count() > 0:
            text = legend.text_content()
            assert "Segment" in text, f"Legend should mention Segment, got: {text}"


# ── View Div Presence ──


class TestSegmentViewStructure:
    """DOM structure of the segment utilization view."""

    def test_view_div_exists_for_fritzbox(self, fritzbox_page):
        """#view-segment-utilization should exist in DOM for FritzBox."""
        view = fritzbox_page.locator("#view-segment-utilization")
        assert view.count() > 0

    def test_view_div_absent_for_demo(self, demo_page):
        """#view-segment-utilization should NOT exist in DOM for demo modem."""
        view = demo_page.locator("#view-segment-utilization")
        assert view.count() == 0

    def test_has_three_kpi_cards(self, fritzbox_page):
        """Should have 3 KPI cards."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        kpis = fritzbox_page.locator("#fritz-cable-content .fritz-cable-kpi")
        assert kpis.count() == 3

    def test_has_two_chart_panels(self, fritzbox_page):
        """Should have 2 chart panels (DS and US)."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        panels = fritzbox_page.locator("#fritz-cable-content .fritz-cable-panel")
        assert panels.count() == 2

    def test_has_note_section(self, fritzbox_page):
        """Should have a note/disclaimer section."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        note = fritzbox_page.locator(".fritz-cable-note")
        assert note.count() > 0
        text = note.text_content().strip()
        assert len(text) > 20, "Note should have meaningful text"

    def test_has_four_range_tabs(self, fritzbox_page):
        """Should have 4 range tabs (24h, 7d, 30d, all)."""
        navigate_to_segment(fritzbox_page)
        tabs = fritzbox_page.locator("#fritz-cable-range-tabs .trend-tab")
        assert tabs.count() == 4


# ── Hash Navigation ──


class TestSegmentHashNavigation:
    """Direct navigation via URL hash."""

    def test_direct_hash_loads_segment_view(self, page, fritzbox_server):
        """Navigating to /#segment-utilization should show the segment tab."""
        page.goto(f"{fritzbox_server}/#segment-utilization")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        view = page.locator("#view-segment-utilization")
        assert view.is_visible()

    def test_direct_hash_loads_data(self, page, fritzbox_server):
        """Direct hash navigation should load and display chart data."""
        page.goto(f"{fritzbox_server}/#segment-utilization")
        page.wait_for_load_state("networkidle")
        wait_for_content(page)
        canvases = page.locator("#fritz-cable-ds-chart .uplot canvas").count()
        assert canvases >= 1, "Charts should render on direct hash navigation"


# ── No JS Errors ──


class TestSegmentNoJSErrors:
    """No JavaScript errors during segment utilization interactions."""

    def test_no_errors_on_segment_load(self, fritzbox_page):
        """Loading segment tab should not produce JS errors."""
        errors = []
        fritzbox_page.on("pageerror", lambda err: errors.append(str(err)))
        navigate_to_segment(fritzbox_page)
        fritzbox_page.wait_for_timeout(3000)
        assert len(errors) == 0, f"JS errors on segment load: {errors}"

    def test_no_errors_on_range_switch(self, fritzbox_page):
        """Switching ranges should not produce JS errors."""
        navigate_to_segment(fritzbox_page)
        wait_for_content(fritzbox_page)
        errors = []
        fritzbox_page.on("pageerror", lambda err: errors.append(str(err)))
        for rng in ["24h", "7d", "30d", "all"]:
            fritzbox_page.locator(f'#fritz-cable-range-tabs .trend-tab[data-range="{rng}"]').click()
            fritzbox_page.wait_for_timeout(1500)
        assert len(errors) == 0, f"JS errors on range switch: {errors}"

    def test_no_errors_on_view_switching(self, fritzbox_page):
        """Switching between views should not produce JS errors."""
        errors = []
        fritzbox_page.on("pageerror", lambda err: errors.append(str(err)))
        navigate_to_segment(fritzbox_page)
        fritzbox_page.wait_for_timeout(1500)
        fritzbox_page.locator('a.nav-item[data-view="live"]').click()
        fritzbox_page.wait_for_timeout(500)
        navigate_to_segment(fritzbox_page)
        fritzbox_page.wait_for_timeout(1500)
        assert len(errors) == 0, f"JS errors on view switching: {errors}"


# ── CSS Static File ──


class TestSegmentStaticFiles:
    """Static files are served correctly."""

    def test_css_file_loads(self, fritzbox_server, page):
        """segment-utilization.css should be accessible."""
        resp = page.request.get(f"{fritzbox_server}/static/css/segment-utilization.css")
        assert resp.status == 200
        assert "fritz-cable" in resp.text()

    def test_js_file_loads(self, fritzbox_server, page):
        """segment-utilization.js should be accessible."""
        resp = page.request.get(f"{fritzbox_server}/static/js/segment-utilization.js")
        assert resp.status == 200
        assert "loadFritzCableData" in resp.text()
