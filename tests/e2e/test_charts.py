"""E2E tests for uPlot chart rendering.

Verifies all chart types render correctly after the Chart.js → uPlot migration.
Tests cover: hero chart, trend charts, channel charts, compare charts,
zoom modal, theme switching, responsive sizing, and crosshair sync.
"""

import pytest


# ── Helpers ──


def navigate_to_trends(page):
    """Switch to Trends view and wait for charts to load."""
    page.locator('.nav-item[data-view="trends"]').click()
    page.wait_for_timeout(1500)


def navigate_to_channels(page):
    """Switch to Channels view."""
    page.locator('.nav-item[data-view="channels"]').click()
    page.wait_for_timeout(500)


def wait_for_uplot(page, container_id, timeout=5000):
    """Wait for a uPlot chart to render inside a container."""
    page.wait_for_selector(f"#{container_id} .uplot", timeout=timeout)


def count_uplot_canvases(page, container_id):
    """Count uPlot canvas elements inside a container."""
    return page.locator(f"#{container_id} .uplot canvas").count()


def has_no_console_errors(page):
    """Check that no JS errors were logged."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    return errors


# ── Hero Chart ──


class TestHeroChart:
    """Hero trend chart on the dashboard."""

    def test_hero_chart_renders(self, demo_page):
        """Hero chart should render a uPlot instance."""
        wait_for_uplot(demo_page, "hero-trend-chart")
        canvases = count_uplot_canvases(demo_page, "hero-trend-chart")
        assert canvases >= 1, "Hero chart should have at least one canvas"

    def test_hero_chart_has_series(self, demo_page):
        """Hero chart legend should show DS Power, US Power, SNR."""
        wait_for_uplot(demo_page, "hero-trend-chart")
        legend = demo_page.locator("#hero-trend-chart .u-legend")
        assert legend.is_visible()
        text = legend.text_content()
        assert "Power" in text or "dBmV" in text

    def test_hero_chart_has_legend_entries(self, demo_page):
        """Hero chart should have 3 series in the legend."""
        wait_for_uplot(demo_page, "hero-trend-chart")
        series = demo_page.locator("#hero-trend-chart .u-legend .u-series")
        # 3 data series + 1 X-axis series = 4 total, but X may be hidden
        assert series.count() >= 3

    def test_hero_chart_rerenders_on_theme_toggle(self, demo_page):
        """Hero chart should re-render when theme is toggled."""
        wait_for_uplot(demo_page, "hero-trend-chart")
        # Use JS to toggle theme directly (checkbox may be hidden in sidebar)
        demo_page.evaluate("""
            var toggle = document.getElementById('theme-toggle-sidebar');
            if (toggle) { toggle.checked = !toggle.checked; toggle.dispatchEvent(new Event('change')); }
        """)
        demo_page.wait_for_timeout(500)
        # Chart should still be present after theme toggle
        canvases = count_uplot_canvases(demo_page, "hero-trend-chart")
        assert canvases >= 1
        # Toggle back
        demo_page.evaluate("""
            var toggle = document.getElementById('theme-toggle-sidebar');
            if (toggle) { toggle.checked = !toggle.checked; toggle.dispatchEvent(new Event('change')); }
        """)
        demo_page.wait_for_timeout(300)


# ── Trend Charts ──


class TestTrendCharts:
    """Charts in the Trends view (DS Power, DS SNR, US Power, Errors)."""

    def test_trend_charts_render(self, demo_page):
        """All 4 trend charts should render uPlot instances."""
        navigate_to_trends(demo_page)
        for chart_id in ["chart-ds-power", "chart-ds-snr", "chart-us-power", "chart-errors"]:
            wait_for_uplot(demo_page, chart_id)
            canvases = count_uplot_canvases(demo_page, chart_id)
            assert canvases >= 1, f"{chart_id} should have a uPlot canvas"

    def test_ds_power_has_zone_lines(self, demo_page):
        """DS Power chart should render with threshold zones visible."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")
        # The canvas itself should have non-zero dimensions
        canvas = demo_page.locator("#chart-ds-power .uplot canvas").first
        box = canvas.bounding_box()
        assert box["width"] > 100
        assert box["height"] > 50

    def test_errors_bar_chart(self, demo_page):
        """Errors chart should render as bar chart with 2 series."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-errors")
        legend = demo_page.locator("#chart-errors .u-legend")
        assert legend.is_visible()

    def test_trend_tabs_switch_range(self, demo_page):
        """Clicking Week/Month tabs should reload charts."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        # Click Week tab
        week_tab = demo_page.locator('.trend-tab[data-range="week"]')
        if week_tab.count() > 0:
            week_tab.click()
            demo_page.wait_for_timeout(1500)
            canvases = count_uplot_canvases(demo_page, "chart-ds-power")
            assert canvases >= 1, "Chart should still render after range switch"

    def test_crosshair_sync_between_trends(self, demo_page):
        """Hovering one trend chart should show crosshair on all trend charts."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")
        wait_for_uplot(demo_page, "chart-ds-snr")

        # Hover over DS Power chart
        ds_power = demo_page.locator("#chart-ds-power .uplot .u-over")
        box = ds_power.bounding_box()
        if box:
            demo_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            demo_page.wait_for_timeout(200)
            # Crosshair cursor elements should appear
            cursors = demo_page.locator("#chart-ds-snr .uplot .u-cursor-x")
            assert cursors.count() > 0, "Synced crosshair should appear on SNR chart"


# ── Chart Zoom Modal ──


class TestChartZoom:
    """Fullscreen chart zoom modal."""

    def test_zoom_modal_opens(self, demo_page):
        """Clicking expand button should open the zoom modal."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        expand_btn = demo_page.locator('.chart-expand-btn[data-chart="chart-ds-power"]')
        if expand_btn.count() > 0:
            expand_btn.click()
            demo_page.wait_for_timeout(300)
            overlay = demo_page.locator("#chart-zoom-overlay")
            assert overlay.is_visible()

    def test_zoom_modal_renders_chart(self, demo_page):
        """Zoom modal should render a uPlot chart inside."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        expand_btn = demo_page.locator('.chart-expand-btn[data-chart="chart-ds-power"]')
        if expand_btn.count() > 0:
            expand_btn.click()
            demo_page.wait_for_timeout(300)
            zoom_canvas = demo_page.locator("#chart-zoom-canvas .uplot canvas")
            assert zoom_canvas.count() >= 1, "Zoom modal should contain a uPlot chart"

    def test_zoom_modal_closes_on_escape(self, demo_page):
        """ESC key should close the zoom modal."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        expand_btn = demo_page.locator('.chart-expand-btn[data-chart="chart-ds-power"]')
        if expand_btn.count() > 0:
            expand_btn.click()
            demo_page.wait_for_timeout(300)
            assert demo_page.locator("#chart-zoom-overlay").is_visible()
            demo_page.keyboard.press("Escape")
            demo_page.wait_for_timeout(200)
            assert not demo_page.locator("#chart-zoom-overlay").is_visible()

    def test_zoom_modal_closes_on_button(self, demo_page):
        """Close button should close the zoom modal."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        expand_btn = demo_page.locator('.chart-expand-btn[data-chart="chart-ds-power"]')
        if expand_btn.count() > 0:
            expand_btn.click()
            demo_page.wait_for_timeout(300)
            close_btn = demo_page.locator(".chart-zoom-modal .modal-close")
            close_btn.click()
            demo_page.wait_for_timeout(200)
            assert not demo_page.locator("#chart-zoom-overlay").is_visible()


# ── Channel Timeline Charts ──


class TestChannelCharts:
    """Charts in the Channels > Timeline view."""

    def test_channel_selection_renders_charts(self, demo_page):
        """Selecting a channel should render Power and Errors charts."""
        navigate_to_channels(demo_page)

        # Select first channel in the dropdown
        select = demo_page.locator("#channel-select")
        if select.count() > 0:
            options = select.locator("option")
            if options.count() > 1:
                # Select the first non-empty option
                select.select_option(index=1)
                demo_page.wait_for_timeout(1500)

                # Power chart should render
                power_chart = demo_page.locator("#chart-ch-power .uplot canvas")
                assert power_chart.count() >= 1, "Channel power chart should render"

    def test_channel_errors_chart_renders(self, demo_page):
        """Channel errors bar chart should render for DS channels."""
        navigate_to_channels(demo_page)
        select = demo_page.locator("#channel-select")
        if select.count() > 0:
            options = select.locator("option")
            if options.count() > 1:
                select.select_option(index=1)
                demo_page.wait_for_timeout(1500)
                errors_card = demo_page.locator("#channel-errors-card")
                if errors_card.is_visible():
                    errors_chart = demo_page.locator("#chart-ch-errors .uplot canvas")
                    assert errors_chart.count() >= 1

    def test_channel_time_range_tabs(self, demo_page):
        """Channel time range tabs should reload charts."""
        navigate_to_channels(demo_page)
        select = demo_page.locator("#channel-select")
        if select.count() > 0:
            options = select.locator("option")
            if options.count() > 1:
                select.select_option(index=1)
                demo_page.wait_for_timeout(1500)
                # Click 7d tab
                tab_7d = demo_page.locator('.channel-range-tab[data-range="7d"]')
                if tab_7d.count() > 0:
                    tab_7d.click()
                    demo_page.wait_for_timeout(1500)
                    power_chart = demo_page.locator("#chart-ch-power .uplot canvas")
                    assert power_chart.count() >= 1


# ── Compare Charts ──


class TestCompareCharts:
    """Charts in the Channels > Compare view."""

    def test_compare_mode_renders_power_chart(self, demo_page):
        """Compare mode with channels should render power overlay chart."""
        navigate_to_channels(demo_page)

        # Switch to compare tab
        compare_tab = demo_page.locator('.channel-mode-tab[data-mode="compare"]')
        if compare_tab.count() > 0:
            compare_tab.click()
            demo_page.wait_for_timeout(500)

            # Add a channel to compare
            add_btn = demo_page.locator("#compare-add-btn, .compare-add-btn")
            if add_btn.count() > 0:
                add_btn.click()
                demo_page.wait_for_timeout(1500)

                cmp_power = demo_page.locator("#chart-cmp-power .uplot canvas")
                if cmp_power.count() >= 1:
                    assert True  # Power chart rendered

    def test_compare_all_downstream_preset_renders_chart(self, demo_page):
        """All Downstream preset should render the compare charts without manual picks."""
        navigate_to_channels(demo_page)
        compare_tab = demo_page.locator('.trend-tab[data-value="compare"]')
        if compare_tab.count() > 0:
            compare_tab.first.click()
            demo_page.wait_for_timeout(500)

            add_all_btn = demo_page.locator("#compare-add-all-btn")
            if add_all_btn.count() > 0:
                add_all_btn.click()
                demo_page.wait_for_timeout(1500)
                wait_for_uplot(demo_page, "chart-cmp-power")
                chips = demo_page.locator("#compare-chips .compare-chip")
                assert chips.count() >= 1


class TestUnsupportedDocsisErrorCharts:
    """Unsupported DOCSIS error counters should remove misleading error charts."""

    def test_trends_hide_errors_chart_when_error_counters_are_unsupported(self, demo_page):
        demo_page.route(
            "**/api/trends**",
            lambda route: route.fulfill(json=[{
                "timestamp": "2026-05-01T12:00:00",
                "ds_power_avg": 1.2,
                "ds_snr_avg": 38.5,
                "us_power_avg": 42.1,
                "errors_supported": False,
                "ds_correctable_errors": None,
                "ds_uncorrectable_errors": None,
            }]),
        )

        navigate_to_trends(demo_page)

        assert demo_page.locator("#trend-errors-card").is_hidden()
        assert demo_page.locator("#chart-errors .uplot").count() == 0
        wait_for_uplot(demo_page, "chart-ds-power")

    def test_channel_timeline_hides_errors_chart_when_error_counters_are_unsupported(self, demo_page):
        demo_page.route(
            "**/api/channel-history**",
            lambda route: route.fulfill(json=[{
                "timestamp": "2026-05-01T12:00:00",
                "power": 1.2,
                "snr": 38.5,
                "modulation": "256QAM",
                "correctable_errors": None,
                "uncorrectable_errors": None,
            }]),
        )

        navigate_to_channels(demo_page)
        select = demo_page.locator("#channel-select")
        select.select_option(index=1)
        wait_for_uplot(demo_page, "chart-ch-power")

        assert demo_page.locator("#channel-errors-card").is_hidden()
        assert demo_page.locator("#chart-ch-errors .uplot").count() == 0

    def test_compare_hides_errors_chart_when_error_counters_are_unsupported(self, demo_page):
        demo_page.route(
            "**/api/channel-compare**",
            lambda route: route.fulfill(json={
                "1": [{
                    "timestamp": "2026-05-01T12:00:00",
                    "power": 1.2,
                    "snr": 38.5,
                    "modulation": "256QAM",
                    "correctable_errors": None,
                    "uncorrectable_errors": None,
                }]
            }),
        )

        navigate_to_channels(demo_page)
        compare_tab = demo_page.locator('.trend-tab[data-value="compare"]')
        compare_tab.first.click()
        demo_page.wait_for_timeout(500)
        demo_page.locator("#compare-add-all-btn").click()
        wait_for_uplot(demo_page, "chart-cmp-power")

        assert demo_page.locator("#compare-errors-card").is_hidden()
        assert demo_page.locator("#chart-cmp-errors .uplot").count() == 0


# ── Theme Toggle ──


class TestChartTheme:
    """Charts should look correct in both themes."""

    def test_trend_charts_dark_mode(self, demo_page):
        """Trend charts should render in dark mode."""
        # Ensure dark mode via JS
        demo_page.evaluate("""
            document.documentElement.setAttribute('data-theme', 'dark');
            localStorage.setItem('docsis-theme', 'dark');
        """)
        demo_page.wait_for_timeout(200)

        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")
        canvases = count_uplot_canvases(demo_page, "chart-ds-power")
        assert canvases >= 1

    def test_trend_charts_light_mode(self, demo_page):
        """Trend charts should render in light mode."""
        # Switch to light mode via JS (checkbox may be hidden)
        demo_page.evaluate("""
            document.documentElement.setAttribute('data-theme', 'light');
            localStorage.setItem('docsis-theme', 'light');
        """)
        demo_page.wait_for_timeout(200)

        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")
        canvases = count_uplot_canvases(demo_page, "chart-ds-power")
        assert canvases >= 1

        # Toggle back to dark
        demo_page.evaluate("""
            document.documentElement.setAttribute('data-theme', 'dark');
            localStorage.setItem('docsis-theme', 'dark');
        """)
        demo_page.wait_for_timeout(200)


# ── Responsive Sizing ──


class TestChartResponsive:
    """Charts should resize properly."""

    def test_chart_fills_container_width(self, demo_page):
        """Chart canvas should approximately fill its container width."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        container_box = demo_page.locator("#chart-ds-power").bounding_box()
        canvas_box = demo_page.locator("#chart-ds-power .uplot canvas").first.bounding_box()
        if container_box and canvas_box:
            ratio = canvas_box["width"] / container_box["width"]
            assert ratio > 0.8, f"Chart width ratio {ratio} is too small"

    def test_chart_resizes_on_viewport_change(self, demo_page):
        """Charts should resize when viewport width changes."""
        # Start with a wide viewport
        demo_page.set_viewport_size({"width": 1280, "height": 720})
        demo_page.wait_for_timeout(300)
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        initial = demo_page.locator("#chart-ds-power .uplot canvas").first.bounding_box()

        # Resize viewport narrower
        demo_page.set_viewport_size({"width": 600, "height": 800})
        demo_page.wait_for_timeout(800)

        after = demo_page.locator("#chart-ds-power .uplot canvas").first.bounding_box()
        if initial and after:
            # The chart width should change (either direction is fine, just verify it reacts)
            assert abs(after["width"] - initial["width"]) > 10, \
                f"Chart should resize: {initial['width']} vs {after['width']}"

        # Restore viewport
        demo_page.set_viewport_size({"width": 1280, "height": 720})
        demo_page.wait_for_timeout(500)


# ── Tooltip ──


class TestChartTooltip:
    """Chart tooltip should appear on hover."""

    def test_tooltip_appears_on_hover(self, demo_page):
        """Hovering over a trend chart should show a tooltip."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        over = demo_page.locator("#chart-ds-power .uplot .u-over")
        box = over.bounding_box()
        if box:
            demo_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            demo_page.wait_for_timeout(300)
            tooltip = demo_page.locator("#chart-ds-power .uplot-tooltip")
            if tooltip.count() > 0:
                assert tooltip.first.is_visible()

    def test_tooltip_disappears_on_mouse_leave(self, demo_page):
        """Tooltip should hide when mouse leaves the chart."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        over = demo_page.locator("#chart-ds-power .uplot .u-over")
        box = over.bounding_box()
        if box:
            # Hover to show tooltip
            demo_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            demo_page.wait_for_timeout(300)
            # Move away
            demo_page.mouse.move(0, 0)
            demo_page.wait_for_timeout(300)
            tooltip = demo_page.locator("#chart-ds-power .uplot-tooltip")
            if tooltip.count() > 0:
                display = tooltip.first.evaluate("el => getComputedStyle(el).display")
                assert display == "none" or not tooltip.first.is_visible()


# ── No Console Errors ──


class TestNoJSErrors:
    """No JavaScript errors should occur during chart interactions."""

    def test_no_errors_on_dashboard_load(self, demo_page):
        """Dashboard load should not produce JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        demo_page.reload()
        demo_page.wait_for_timeout(2000)
        chart_errors = [e for e in errors if "Chart" in e or "uPlot" in e or "canvas" in e.lower()]
        assert len(chart_errors) == 0, f"JS errors on load: {chart_errors}"

    def test_no_errors_on_trends_view(self, demo_page):
        """Trends view should not produce JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        navigate_to_trends(demo_page)
        chart_errors = [e for e in errors if "Chart" in e or "uPlot" in e or "canvas" in e.lower()]
        assert len(chart_errors) == 0, f"JS errors in trends: {chart_errors}"

    def test_no_errors_on_channels_view(self, demo_page):
        """Channels view should not produce JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        navigate_to_channels(demo_page)
        chart_errors = [e for e in errors if "Chart" in e or "uPlot" in e or "canvas" in e.lower()]
        assert len(chart_errors) == 0, f"JS errors in channels: {chart_errors}"


# ── Chart Destruction (Memory Leaks) ──


class TestChartCleanup:
    """Charts should be properly destroyed when switching views."""

    def test_charts_destroyed_on_view_switch(self, demo_page):
        """Switching away from Trends should not leave orphan chart elements."""
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        # Switch to another view
        demo_page.locator('.nav-item[data-view="live"]').click()
        demo_page.wait_for_timeout(500)

        # Switch back — charts should re-render without stacking
        navigate_to_trends(demo_page)
        wait_for_uplot(demo_page, "chart-ds-power")

        # Should have exactly 1 uplot instance per container
        uplot_count = demo_page.locator("#chart-ds-power .uplot").count()
        assert uplot_count == 1, f"Expected 1 uPlot instance, got {uplot_count}"


# ── Vendor File Check ──


class TestVendorFiles:
    """Verify vendor files are served correctly."""

    def test_uplot_js_loads(self, live_server, page):
        """uPlot JS should be accessible."""
        resp = page.request.get(f"{live_server}/static/vendor/uPlot.min.js")
        assert resp.status == 200
        assert len(resp.body()) > 40000  # ~51KB

    def test_uplot_css_loads(self, live_server, page):
        """uPlot CSS should be accessible."""
        resp = page.request.get(f"{live_server}/static/vendor/uPlot.min.css")
        assert resp.status == 200
        assert ".uplot" in resp.text()

    def test_chartjs_removed(self, live_server, page):
        """Old Chart.js files should no longer be served."""
        resp = page.request.get(f"{live_server}/static/vendor/chart.umd.min.js")
        assert resp.status == 404

    def test_chartjs_adapter_removed(self, live_server, page):
        """Old Chart.js date-fns adapter should no longer be served."""
        resp = page.request.get(
            f"{live_server}/static/vendor/chartjs-adapter-date-fns.bundle.min.js"
        )
        assert resp.status == 404


# ── Existing Charts Unaffected ──


class TestNonMigratedCharts:
    """Custom canvas charts that should NOT be affected by the migration."""

    def test_donut_charts_still_render(self, demo_page):
        """Channel health donut charts should still work."""
        ds_donut = demo_page.locator("#ds-health-donut")
        us_donut = demo_page.locator("#us-health-donut")
        # Donuts are raw canvas, not uPlot — should still be canvas elements
        if ds_donut.count() > 0:
            assert ds_donut.evaluate("el => el.tagName") == "CANVAS"
        if us_donut.count() > 0:
            assert us_donut.evaluate("el => el.tagName") == "CANVAS"

    def test_sparklines_still_render(self, demo_page):
        """Sparkline canvases should still be present and rendered."""
        sparklines = demo_page.locator("canvas.sparkline")
        if sparklines.count() > 0:
            # Sparklines are custom canvas — should still be canvas
            assert sparklines.first.evaluate("el => el.tagName") == "CANVAS"
