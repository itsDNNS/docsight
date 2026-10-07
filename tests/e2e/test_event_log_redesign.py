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
    # The demo journal's notes would join a fully loaded, served log; tests that want notes serve their own.
    page.route(re.compile(r".*/api/journal\?limit=1000.*"), lambda route: route.fulfill(json=[]))


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


def test_acknowledging_offers_undo_that_restores_the_row(demo_page):
    page = demo_page
    _serve_events(page, json.loads(json.dumps(RUN_EVENTS)))
    calls = []

    def record(route):
        calls.append((route.request.url.rsplit("/", 1)[-1], route.request.post_data_json))
        route.fulfill(json={"success": True, "count": len(calls[-1][1]["ids"])})

    page.route("**/api/events/acknowledge", record)
    page.route("**/api/events/unacknowledge", record)
    _open_events(page, DESKTOP_VIEWPORT)

    snr = page.locator('#events-feed [data-event-id="38"]')
    snr.locator(".ev-ack").click()
    expect(snr).to_have_class(re.compile(r"\bev-acked\b"))
    toast = page.locator("#toast")
    expect(toast).to_contain_text("Ereignis bestätigt")
    undo = toast.get_by_role("button", name="Rückgängig")
    expect(undo).to_be_visible()

    # Focus pauses the time left, so keyboard users can reach the button.
    undo.focus()
    expect(toast).to_have_class(re.compile(r"\btoast-paused\b"))
    undo.press("Enter")
    expect(toast).to_be_hidden()
    expect(snr).not_to_have_class(re.compile(r"\bev-acked\b"))
    expect(snr.locator(".ev-ack")).to_be_visible()
    assert calls == [("acknowledge", {"ids": [38]}), ("unacknowledge", {"ids": [38]})]


def test_acknowledged_events_stay_acknowledged_when_the_undo_time_runs_out(demo_page):
    page = demo_page
    page.clock.install()
    _serve_events(page, json.loads(json.dumps(RUN_EVENTS)))
    calls = []
    page.route("**/api/events/acknowledge", lambda route: (calls.append("acknowledge"), route.fulfill(json={"success": True, "count": 2}))[1])
    page.route("**/api/events/unacknowledge", lambda route: (calls.append("unacknowledge"), route.fulfill(json={"success": True, "count": 2}))[1])
    _open_events(page, DESKTOP_VIEWPORT)

    run = page.locator("#events-feed .ev-group").first
    run.locator(":scope > .ev-select input").check()
    page.locator("#btn-ack-selected").click()
    expect(page.locator("#toast")).to_contain_text("2 Ereignisse bestätigt")
    page.mouse.move(5, 5)
    page.clock.run_for(6500)
    expect(page.locator("#toast")).to_be_hidden()
    expect(run).to_have_class(re.compile(r"\bev-acked\b"))
    assert calls == ["acknowledge"]
NOTES = [
    {"id": 501, "date": "2026-10-04", "title": "Technician replaced the amplifier", "incident_id": 7},
    {"id": 502, "date": "2026-10-02", "title": "Quiet day note", "incident_id": None},
]


def _serve_notes(page, notes):
    page.route(re.compile(r".*/api/journal\?limit=1000.*"), lambda route: route.fulfill(json=notes))
    page.route(re.compile(r".*/api/incidents$"), lambda route: route.fulfill(json=[{"id": 7, "name": "Evening dropouts"}]))
    page.route(re.compile(r".*/api/journal/501$"), lambda route: route.fulfill(json={**NOTES[0], "description": "", "icon": None, "attachments": []}))


def test_journal_notes_sit_at_their_day_and_open_the_entry(demo_page):
    page = demo_page
    _serve_events(page, json.loads(json.dumps(RUN_EVENTS)))
    _serve_notes(page, NOTES)
    _open_events(page, DESKTOP_VIEWPORT)

    note = page.locator('#events-feed .ev-note[data-key="n501"]')
    expect(note).to_be_visible()
    expect(note).to_contain_text("Journal-Notiz")
    expect(note).to_contain_text("Technician replaced the amplifier")
    expect(note).to_contain_text("Evening dropouts")
    # Notes carry no time, so they lead their day; they offer neither selection nor acknowledge.
    day = note.locator("xpath=ancestor::section[1]")
    expect(day.locator(".ev-row").first).to_have_attribute("data-key", "n501")
    expect(note.locator("input, .ev-ack")).to_have_count(0)
    # The whole log is loaded, so an older day with only a note gets its own section.
    quiet = page.locator('#events-feed .ev-note[data-key="n502"]')
    expect(quiet).to_be_visible()
    expect(quiet.locator("xpath=ancestor::section[1]").locator(".ev-row")).to_have_count(1)

    note.get_by_role("button").click()
    expect(page.locator("#entry-modal")).to_be_visible()
    expect(page.locator("#entry-title-input")).to_have_value("Technician replaced the amplifier")


def test_notes_older_than_the_loaded_page_wait_for_it(demo_page):
    page = demo_page
    events = [{"id": 1000 - i, "timestamp": f"2026-10-04T{23 - i // 3:02d}:{(i % 3) * 15:02d}:00", "severity": "info",
               "event_type": "health_change" if i % 2 else "snr_change", "message": "x", "details": {}, "acknowledged": 1}
              for i in range(50)]
    _serve_events(page, events)
    _serve_notes(page, [
        {"id": 601, "date": "2026-10-05", "title": "After the newest event", "incident_id": None},
        {"id": 602, "date": "2026-10-03", "title": "Before the loaded page", "incident_id": None},
    ])
    _open_events(page, DESKTOP_VIEWPORT)
    expect(page.locator("#events-show-more")).to_be_visible()
    expect(page.locator('#events-feed .ev-note[data-key="n601"]')).to_be_visible()
    expect(page.locator('#events-feed .ev-note[data-key="n602"]')).to_have_count(0)


def test_severity_filters_show_events_only(demo_page):
    page = demo_page
    _serve_events(page, json.loads(json.dumps(RUN_EVENTS)))
    _serve_notes(page, NOTES)
    _open_events(page, DESKTOP_VIEWPORT)
    expect(page.locator("#events-feed .ev-note")).to_have_count(2)
    page.locator('#events-severity-tabs [data-severity="warning"]').click()
    expect(page.locator("#events-feed .ev-row").first).to_be_visible()
    expect(page.locator("#events-feed .ev-note")).to_have_count(0)


CASES = [
    {"id": 3, "name": "Resolved earlier", "status": "resolved", "start_date": "2026-09-01", "end_date": "2026-09-03"},
    {"id": 7, "name": "Evening dropouts", "status": "open", "start_date": "2026-10-01", "end_date": None},
]


def _serve_cases(page):
    sent = []

    def handle(route):
        request = route.request
        if request.method == "POST":
            sent.append((request.url.split("/api/", 1)[1], request.post_data_json))
            route.fulfill(status=201, json={"id": 9} if request.url.endswith("/api/incidents") else {"success": True})
        else:
            route.fulfill(json=CASES)

    page.route(re.compile(r".*/api/incidents(/\d+/extend)?$"), handle)
    return sent


def test_selected_events_widen_an_existing_case(demo_page):
    page = demo_page
    _serve_events(page, json.loads(json.dumps(RUN_EVENTS)))
    sent = _serve_cases(page)
    _open_events(page, DESKTOP_VIEWPORT)

    # The run includes an acknowledged event; with the journal it can still be picked for a case.
    page.locator("#events-feed .ev-group").first.locator(":scope > .ev-select input").check()
    page.locator('#events-feed [data-event-id="38"] .ev-select input').check()
    add = page.locator("#btn-add-to-case")
    expect(add).to_have_text("Zu Fall hinzufügen… (4)")
    expect(page.locator("#btn-ack-selected")).to_have_text("Auswahl bestätigen (3)")

    add.click()
    dialog = page.locator("#add-to-case-modal")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#add-to-case-summary")).to_contain_text("4 Ereignisse")
    options = dialog.locator(".case-pick-list .case-pick-name")
    expect(options).to_have_text(["Evening dropouts", "Resolved earlier"])
    dialog.get_by_label("Resolved earlier").check()
    expect(dialog.locator(".case-pick-new-name")).to_be_hidden()
    dialog.locator("#add-to-case-submit").click()

    expect(dialog).to_be_hidden()
    expect(page.locator("#toast")).to_contain_text("4 Ereignisse zu „Resolved earlier“ hinzugefügt")
    expect(page.locator("#toast").get_by_role("button", name="Fall öffnen")).to_be_visible()
    assert sent == [("incidents/3/extend", {"start_date": "2026-10-04", "end_date": "2026-10-04"})]
    expect(add).to_be_hidden()


def test_selected_events_start_a_new_case_with_their_days(demo_page):
    page = demo_page
    _serve_events(page, json.loads(json.dumps(RUN_EVENTS)))
    sent = _serve_cases(page)
    _open_events(page, DESKTOP_VIEWPORT)

    page.locator('#events-feed [data-event-id="38"] .ev-select input').check()
    page.locator("#btn-add-to-case").click()
    dialog = page.locator("#add-to-case-modal")
    dialog.get_by_label("Neuer Fall").check()
    name = dialog.locator("#add-to-case-name")
    expect(name).to_be_visible()
    name.fill("SNR drop")
    dialog.locator("#add-to-case-submit").click()
    expect(page.locator("#toast")).to_contain_text("1 Ereignis zu „SNR drop“ hinzugefügt")
    assert sent == [("incidents", {"name": "SNR drop", "status": "open", "start_date": "2026-10-04", "end_date": "2026-10-04"})]


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
