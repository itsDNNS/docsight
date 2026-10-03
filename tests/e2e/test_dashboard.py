"""E2E tests for the main dashboard page."""

import re

import pytest
from playwright.sync_api import expect
from tests.e2e.support.navigation import open_view


class TestDashboardLoad:
    """Basic page load and structure."""

    def test_page_title(self, demo_page):
        assert demo_page.title() == "DOCSight"

    def test_has_top_navigation(self, demo_page):
        assert demo_page.locator("#topnav").is_visible()
        assert demo_page.locator("#main-nav").is_visible()

    def test_brand_text(self, demo_page):
        title = demo_page.locator(".topnav-brand-name")
        assert title.text_content().strip() == "DOCSight"

    def test_live_view_active_by_default(self, demo_page):
        live_nav = demo_page.locator('.nav-item[data-view="live"]')
        assert "active" in live_nav.get_attribute("class")


class TestNavigation:
    """Top navigation switching."""

    def test_group_panel_opens_with_arrow_down_and_cycles_with_arrows(self, demo_page):
        toggle = demo_page.locator("#nav-toggle-signal")
        toggle.focus()
        toggle.press("ArrowDown")
        expect(demo_page.locator("#nav-panel-signal")).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        focused = lambda: demo_page.evaluate("document.activeElement.getAttribute('data-view')")
        assert focused() == "trends"
        demo_page.keyboard.press("ArrowDown")
        assert focused() == "channels"
        demo_page.keyboard.press("ArrowUp")
        demo_page.keyboard.press("ArrowUp")
        last = demo_page.locator("#nav-panel-signal .nav-item[data-view]").last.get_attribute("data-view")
        assert focused() == last
        demo_page.keyboard.press("Escape")
        expect(demo_page.locator("#nav-panel-signal")).to_be_hidden()
        assert demo_page.evaluate("document.activeElement.id") == "nav-toggle-signal"

    def test_only_one_group_is_open_and_outside_click_closes_it(self, demo_page):
        demo_page.locator("#nav-toggle-signal").click()
        demo_page.locator("#nav-toggle-cases").click()
        expect(demo_page.locator("#nav-panel-signal")).to_be_hidden()
        expect(demo_page.locator("#nav-panel-cases")).to_be_visible()
        demo_page.mouse.click(700, 600)
        expect(demo_page.locator("#nav-panel-cases")).to_be_hidden()
        expect(demo_page.locator("#nav-toggle-cases")).to_have_attribute("aria-expanded", "false")

    def test_deep_link_marks_view_and_its_group_active(self, demo_page):
        base = demo_page.url.split("#")[0]
        demo_page.goto(base + "#channels")
        demo_page.wait_for_selector("#view-channels.active")
        expect(demo_page.locator("#nav-toggle-signal")).to_have_class(re.compile(r"\bactive\b"))
        expect(demo_page.locator('#topnav .nav-item[data-view="channels"]')).to_have_attribute("aria-current", "page")
        expect(demo_page.locator('#topnav .nav-item[data-view="live"]')).not_to_have_attribute("aria-current", "page")

    def test_more_menu_offers_settings_glossary_and_dark_mode(self, demo_page):
        demo_page.locator("#nav-toggle-more").click()
        panel = demo_page.locator("#nav-panel-more")
        expect(panel.locator('a[href$="/settings"]')).to_be_visible()
        expect(panel.locator('[data-view="glossary"]')).to_be_visible()
        expect(panel.locator("#theme-toggle-sidebar")).to_be_attached()

    def test_view_changes_update_the_title_and_move_focus_to_the_heading(self, demo_page):
        expect(demo_page).to_have_title("DOCSight")
        expect(demo_page.locator("h1")).to_have_count(1)
        open_view(demo_page, "trends")
        expect(demo_page).to_have_title("Signal Trends · DOCSight")
        expect(demo_page.locator("#view-trends .view-page-title")).to_be_focused()

    def test_skip_link_is_the_first_tab_stop_and_focuses_the_active_view(self, demo_page):
        demo_page.keyboard.press("Tab")
        expect(demo_page.locator("#skip-link")).to_be_focused()
        demo_page.keyboard.press("Enter")
        expect(demo_page.locator("#view-dashboard")).to_be_focused()
        assert demo_page.evaluate("location.hash") == ""

    def test_initial_deep_link_sets_the_title_without_moving_focus(self, page, live_server):
        page.goto(f"{live_server}/#correlation")
        page.wait_for_load_state("networkidle")
        expect(page).to_have_title("Correlation · DOCSight")
        assert page.evaluate("document.activeElement === document.body")

    def test_switch_to_events(self, demo_page):
        open_view(demo_page, "events")
        events_section = demo_page.locator("#view-events")
        assert events_section.is_visible()

    def test_switch_to_trends(self, demo_page):
        open_view(demo_page, "trends")
        trends_section = demo_page.locator("#view-trends")
        assert trends_section.is_visible()

    def test_switch_to_channels(self, demo_page):
        open_view(demo_page, "channels")
        channels_section = demo_page.locator("#view-channels")
        assert channels_section.is_visible()

    def test_switch_back_to_live(self, demo_page):
        open_view(demo_page, "events")
        open_view(demo_page, "live")
        live_section = demo_page.locator("#view-dashboard")
        assert live_section.is_visible()

    def test_speed_kpi_card_opens_speedtest_view_and_uses_rabbit_icon(self, demo_page):
        speed_card = demo_page.locator("#metric-speed-card")
        assert speed_card.is_visible()
        assert speed_card.get_attribute("role") == "button"
        assert speed_card.get_attribute("tabindex") == "0"
        assert speed_card.locator('svg.lucide-rabbit').is_visible()

        speed_card.click()

        assert demo_page.locator("#view-speedtest").is_visible()
        assert "active" in demo_page.locator('.nav-item[data-view="speedtest"]').get_attribute("class")


class TestDashboardSections:
    """Dashboard content sections in demo mode."""

    def test_demo_badge_visible(self, demo_page):
        badge = demo_page.get_by_text("DEMO", exact=True)
        assert badge.is_visible()

    def test_health_status_shown(self, demo_page):
        word = demo_page.locator(".line-status-word")
        expect(word).to_be_visible()
        expect(word).to_contain_text(re.compile(r"Good|Tolerated|Marginal|Critical"))

    def test_downstream_section(self, demo_page):
        ds = demo_page.locator(".dashboard-channel-panel .channel-title", has_text="Downstream")
        assert ds.is_visible()

    def test_upstream_section(self, demo_page):
        us = demo_page.locator(".dashboard-channel-panel .channel-title", has_text="Upstream")
        assert us.is_visible()

    def test_signal_family_cards_show_ofdma_and_stack_modulation_below_status(self, demo_page):
        ofdma_card = demo_page.locator("#metric-us-ofdma-card")
        assert ofdma_card.is_visible()
        assert "US POWER (OFDMA)" in ofdma_card.text_content()
        assert ofdma_card.locator(".metric-status-row .metric-sub-label").text_content() == "Family status"

        geometry = demo_page.evaluate(
            """
            () => {
                const card = document.querySelector('#metric-ds-sc-qam-power-card');
                if (!card) throw new Error('DS SC-QAM power card not found');
                const status = card.querySelector('.metric-status-row');
                const modulation = card.querySelector('.metric-modulation-row');
                if (!status || !modulation) throw new Error('status or modulation row not found');
                const statusRect = status.getBoundingClientRect();
                const modulationRect = modulation.getBoundingClientRect();
                return {
                    statusBottom: statusRect.bottom,
                    modulationTop: modulationRect.top,
                    modulationWidth: modulationRect.width,
                    cardWidth: card.getBoundingClientRect().width,
                };
            }
            """
        )
        assert geometry["modulationTop"] >= geometry["statusBottom"] - 1
        assert geometry["modulationWidth"] >= geometry["cardWidth"] * 0.8

    def test_metric_range_bars_align_on_wide_home_dashboard(self, demo_page):
        demo_page.set_viewport_size({"width": 1280, "height": 720})
        errors_card = demo_page.locator("#metric-errors-card")
        us_scqam_card = demo_page.locator("#metric-us-sc-qam-card")
        assert errors_card.is_visible()
        assert us_scqam_card.is_visible()

        geometry = demo_page.evaluate(
            """
            () => {
                const errorsTrack = document.querySelector('#metric-errors-card .metric-range-track');
                const usTrack = document.querySelector('#metric-us-sc-qam-card .metric-range-track');
                if (!errorsTrack || !usTrack) throw new Error('range tracks not found');
                const errorsRect = errorsTrack.getBoundingClientRect();
                const usRect = usTrack.getBoundingClientRect();
                return { errorsTop: errorsRect.top, usTop: usRect.top };
            }
            """
        )
        assert abs(geometry["errorsTop"] - geometry["usTop"]) <= 2

    def test_signal_family_average_hint_uses_single_line_on_wide_dashboard(self, demo_page):
        demo_page.set_viewport_size({"width": 1280, "height": 720})
        hint = demo_page.locator(".dashboard-section-context > span")
        assert hint.is_visible()

        geometry = hint.evaluate(
            """
            el => {
                const rect = el.getBoundingClientRect();
                const lineHeight = Number.parseFloat(window.getComputedStyle(el).lineHeight);
                return { height: rect.height, lineHeight };
            }
            """
        )
        assert geometry["height"] <= geometry["lineHeight"] * 1.5

    def test_long_device_meta_values_keep_icons_visible_when_truncated(self, demo_page):
        demo_page.set_viewport_size({"width": 768, "height": 900})
        cases = [
            ("lucide-router", "Vodafone Station (TG6442VF/TG3442DE) with intentionally long vendor model label"),
            ("lucide-package", "AR01.04.046.25_072922_7244.PC20.10-X1-GA-RDKB-INT intentionally long firmware label"),
        ]

        for viewport_width in (768, 390):
            demo_page.set_viewport_size({"width": viewport_width, "height": 900})
            for icon_class, long_value in cases:
                metrics = demo_page.evaluate(
                    """({ iconClass, longValue }) => {
                        const item = Array.from(document.querySelectorAll('.dashboard-view .insights-meta .hero-meta-item'))
                            .find((el) => el.querySelector('svg.' + iconClass));
                        if (!item) throw new Error(iconClass + ' meta item not found');

                        const icon = item.querySelector('svg.' + iconClass);
                        const label = item.querySelector('.hero-meta-label');
                        if (!label) throw new Error(iconClass + ' label not found');
                        label.textContent = longValue;
                        const popover = item.querySelector('.glossary-popover');
                        if (popover) popover.textContent = longValue;
                        item.setAttribute('title', longValue);
                        item.setAttribute('aria-label', longValue);

                        const itemRect = item.getBoundingClientRect();
                        const iconRect = icon.getBoundingClientRect();
                        return {
                            itemLeft: itemRect.left,
                            itemRight: itemRect.right,
                            itemWidth: itemRect.width,
                            textScrollWidth: label.scrollWidth,
                            textClientWidth: label.clientWidth,
                            iconLeft: iconRect.left,
                            iconRight: iconRect.right,
                            iconWidth: iconRect.width,
                        };
                    }""",
                    {"iconClass": icon_class, "longValue": long_value},
                )

                assert metrics["itemWidth"] > 44
                assert metrics["textScrollWidth"] > metrics["textClientWidth"]
                assert metrics["iconWidth"] > 0
                assert metrics["iconLeft"] >= metrics["itemLeft"]
                assert metrics["iconRight"] <= metrics["itemRight"]

    def test_device_meta_value_reveals_full_value_on_focus_and_click(self, demo_page):
        item = demo_page.locator(".dashboard-view .insights-meta .hero-meta-item", has=demo_page.locator("svg.lucide-router")).first
        assert item.is_visible()
        assert item.get_attribute("role") == "button"
        assert item.get_attribute("tabindex") == "0"
        assert item.get_attribute("aria-expanded") == "false"
        assert item.locator(".hero-meta-label").text_content().strip() == "Demo Router"
        assert "Demo Router" in item.locator(".glossary-popover").text_content()

        item.focus()
        overlay = demo_page.locator("body > #glossary-popover-overlay")
        assert overlay.is_visible()
        assert item.get_attribute("aria-expanded") == "true"
        assert "Demo Router" in overlay.text_content()

        demo_page.keyboard.press("Escape")
        assert not overlay.is_visible()
        assert item.get_attribute("aria-expanded") == "false"

        item.click()
        assert overlay.is_visible()
        assert item.get_attribute("aria-expanded") == "true"
        assert "Demo Router" in overlay.text_content()

    def test_device_meta_value_popover_stays_near_tapped_mobile_item(self, demo_page):
        demo_page.set_viewport_size({"width": 390, "height": 900})
        item = demo_page.locator(".dashboard-view .insights-meta .hero-meta-item", has=demo_page.locator("svg.lucide-router")).first
        item.click()

        overlay = demo_page.locator("body > #glossary-popover-overlay")
        assert overlay.is_visible()

        metrics = demo_page.evaluate(
            """() => {
                const item = Array.from(document.querySelectorAll('.dashboard-view .insights-meta .hero-meta-item'))
                    .find((el) => el.querySelector('svg.lucide-router'));
                const overlay = document.querySelector('body > #glossary-popover-overlay');
                if (!item || !overlay) throw new Error('meta item or overlay missing');
                const itemRect = item.getBoundingClientRect();
                const overlayRect = overlay.getBoundingClientRect();
                const viewportWidth = document.documentElement.clientWidth;
                return {
                    itemTop: itemRect.top,
                    itemBottom: itemRect.bottom,
                    overlayTop: overlayRect.top,
                    overlayBottom: overlayRect.bottom,
                    overlayLeft: overlayRect.left,
                    overlayRight: overlayRect.right,
                    viewportWidth,
                };
            }"""
        )

        below_gap = abs(metrics["overlayTop"] - metrics["itemBottom"])
        above_gap = abs(metrics["itemTop"] - metrics["overlayBottom"])
        assert min(below_gap, above_gap) <= 24
        assert metrics["overlayLeft"] >= 8
        assert metrics["overlayRight"] <= metrics["viewportWidth"] - 8

    def test_dashboard_refresh_control_is_keyboard_focusable(self, demo_page):
        refresh = demo_page.locator(".hero-refresh-button")
        assert refresh.first.is_visible()
        assert refresh.first.evaluate("el => el.tagName.toLowerCase() === 'button'")

    def test_connection_monitor_card_is_keyboard_accessible(self, demo_page):
        card = demo_page.locator("#connection-monitor-card")
        assert card.count() == 1
        assert card.get_attribute("role") == "button"
        assert card.get_attribute("tabindex") == "0"

    def test_enabled_connection_monitor_card_uses_standard_kpi_anatomy(self, demo_page):
        demo_page.route(
            "**/api/connection-monitor/summary",
            lambda route: route.fulfill(
                json={
                    "1": {
                        "label": "Cloudflare",
                        "host": "1.1.1.1",
                        "enabled": True,
                        "avg_latency_ms": 39.9,
                        "sample_count": 12,
                        "min_latency_ms": 37.2,
                        "max_latency_ms": 43.6,
                        "packet_loss_pct": 0,
                    }
                }
            ),
        )
        demo_page.reload(wait_until="networkidle")

        latency = demo_page.locator("#cm-card-latency")
        average = demo_page.locator("#cm-card-avg")
        badge = demo_page.locator("#cm-card-badge")
        expect(average).to_have_text("Avg · 1/1 OK")

        assert latency.text_content() == "39.9ms"
        assert latency.locator(":scope > .unit").count() == 1
        assert latency.locator(":scope > .unit").text_content() == "ms"
        assert "Avg" not in latency.text_content()
        assert average.text_content() == "Avg · 1/1 OK"
        assert badge.text_content() == "Good"

        structure = demo_page.evaluate(
            """
            () => {
                const latency = document.querySelector('#cm-card-latency');
                const average = document.querySelector('#cm-card-avg');
                const averageRow = average && average.closest('.metric-average-row');
                return {
                    primaryText: latency && latency.firstChild && latency.firstChild.nodeValue,
                    unitParentIsPrimary: latency && latency.querySelector(':scope > .unit')?.parentElement === latency,
                    averageParentIsSecondaryRow: averageRow?.contains(average) === true,
                    primaryContainsAverage: latency?.contains(average) === true,
                };
            }
            """
        )
        assert structure == {
            "primaryText": "39.9",
            "unitParentIsPrimary": True,
            "averageParentIsSecondaryRow": True,
            "primaryContainsAverage": False,
        }

    def test_speedtest_row_toggles_are_named_and_expose_their_state(self, demo_page):
        demo_page.evaluate("switchView('speedtest')")
        toggle = demo_page.locator("#speedtest-tbody .st-expand-btn").first
        expect(toggle).to_have_accessible_name("Show signal at this time")
        expect(toggle).to_have_attribute("aria-expanded", "false")
        unnamed = demo_page.evaluate(
            """() => [...document.querySelectorAll('#view-speedtest button')]
                .filter((b) => b.offsetParent && !b.innerText.trim() && !b.getAttribute('aria-label')).length"""
        )
        assert unnamed == 0
        toggle.focus()
        toggle.press("Enter")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(demo_page.locator("#" + toggle.get_attribute("aria-controls"))).to_be_visible()

    def test_demo_connection_monitor_card_shows_seeded_latency(self, demo_page):
        expect(demo_page.locator("#connection-monitor-card")).to_have_attribute(
            "data-cm-state", "active", timeout=15000
        )
        expect(demo_page.locator("#cm-card-latency")).to_contain_text("ms")
        expect(demo_page.locator("#cm-card-badge")).not_to_have_text("–")

    def test_disabled_connection_monitor_card_explains_state_and_opens_settings(self, demo_page):
        demo_page.route("**/api/connection-monitor/summary", lambda route: route.fulfill(json={}))
        demo_page.reload(wait_until="networkidle")

        card = demo_page.locator("#connection-monitor-card")
        expect(card).to_have_attribute("data-cm-state", "off")
        expect(demo_page.locator("#cm-card-badge")).to_have_text("Off")
        expect(demo_page.locator("#cm-card-avg")).to_have_text("Turn on in Settings")

        card.focus()
        card.press("Enter")
        demo_page.wait_for_url("**/settings#mod-docsight_connection_monitor")

    def test_docsis_groups_expose_expanded_state(self, demo_page):
        header = demo_page.locator(".docsis-group-header").first
        assert header.get_attribute("aria-expanded") == "false"
        assert header.get_attribute("aria-controls")
        header.press("Enter")
        assert header.get_attribute("aria-expanded") == "true"

    def test_settings_link_exists(self, demo_page):
        # Settings accessible via nav or bottom bar
        settings = demo_page.locator('[onclick*="settings"], a[href="/settings"]')
        assert settings.count() > 0


class TestHealthEndpoint:
    """The /health endpoint is always public."""

    def test_health_returns_ok(self, live_server, page):
        page.goto(f"{live_server}/health")
        content = page.text_content("body")
        assert '"status": "ok"' in content or '"status":"ok"' in content


class TestSignalRefresh:
    def test_refresh_keeps_real_hero_and_cached_sparse_sparks_then_updates(self, page, live_server):
        from tests.e2e.support.signal_trends import start, painted, rows, wait_count, click_refresh, spark_pixels, toggle_theme
        requests = start(page, live_server)
        painted(page)
        page.wait_for_load_state('networkidle')
        page.evaluate("window.savedHero = document.querySelector('#hero-trend-chart'); window.savedCanvas = savedHero.querySelector('canvas'); window.savedBitmap = savedCanvas.toDataURL();")
        held = []
        page.route('**/api/trends/signal?*', lambda route: held.append(route))
        click_refresh(page)
        wait_count(page, held, 1)
        assert page.evaluate("savedHero === document.querySelector('#hero-trend-chart') && savedCanvas.isConnected && savedCanvas.toDataURL() === savedBitmap")
        assert spark_pixels(page, '#spark-speed')
        assert spark_pixels(page, '#spark-errors')
        toggle_theme(page)
        assert len(held) == 1
        held[0].fulfill(json=rows(8))
        painted(page, 8)
        wait_count(page, requests['legacy'], 2)
        assert page.evaluate('!savedCanvas.isConnected')
        assert page.locator('body > .uplot-tooltip').count() == 1

    def test_stale_signal_and_theme_during_fetch_cannot_overwrite_newer_data(self, page, live_server):
        from tests.e2e.support.signal_trends import start, painted, rows, wait_count, click_refresh, toggle_theme
        held = []
        requests = start(page, live_server, signal=lambda route: held.append(route))
        wait_count(page, held, 1)
        toggle_theme(page)
        assert len(held) == 1
        click_refresh(page)
        wait_count(page, held, 2)
        toggle_theme(page)
        held[1].fulfill(json=rows(20))
        painted(page, 20)
        held[0].fulfill(json=rows(1))
        page.wait_for_load_state('networkidle')
        assert page.evaluate('dashboardTrendsProbe.charts.at(-1).data[1][0]') == 20
        assert len(held) == 2
        assert len(requests['legacy']) == 1

    def test_html_refresh_race_uses_latest_response(self, page, live_server):
        from tests.e2e.support.signal_trends import start, painted, wait_count, click_refresh, wait_js
        start(page, live_server)
        painted(page)
        page.wait_for_load_state('networkidle')
        html = page.request.get(live_server).text()
        held = []
        page.route(live_server + '/', lambda route: held.append(route))
        page.clock.install()
        click_refresh(page)
        wait_count(page, held, 1)
        page.clock.run_for(10001)  # Existing user refresh cooldown.
        click_refresh(page)
        wait_count(page, held, 2)
        newer = html.replace('24h signal trend', 'Newest trend marker')
        held[1].fulfill(content_type='text/html', body=newer)
        wait_js(page, "() => document.querySelector('#view-dashboard').textContent.includes('Newest trend marker')")
        held[0].fulfill(content_type='text/html', body=html.replace('24h signal trend', 'Stale trend marker'))
        page.wait_for_timeout(100)
        assert 'Newest trend marker' in page.locator('#view-dashboard').text_content()
        assert 'Stale trend marker' not in page.locator('#view-dashboard').text_content()

    def test_refresh_failure_retains_chart_and_modules_still_update(self, page, live_server):
        from tests.e2e.support.signal_trends import start, painted, rows, wait_count, click_refresh, spark_pixels
        requests = start(page, live_server)
        painted(page)
        page.wait_for_load_state('networkidle')
        page.evaluate("window.savedCanvas = document.querySelector('#hero-trend-chart canvas')")
        page.route('**/api/trends/signal?*', lambda route: route.fulfill(status=503, json={}))
        click_refresh(page)
        wait_count(page, requests['legacy'], 2)
        page.wait_for_load_state('networkidle')
        assert page.evaluate('savedCanvas.isConnected')
        assert spark_pixels(page, '#spark-errors')
        assert spark_pixels(page, '#spark-speed')
