"""Event log: compact day timeline, collapsed repeats, multi-acknowledge and the attention badge."""

import json
import re

from playwright.sync_api import expect

MOBILE_VIEWPORT = {"width": 393, "height": 852}
DESKTOP_VIEWPORT = {"width": 1440, "height": 1000}
MAX_HORIZONTAL_OVERFLOW = 1
MIN_TOUCH_TARGET = 44
# The former card feed needed about 134 px (desktop) and 193 px (phone) per event.
# The timeline has to show at least three times as many events per screen.
FORMER_CARD_HEIGHT = {"desktop": 134, "mobile": 193}

# Newest first, as the API returns them: a run of three health changes, then a single SNR event.
RUN_EVENTS = [
    {"id": 41, "timestamp": "2026-10-04T18:00:00", "severity": "warning", "event_type": "health_change",
     "message": "Health changed", "details": {"prev": "good", "current": "marginal"}, "acknowledged": 0},
    {"id": 40, "timestamp": "2026-10-04T17:30:00", "severity": "info", "event_type": "health_change",
     "message": "Health changed", "details": {"prev": "marginal", "current": "good"}, "acknowledged": 0},
    {"id": 39, "timestamp": "2026-10-04T17:00:00", "severity": "warning", "event_type": "health_change",
     "message": "Health changed", "details": {"prev": "good", "current": "marginal"}, "acknowledged": 1},
    {"id": 38, "timestamp": "2026-10-04T09:15:00", "severity": "warning", "event_type": "snr_change",
     "message": "DS SNR dropped", "acknowledged": 0, "details": {
         "prev": 37.0, "current": 32.4, "threshold": "warning",
         "affected_channels": [{"channel": 13, "frequency": "746 MHz", "prev": 37.0, "current": 32.4, "delta": -4.6}]}},
]


def _base_url(page):
    return page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def _open_events(page, viewport):
    page.set_viewport_size(viewport)
    page.goto(f"{_base_url(page)}/?lang=de#events", wait_until="networkidle")
    page.wait_for_selector("#view-events.active", state="visible")
    page.wait_for_selector("#events-feed-card", state="visible")
    page.wait_for_selector("#events-feed .ev-row", state="visible")


def _serve_events(page, events):
    page.route(
        re.compile(r".*/api/events\?.*"),
        lambda route: route.fulfill(json={"events": events, "unacknowledged_count": 0}),
    )


def _timeline_geometry(page):
    return page.evaluate(
        """
        () => {
            const feed = document.querySelector('#events-feed');
            const view = document.querySelector('#view-events.active');
            const box = node => {
                const r = node.getBoundingClientRect();
                return {width: r.width, height: r.height};
            };
            const ack = document.querySelector('#events-feed .ev-ack');
            const select = document.querySelector('#events-feed .ev-select input');
            return {
                events: document.querySelectorAll('#events-feed [data-event-id]').length,
                feedHeight: feed.getBoundingClientRect().height,
                documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
                viewOverflow: view.scrollWidth - view.clientWidth,
                ack: ack ? box(ack) : null,
                select: select ? box(select.closest('label')) : null,
            };
        }
        """
    )


def test_desktop_timeline_is_three_times_denser_than_cards(demo_page):
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)

    expect(page.locator("#events-feed .ev-day").first).to_be_visible()
    expect(page.locator("#events-feed .ev-day-head").first).to_be_visible()
    expect(page.locator("#events-table")).to_have_count(0)
    # The page title is the only "Event Log" heading; the card has a toolbar instead.
    expect(page.locator("#view-events").get_by_text("Ereignisprotokoll", exact=True)).to_have_count(1)
    expect(page.locator("#events-summary")).to_have_text(re.compile(r"^\d+ Ereignisse angezeigt$"))

    geometry = _timeline_geometry(page)
    assert geometry["events"] >= 20
    assert geometry["feedHeight"] / geometry["events"] <= FORMER_CARD_HEIGHT["desktop"] / 3
    assert geometry["documentOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["viewOverflow"] <= MAX_HORIZONTAL_OVERFLOW

    ack = page.locator("#events-feed .ev-ack").first
    expect(ack).to_have_attribute("aria-label", re.compile(r"^Bestätigen: "))
    expect(ack).to_have_attribute("title", "Bestätigen")


def test_mobile_timeline_is_dense_with_touch_targets(demo_page):
    page = demo_page
    _open_events(page, MOBILE_VIEWPORT)

    expect(page.locator("#events-export-csv")).to_be_visible()
    geometry = _timeline_geometry(page)
    assert geometry["feedHeight"] / geometry["events"] <= FORMER_CARD_HEIGHT["mobile"] / 3
    assert geometry["documentOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["viewOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["ack"]["width"] >= MIN_TOUCH_TARGET and geometry["ack"]["height"] >= MIN_TOUCH_TARGET
    assert geometry["select"]["height"] >= MIN_TOUCH_TARGET
    for tab in page.locator("#events-severity-tabs .segmented-option").all():
        assert tab.bounding_box()["height"] >= MIN_TOUCH_TARGET


def test_repeated_events_collapse_into_an_expandable_run(demo_page):
    page = demo_page
    _serve_events(page, RUN_EVENTS)
    _open_events(page, DESKTOP_VIEWPORT)

    rows = page.locator("#events-feed .ev-rows > .ev-row")
    expect(rows).to_have_count(2)
    run = rows.nth(0)
    expect(run).to_have_class(re.compile(r"\bev-group\b"))
    expect(run).to_have_class(re.compile(r"\bev-sev-warning\b"))
    expect(run.locator(".ev-run")).to_contain_text("3×")
    members = run.locator(".ev-group-members")
    expect(members).to_be_hidden()

    toggle = run.locator(":scope > .ev-main")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(members.locator(".ev-row")).to_have_count(3)
    expect(members.locator(".ev-row.ev-acked")).to_have_count(1)
    # Nothing is said twice: members carry no type, the open header no preview or newest time.
    expect(members.locator(".ev-type")).to_have_count(0)
    expect(toggle.locator(".ev-msg")).to_be_hidden()
    expect(toggle.locator(".ev-time")).to_have_css("visibility", "hidden")

    toggle.click()
    expect(members).to_be_hidden()


def test_extra_lines_open_in_place_without_repeating_the_summary(demo_page):
    page = demo_page
    _serve_events(page, RUN_EVENTS)
    _open_events(page, DESKTOP_VIEWPORT)

    snr = page.locator('#events-feed [data-event-id="38"]')
    toggle = snr.locator(":scope > .ev-main")
    channel = toggle.locator(".ev-sub")
    expect(channel).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(channel).to_have_text("DS Kanal 13 · 746 MHz")
    assert toggle.inner_text().count("32,4") == 1
    expect(snr.locator(".ev-detail")).to_have_count(0)


def test_rows_do_not_repeat_their_type_or_offer_empty_details(demo_page):
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)

    rows = page.evaluate(
        """
        () => [...document.querySelectorAll('#events-feed .ev-rows > .ev-row:not(.ev-group)')].map(row => {
            const main = row.querySelector(':scope > .ev-main');
            const msg = main.querySelector('.ev-msg');
            return {
                type: main.querySelector('.ev-type').textContent.trim(),
                message: msg.textContent,
                toggle: main.hasAttribute('data-toggle'),
                hasExtra: !!msg.querySelector('.ev-sub'),
                truncated: msg.scrollWidth > msg.clientWidth + 1,
            };
        })
        """
    )
    assert rows
    for row in rows:
        assert row["type"].lower() not in row["message"].lower(), row
        assert row["toggle"] == (row["hasExtra"] or row["truncated"]), row


def test_selected_events_are_acknowledged_together(demo_page):
    page = demo_page
    events = json.loads(json.dumps(RUN_EVENTS))
    _serve_events(page, events)
    posted = []

    def acknowledge(route):
        posted.append(route.request.post_data_json)
        route.fulfill(json={"success": True, "count": len(posted[-1]["ids"])})

    page.route("**/api/events/acknowledge", acknowledge)
    _open_events(page, DESKTOP_VIEWPORT)

    run = page.locator("#events-feed .ev-group").first
    selected_button = page.locator("#btn-ack-selected")
    expect(selected_button).to_be_hidden()
    run.locator(":scope > .ev-select input").check()
    expect(selected_button).to_be_visible()
    expect(selected_button).to_have_text("Auswahl bestätigen (2)")

    with page.expect_request(re.compile(r".*/api/events/count\?scope=attention.*")):
        selected_button.click()
    assert posted == [{"ids": [41, 40]}]
    expect(run).to_have_class(re.compile(r"\bev-acked\b"))
    expect(run.locator(":scope > .ev-ack-done")).to_be_visible()
    expect(selected_button).to_be_hidden()
    # The SNR event is still open, so "acknowledge visible" stays available for it alone.
    visible_button = page.locator("#btn-ack-visible")
    expect(visible_button).to_be_visible()
    visible_button.click()
    expect(visible_button).to_be_hidden()
    assert posted[-1] == {"ids": [38]}


def test_single_acknowledge_keeps_focus_in_the_row(demo_page):
    page = demo_page
    _serve_events(page, json.loads(json.dumps(RUN_EVENTS)))
    page.route("**/api/events/acknowledge", lambda route: route.fulfill(json={"success": True, "count": 1}))
    _open_events(page, DESKTOP_VIEWPORT)

    snr = page.locator('#events-feed [data-event-id="38"]')
    snr.locator(".ev-ack").click()
    expect(snr).to_have_class(re.compile(r"\bev-acked\b"))
    expect(snr.locator(":scope > .ev-main")).to_be_focused()


def test_badge_only_counts_recent_unacknowledged_warnings(demo_page):
    page = demo_page
    with page.expect_response(re.compile(r".*/api/events/count\?scope=attention.*")) as response_info:
        _open_events(page, DESKTOP_VIEWPORT)
    count = response_info.value.json()["count"]
    assert count < 99

    badge = page.locator("#event-badge")
    if count:
        expect(badge).to_have_text(str(count))
    else:
        expect(badge).to_be_hidden()
    expect(badge).to_have_attribute("title", re.compile("letzten 24 Stunden"))

    # Filters change the log, never the badge.
    page.locator("#events-severity-tabs [data-severity='info']").click()
    expect(page.locator("#events-severity-tabs [data-severity='info']")).to_have_attribute("aria-pressed", "true")
    if count:
        expect(badge).to_have_text(str(count))
    else:
        expect(badge).to_be_hidden()


def test_event_export_link_tracks_active_filters(demo_page):
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)
    export = page.locator("#events-export-csv")
    expect(export).to_have_attribute("href", re.compile(r"/api/events/export\.csv\?.*exclude_operational=true"))

    page.locator("#events-severity-tabs [data-severity='warning']").click()
    expect(page.locator("#events-feed .ev-row").first).to_be_visible()
    expect(export).to_have_attribute(
        "href", re.compile(r"/api/events/export\.csv\?.*severity=warning.*exclude_operational=true"))

    device = page.locator("#device-filter-pill")
    device.click()
    expect(device).to_have_attribute("aria-pressed", "true")
    expect(export).to_have_attribute("href", re.compile(r"event_prefix=device_"))
    expect(export).to_have_attribute("href", re.compile(r"severity=warning"))

    operational = page.locator("#hide-operational-toggle")
    expect(operational).to_be_checked()
    page.locator(".events-switch").click()
    expect(operational).not_to_be_checked()
    expect(export).not_to_have_attribute("href", re.compile(r"exclude_operational"))


def test_event_export_stays_available_for_empty_filtered_feed(demo_page):
    page = demo_page
    _open_events(page, DESKTOP_VIEWPORT)
    page.route(
        re.compile(r".*/api/events\?.*severity=critical.*"),
        lambda route: route.fulfill(json={"events": [], "unacknowledged_count": 0}),
    )

    page.locator("#events-severity-tabs [data-severity='critical']").click()

    expect(page.locator("#events-empty")).to_be_visible()
    expect(page.locator("#events-export-csv")).to_be_visible()
    expect(page.locator("#btn-ack-visible")).to_be_hidden()
    expect(page.locator("#events-export-csv")).to_have_attribute(
        "href", re.compile(r"/api/events/export\.csv\?.*severity=critical.*exclude_operational=true"))


def test_event_numbers_use_the_page_language(demo_page):
    page = demo_page
    _serve_events(page, [{
        "id": 50, "timestamp": "2026-10-04T12:00:00", "severity": "warning", "event_type": "error_spike",
        "message": "Uncorrectable errors jumped", "details": {"prev": 0, "current": 1072, "delta": 1072},
        "acknowledged": 0,
    }])
    _open_events(page, DESKTOP_VIEWPORT)

    message = page.locator('#events-feed [data-event-id="50"] .ev-msg')
    expect(message).to_contain_text("+1.072")
    expect(message).to_contain_text("(0 → 1.072)")

    # English uses 12-hour times; the longer "12:00 PM" must not run into the icon.
    page.goto(f"{_base_url(page)}/?lang=en#events", wait_until="networkidle")
    row = page.locator('#events-feed [data-event-id="50"]')
    expect(row.locator(".ev-msg")).to_contain_text("+1,072")
    expect(row.locator(".ev-time")).to_contain_text("PM")
    time_box = row.locator(".ev-time").bounding_box()
    icon_box = row.locator(".ev-sev").bounding_box()
    assert time_box["x"] + time_box["width"] <= icon_box["x"]
    assert row.locator(".ev-time").evaluate("node => node.scrollWidth <= node.clientWidth")
