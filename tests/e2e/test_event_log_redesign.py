"""Regression coverage for the event log feed/table redesign."""

from playwright.sync_api import expect

MOBILE_VIEWPORT = {"width": 393, "height": 852}
DESKTOP_VIEWPORT = {"width": 1440, "height": 1000}
MAX_HORIZONTAL_OVERFLOW = 1
MIN_TOUCH_TARGET = 44


def _open_events(page, viewport):
    page.set_viewport_size(viewport)
    base_url = page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    page.goto(f"{base_url}/?lang=de#events", wait_until="networkidle")
    page.wait_for_selector("#view-events.active", state="visible")
    page.wait_for_selector("#events-table-card", state="visible")
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
                tableDisplay: table ? getComputedStyle(table).display : null,
                firstCard: rect(firstCard),
                message: rect(message),
                action: rect(action),
            };
        }
        """
    )


def test_mobile_event_log_uses_feed_cards_instead_of_squeezed_table(demo_page):
    """Mobile should render a scanable event feed, not a compressed desktop table."""
    page = demo_page
    _open_events(page, MOBILE_VIEWPORT)

    feed_items = page.locator("#events-feed .event-feed-item")
    expect(feed_items).to_have_count(50)
    expect(page.locator("#events-table")).to_be_hidden()
    expect(feed_items.first.locator(".event-feed-title")).to_be_visible()
    expect(feed_items.first.locator(".event-feed-meta")).to_be_visible()
    expect(feed_items.first.locator(".event-feed-message")).to_be_visible()

    ack_button = feed_items.first.locator(".event-feed-action .btn-ack")
    if ack_button.count() > 0:
        expect(ack_button).to_contain_text("Bestätigen")

    geometry = _active_view_geometry(page)
    assert geometry["documentOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["activeViewOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["feedDisplay"] != "none"
    assert geometry["tableDisplay"] == "none"
    assert geometry["firstCard"]["left"] >= 0
    assert geometry["firstCard"]["right"] <= geometry["viewportWidth"] + MAX_HORIZONTAL_OVERFLOW
    assert geometry["message"]["width"] >= 240
    if geometry["action"]:
        assert geometry["action"]["width"] >= MIN_TOUCH_TARGET
        assert geometry["action"]["height"] >= MIN_TOUCH_TARGET


def test_desktop_event_log_defaults_to_feed_with_optional_table_mode(demo_page):
    """Desktop should favor a scanable feed while keeping table mode available."""
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)

    expect(page.locator("#events-feed .event-feed-item").first).to_be_visible()
    expect(page.locator("#events-table")).to_be_hidden()
    expect(page.locator("#events-view-mode-feed")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#events-view-mode-table")).to_have_attribute("aria-pressed", "false")

    first_card = page.locator("#events-feed .event-feed-item").first
    expect(first_card.locator(".event-feed-title")).to_be_visible()
    expect(first_card.locator(".event-feed-meta")).to_be_visible()
    expect(first_card.locator(".event-feed-message")).to_be_visible()

    page.locator("#events-view-mode-table").click()
    expect(page.locator("#events-view-mode-table")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#events-feed")).to_be_hidden()
    expect(page.locator("#events-table")).to_be_visible()
    expect(page.locator("#events-table tbody tr").first).to_be_visible()

    page.locator("#events-view-mode-feed").click()
    expect(page.locator("#events-feed .event-feed-item").first).to_be_visible()
    expect(page.locator("#events-table")).to_be_hidden()
