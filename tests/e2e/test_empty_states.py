"""Shared empty state: views without content explain why and offer one next step."""

import re

from playwright.sync_api import expect


def _base_url(page):
    return page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def _open(page, view_hash):
    page.goto(f"{_base_url(page)}/?lang=en#{view_hash}", wait_until="networkidle")


def _expect_state(empty, title, action):
    expect(empty).to_be_visible()
    expect(empty).to_have_attribute("role", "status")
    expect(empty.locator(".view-empty-icon svg")).to_be_visible()
    expect(empty.locator(".view-empty-title")).to_have_text(title)
    expect(empty.locator(".view-empty-text")).not_to_be_empty()
    expect(empty.locator(".view-empty-action")).to_have_text(action)


def test_empty_range_offers_the_longest_range_then_the_modem_connection(demo_page):
    page = demo_page
    requests = []
    page.route(re.compile(r".*/api/trends\?.*"), lambda route: (requests.append(route.request.url), route.fulfill(json=[])))
    _open(page, "trends")

    empty = page.locator("#trend-no-data")
    _expect_state(empty, "No data in this period", "Show 90d")
    expect(empty.locator(".view-empty-link")).to_have_attribute("href", "#glossary?term=signal_trends")
    expect(page.locator("#charts-grid")).to_be_hidden()

    empty.locator(".view-empty-action").click()
    expect(page.locator("#trend-tabs .trend-tab.active")).to_have_text("90d")
    assert "range=90d" in requests[-1]
    _expect_state(empty, "No measurements yet", "Check modem connection")
    expect(empty.locator(".view-empty-action")).to_have_attribute("href", re.compile(r"/settings#connection$"))


def test_failed_load_offers_a_retry_that_restores_the_view(demo_page):
    page = demo_page
    calls = {"count": 0}

    def trends(route):
        calls["count"] += 1
        if calls["count"] == 1:
            route.fulfill(status=500, body="down")
        else:
            route.fallback()

    page.route(re.compile(r".*/api/trends\?.*"), trends)
    _open(page, "trends")

    empty = page.locator("#trend-no-data")
    _expect_state(empty, "Could not load the data", "Try again")
    expect(empty.locator(".view-empty-link")).to_have_count(0)
    empty.locator(".view-empty-action").click()
    expect(empty).to_be_hidden()
    expect(page.locator("#charts-grid")).to_be_visible()


def test_correlation_without_data_uses_the_shared_state(demo_page):
    page = demo_page
    page.route(re.compile(r".*/api/correlation\?.*"), lambda route: route.fulfill(json=[]))
    page.route(re.compile(r".*/api/connection-monitor/.*"), lambda route: route.fulfill(json=[]))
    _open(page, "correlation")

    empty = page.locator("#correlation-no-data")
    _expect_state(empty, "No data in this period", re.compile(r"^Show \w+$"))
    expect(empty.locator(".view-empty-link")).to_have_attribute("href", "#glossary?term=correlation_analysis")


def test_channel_status_failure_offers_a_retry(demo_page):
    page = demo_page
    page.route(re.compile(r".*/api/channel-status\?.*"), lambda route: route.fulfill(status=503, body="busy"))
    _open(page, "channels")

    empty = page.locator("#channel-status-empty")
    _expect_state(empty, "Could not load the data", "Try again")
    page.unroute(re.compile(r".*/api/channel-status\?.*"))
    empty.locator(".view-empty-action").click()
    expect(empty).to_be_hidden()
    expect(page.locator("#channel-status-body")).not_to_be_empty()


def test_channel_modes_without_a_selection_point_at_the_picker(demo_page):
    page = demo_page
    _open(page, "channels")

    page.locator('#channel-mode-tabs .trend-tab[data-value="timeline"]').click()
    onboarding = page.locator("#channel-empty")
    _expect_state(onboarding, "Channel Timeline", "Choose a channel")
    onboarding.locator(".view-empty-action").click()
    expect(page.locator("#channel-select")).to_be_focused()

    page.locator('#channel-mode-tabs .trend-tab[data-value="compare"]').click()
    compare = page.locator("#compare-empty")
    _expect_state(compare, "Select channels to compare", "Choose channels")
    compare.locator(".view-empty-action").click()
    expect(page.locator("#compare-channel-select")).to_be_focused()


def test_empty_event_log_distinguishes_filters_from_no_events(demo_page):
    page = demo_page
    page.route(re.compile(r".*/api/events\?.*"), lambda route: route.fulfill(json={"events": [], "unacknowledged_count": 0}))
    _open(page, "events")

    empty = page.locator("#events-empty")
    _expect_state(empty, "No events yet", "Set up notifications")
    expect(empty.locator(".view-empty-action")).to_have_attribute("href", re.compile(r"/settings#notifications$"))

    page.locator("#events-severity-tabs [data-severity='critical']").click()
    _expect_state(empty, "No events match these filters", "Show all events")
    with page.expect_request(lambda request: "/api/events?" in request.url and "severity=" not in request.url):
        empty.locator(".view-empty-action").click()
    expect(page.locator("#events-severity-tabs [data-severity='']")).to_have_attribute("aria-pressed", "true")
    _expect_state(empty, "No events yet", "Set up notifications")


def test_broadband_measurement_without_reports_offers_the_upload(demo_page):
    page = demo_page
    page.route("**/api/bnetz/measurements", lambda route: route.fulfill(json=[]))
    _open(page, "bnetz")

    empty = page.locator("#bnetz-empty")
    _expect_state(empty, "No measurements uploaded yet", re.compile(r"\S"))
    expect(empty.locator(".view-empty-link")).to_have_attribute("href", "#glossary?term=bnetza")
    with page.expect_file_chooser() as chooser:
        empty.locator(".view-empty-action").click()
    assert chooser.value.element.get_attribute("id") == "bnetz-file-input"


def test_glossary_link_opens_the_term(demo_page):
    page = demo_page
    page.route(re.compile(r".*/api/trends\?.*"), lambda route: route.fulfill(json=[]))
    _open(page, "trends")

    page.locator("#trend-no-data .view-empty-link").click()
    expect(page.locator("#view-glossary")).to_be_visible()
    assert "term=signal_trends" in page.url
