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


DESKTOP = {"width": 1440, "height": 1000}
MOBILE = {"width": 393, "height": 852}
UNREACHABLE = "5 Zeitüberschreitungen in Folge"
RECOVERED = "wieder erreichbar nach 5 Zeitüberschreitungen"


class TestConnectionMonitorEventTargets:
    """#1106: events from the real rules name their target as it was then."""

    def _open(self, page, server, viewport):
        page.set_viewport_size(viewport)
        page.goto(f"{server}/?lang=de#events", wait_until="networkidle")
        page.wait_for_selector("#events-feed .ev-row", state="visible")
        for toggle in page.locator("#events-feed .ev-group > .ev-main").all():
            toggle.click()
        events = page.request.get(f"{server}/api/events?limit=100").json()["events"]
        return {
            (e["event_type"], e["details"]["target_id"]):
                page.locator(f'#events-feed [data-event-id="{e["id"]}"] .ev-msg').inner_text()
            for e in events
        }

    def test_messages_name_the_target_snapshot(self, page, cm_events_server):
        messages = self._open(page, cm_events_server, DESKTOP)

        # Stable keys: after deleting the first target, the live ones are 2 and 3.
        # Afterwards Second (2) is deleted and Third (3) renamed; both keep the
        # identity their events were recorded with.
        assert messages[("cm_target_unreachable", 2)] == f"Second (192.0.2.2): {UNREACHABLE}"
        assert messages[("cm_target_unreachable", 3)] == f"Third (192.0.2.3): {UNREACHABLE}"
        assert messages[("cm_target_recovered", 3)] == f"Third (192.0.2.3): {RECOVERED}"
        assert messages[("cm_packet_loss_warning", 3)] == "Third (192.0.2.3): 100 % Paketverlust über 60 s"
        # Events from before #1106 only know the ID; nothing is guessed about the target.
        assert messages[("cm_target_unreachable", 1)] == f"Ziel-ID 1: {UNREACHABLE}"
        assert messages[("cm_target_recovered", 1)] == f"Ziel-ID 1: {RECOVERED}"
        assert messages[("cm_packet_loss_warning", 1)] == "Ziel-ID 1: 4,5 % Paketverlust über 60 s"

        feed = page.locator("#events-feed").inner_text()
        for absent in ("Renamed", "198.51.100.3", "cm_target", "Target"):
            assert absent not in feed
        types = page.locator("#events-feed .ev-type").all_inner_texts()
        assert {"Ziel nicht erreichbar", "Ziel wieder erreichbar", "Paketverlust-Warnung"} <= set(types)

    def test_target_labels_are_shown_as_text(self, page, cm_events_server):
        from tests.e2e.support.connection_monitor import XSS_LABEL

        messages = self._open(page, cm_events_server, DESKTOP)

        assert messages[("cm_target_unreachable", 4)] == f"{XSS_LABEL} (lab.example): {UNREACHABLE}"
        assert page.locator("#events-feed img").count() == 0
        assert page.evaluate("window.__docsightXss") is None

    def test_phone_layout_keeps_named_targets_inside_the_view(self, page, cm_events_server):
        messages = self._open(page, cm_events_server, MOBILE)

        assert messages[("cm_target_unreachable", 3)] == f"Third (192.0.2.3): {UNREACHABLE}"
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1
