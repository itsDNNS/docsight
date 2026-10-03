"""E2E tests for the events view."""

import pytest
from tests.e2e.support.navigation import open_view


class TestEventsView:
    """Events view navigation and content."""

    def test_switch_to_events_view(self, demo_page):
        open_view(demo_page, "events")
        events = demo_page.locator("#view-events")
        assert events.is_visible()

    def test_events_view_hides_live(self, demo_page):
        open_view(demo_page, "events")
        live = demo_page.locator("#view-live")
        assert not live.is_visible()

    def test_events_nav_marked_active(self, demo_page):
        open_view(demo_page, "events")
        nav = demo_page.locator('.nav-item[data-view="events"]')
        assert "active" in nav.get_attribute("class")

    def test_events_api_returns_data(self, live_server, page):
        resp = page.request.get(f"{live_server}/api/events")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, (list, dict))
