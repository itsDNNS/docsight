"""E2E tests for the channel status track in case detail and correlation."""

import re

from playwright.sync_api import expect
from tests.e2e.support.navigation import open_view


def _incident(page, live_server, status):
    data = page.request.get(f"{live_server}/api/incidents").json()
    incidents = data if isinstance(data, list) else data.get("incidents", [])
    return next(inc for inc in incidents if (inc["status"] == "open") == (status == "open") and inc.get("start_date"))


def _open_case(page, incident_id):
    open_view(page, "journal")
    page.evaluate("id => openIncidentTimeline(id)", incident_id)
    card = page.locator("#incident-timeline-status")
    # Long cases load a few months of snapshots; allow for a slow CI machine.
    expect(card).to_be_visible(timeout=15000)
    expect(card.locator(".cs-window")).to_be_visible(timeout=15000)
    return card


class TestCaseStatusTrack:
    def test_closed_case_shows_its_window_and_the_state_at_its_end(self, demo_page, live_server):
        incident = _incident(demo_page, live_server, "resolved")
        card = _open_case(demo_page, incident["id"])

        expect(card.locator(".cs-direction")).to_have_count(2)
        expect(card.locator(".cs-cell.cs-now")).to_have_count(0)
        expect(card.locator(".cs-at-end").first).to_have_text("At the end of the period")
        last_tick = card.locator(".cs-axis-ticks > span").last
        expect(last_tick).not_to_have_text("now")

    def test_open_case_runs_until_now(self, demo_page, live_server):
        incident = _incident(demo_page, live_server, "open")
        card = _open_case(demo_page, incident["id"])

        expect(card.locator(".cs-axis-ticks > span").last).to_have_text("now")
        expect(card.locator(".cs-at-end")).to_have_count(0)

    def test_case_row_opens_the_channel_charts_reaching_back_to_the_case_start(self, demo_page, live_server):
        incident = _incident(demo_page, live_server, "resolved")
        card = _open_case(demo_page, incident["id"])
        row = card.locator(".cs-rows > .cs-row:not(.cs-aggregate)").first
        if row.count() == 0:
            card.locator(".cs-aggregate").first.click()
            row = card.locator(".cs-others .cs-row").first
        direction, channel = row.get_attribute("data-direction"), row.get_attribute("data-channel-id")

        row.click()

        expect(demo_page.locator("#channel-panel-timeline")).to_be_visible()
        expect(demo_page.locator("#channel-select")).to_have_value(f"{direction}-{channel}")
        hash_value = demo_page.evaluate("location.hash")
        assert re.search(r"range=(7d|30d|90d)$", hash_value), hash_value


class TestCorrelationStatusTrack:
    def test_track_follows_the_correlation_range_and_opens_charts(self, demo_page):
        open_view(demo_page, "correlation")
        section = demo_page.locator("#correlation-status")
        expect(section).to_be_visible()
        expect(section.locator(".cs-window")).to_have_text("One cell = 30 min")
        expect(section.locator(".cs-row").first.locator(".cs-cell")).to_have_count(48)

        demo_page.locator('#correlation-tabs .segmented-option[data-value="7d"]').click()
        expect(section.locator(".cs-window")).to_have_text("One cell = 3.5 h")

        aggregate = section.locator(".cs-aggregate").first
        aggregate.click()
        row = section.locator("#" + aggregate.get_attribute("aria-controls") + " .cs-row").first
        direction, channel = row.get_attribute("data-direction"), row.get_attribute("data-channel-id")
        row.click()

        expect(demo_page.locator("#channel-select")).to_have_value(f"{direction}-{channel}")
        expect(demo_page.locator('#channel-time-tabs .segmented-option.active')).to_have_attribute("data-value", "7d")
