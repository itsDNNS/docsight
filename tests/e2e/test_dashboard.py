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
        live_nav = demo_page.locator('a.nav-item[data-view="live"]')
        assert "active" in live_nav.get_attribute("class")


class TestNavigation:
    """Sidebar nav switching."""

    def test_switch_to_events(self, demo_page):
        demo_page.locator('a.nav-item[data-view="events"]').click()
        events_section = demo_page.locator("#view-events")
        assert events_section.is_visible()

    def test_switch_to_trends(self, demo_page):
        demo_page.locator('a.nav-item[data-view="trends"]').click()
        trends_section = demo_page.locator("#view-trends")
        assert trends_section.is_visible()

    def test_switch_to_channels(self, demo_page):
        demo_page.locator('a.nav-item[data-view="channels"]').click()
        channels_section = demo_page.locator("#view-channels")
        assert channels_section.is_visible()

    def test_switch_back_to_live(self, demo_page):
        demo_page.locator('a.nav-item[data-view="events"]').click()
        demo_page.locator('a.nav-item[data-view="live"]').click()
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
        ds = demo_page.locator(".ring-title", has_text="Downstream")
        assert ds.is_visible()

    def test_upstream_section(self, demo_page):
        us = demo_page.locator(".ring-title", has_text="Upstream")
        assert us.is_visible()

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
