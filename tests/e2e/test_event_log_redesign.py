"""Regression coverage for the event log feed-only redesign."""

from playwright.sync_api import expect
import re

MOBILE_VIEWPORT = {"width": 393, "height": 852}
DESKTOP_VIEWPORT = {"width": 1440, "height": 1000}
MAX_HORIZONTAL_OVERFLOW = 1
MIN_TOUCH_TARGET = 44


def _open_events(page, viewport):
    page.set_viewport_size(viewport)
    base_url = page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    page.goto(f"{base_url}/?lang=de#events", wait_until="networkidle")
    page.wait_for_selector("#view-events.active", state="visible")
    page.wait_for_selector("#events-feed-card", state="visible")
    page.wait_for_selector("#events-feed .event-feed-item", state="visible")


def _active_view_geometry(page):
    return page.evaluate(
        """
        () => {
            const activeView = document.querySelector('#view-events.active');
            const feed = document.querySelector('#events-feed');
            const firstCard = document.querySelector('#events-feed .event-feed-item');
            const message = document.querySelector('#events-feed .event-feed-message');
            const action = document.querySelector('#events-feed .event-feed-action .btn-ack');
            const table = document.querySelector('#events-table');
            const rect = (node) => {
                if (!node) return null;
                const box = node.getBoundingClientRect();
                return {left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height};
            };
            return {
                viewportWidth: window.innerWidth,
                documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
                activeViewOverflow: activeView ? activeView.scrollWidth - activeView.clientWidth : 0,
                feedDisplay: feed ? getComputedStyle(feed).display : null,
                hasTable: Boolean(table),
                firstCard: rect(firstCard),
                message: rect(message),
                action: rect(action),
            };
        }
        """
    )


def test_mobile_event_log_uses_feed_cards_without_table_mode(demo_page):
    """Mobile should render a scanable event feed with no alternate table mode."""
    page = demo_page
    _open_events(page, MOBILE_VIEWPORT)

    feed_items = page.locator("#events-feed .event-feed-item")
    expect(feed_items).to_have_count(50)
    expect(page.locator("#events-table")).to_have_count(0)
    expect(page.locator("#events-view-mode-table")).to_have_count(0)
    expect(page.locator("#events-view-mode-feed")).to_have_count(0)
    expect(page.locator("#events-export-csv")).to_be_visible()
    expect(feed_items.first.locator(".event-feed-title")).to_be_visible()
    expect(feed_items.first.locator(".event-feed-meta")).to_have_count(0)
    expect(feed_items.first.locator(".event-feed-message")).to_be_visible()

    ack_button = feed_items.first.locator(".event-feed-action .btn-ack")
    if ack_button.count() > 0:
        expect(ack_button).to_contain_text("Bestätigen")

    geometry = _active_view_geometry(page)
    assert geometry["documentOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["activeViewOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["feedDisplay"] != "none"
    assert geometry["hasTable"] is False
    assert geometry["firstCard"]["left"] >= 0
    assert geometry["firstCard"]["right"] <= geometry["viewportWidth"] + MAX_HORIZONTAL_OVERFLOW
    assert geometry["message"]["width"] >= 240
    if geometry["action"]:
        assert geometry["action"]["width"] >= MIN_TOUCH_TARGET
        assert geometry["action"]["height"] >= MIN_TOUCH_TARGET


def test_desktop_event_log_is_feed_only_with_export_and_acknowledge(demo_page):
    """Desktop should keep the feed, expose export, and not render table mode."""
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)

    expect(page.locator("#events-feed .event-feed-item").first).to_be_visible()
    expect(page.locator("#events-table")).to_have_count(0)
    expect(page.locator("#events-view-mode-table")).to_have_count(0)
    expect(page.locator("#events-view-mode-feed")).to_have_count(0)
    export = page.locator("#events-export-csv")
    expect(export).to_be_visible()
    expect(export).to_have_attribute("href", re.compile(r"/api/events/export\.csv\?.*exclude_operational=true"))

    first_card = page.locator("#events-feed .event-feed-item").first
    expect(first_card.locator(".event-feed-title")).to_be_visible()
    expect(first_card.locator(".event-feed-meta")).to_have_count(0)
    expect(first_card.locator(".event-feed-message")).to_be_visible()

    ack_button = first_card.locator(".event-feed-action .btn-ack")
    if ack_button.count() > 0:
        ack_button.click()
        expect(page.locator("#events-feed .event-feed-item").first).to_be_visible()


def test_event_export_link_tracks_active_filters(demo_page):
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)

    page.locator("button[data-severity='warning']").click()
    expect(page.locator("#events-feed .event-feed-item").first).to_be_visible()
    expect(page.locator("#events-export-csv")).to_have_attribute(
        "href",
        re.compile(r"/api/events/export\.csv\?.*severity=warning.*exclude_operational=true"),
    )

    page.locator("#device-filter-pill").click()
    expect(page.locator("#events-feed .event-feed-item").first).to_be_visible()
    expect(page.locator("#events-export-csv")).to_have_attribute(
        "href",
        re.compile(r"/api/events/export\.csv\?.*(event_prefix=device_.*exclude_operational=true|exclude_operational=true.*event_prefix=device_)"),
    )


def test_event_export_stays_available_for_empty_filtered_feed(demo_page):
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)
    page.route(
        re.compile(r".*/api/events\?.*severity=critical.*"),
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"events": [], "unacknowledged_count": 0}',
        ),
    )

    page.locator("button[data-severity='critical']").click()

    expect(page.locator("#events-empty")).to_be_visible()
    expect(page.locator("#events-export-csv")).to_be_visible()
    expect(page.locator("#events-export-csv")).to_have_attribute(
        "href",
        re.compile(r"/api/events/export\.csv\?.*severity=critical.*exclude_operational=true"),
    )
