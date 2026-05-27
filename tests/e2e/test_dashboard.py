"""E2E tests for the main dashboard page."""

import re

import pytest


class TestDashboardLoad:
    """Basic page load and structure."""

    def test_page_title(self, demo_page):
        assert demo_page.title() == "DOCSight"

    def test_has_sidebar(self, demo_page):
        sidebar = demo_page.locator("nav.sidebar")
        assert sidebar.is_visible()

    def test_sidebar_logo_text(self, demo_page):
        title = demo_page.locator(".sidebar-title")
        assert title.text_content().strip() == "DOCSight"

    def test_live_view_active_by_default(self, demo_page):
        live_nav = demo_page.locator('.nav-item[data-view="live"]')
        assert "active" in live_nav.get_attribute("class")


class TestNavigation:
    """Sidebar nav switching."""

    def test_switch_to_events(self, demo_page):
        demo_page.locator('.nav-item[data-view="events"]').click()
        events_section = demo_page.locator("#view-events")
        assert events_section.is_visible()

    def test_switch_to_trends(self, demo_page):
        demo_page.locator('.nav-item[data-view="trends"]').click()
        trends_section = demo_page.locator("#view-trends")
        assert trends_section.is_visible()

    def test_switch_to_channels(self, demo_page):
        demo_page.locator('.nav-item[data-view="channels"]').click()
        channels_section = demo_page.locator("#view-channels")
        assert channels_section.is_visible()

    def test_switch_back_to_live(self, demo_page):
        demo_page.locator('.nav-item[data-view="events"]').click()
        demo_page.locator('.nav-item[data-view="live"]').click()
        live_section = demo_page.locator("#view-dashboard")
        assert live_section.is_visible()


class TestDashboardSections:
    """Dashboard content sections in demo mode."""

    def test_demo_badge_visible(self, demo_page):
        badge = demo_page.locator(".badge-muted")
        assert badge.is_visible()

    def test_health_status_shown(self, demo_page):
        hero = demo_page.locator(".hero-title, .status-dot")
        assert hero.first.is_visible()

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

    def test_disabled_connection_monitor_card_shows_no_data_state(self, demo_page):
        status = demo_page.locator("#cm-card-status")
        details = demo_page.locator("#cm-card-details")
        status.wait_for(state="visible")
        demo_page.wait_for_function("document.querySelector('#cm-card-status').textContent.trim() === '—'")
        assert details.text_content().strip() == ""

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
