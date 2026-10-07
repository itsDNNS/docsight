"""BQM and SmokePing graphs share one frame: title and window, the graph on paper, the source."""

from datetime import datetime, timezone
from io import BytesIO

from PIL import Image
from playwright.sync_api import expect

from tests.e2e.support.navigation import open_view


def _png():
    image = BytesIO()
    Image.new("RGB", (64, 32), "white").save(image, format="PNG")
    return image.getvalue()


def test_bqm_graph_sits_in_the_frame_with_its_day(page, live_server):
    page.clock.install(time=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))
    page.route("**/api/bqm/data/dates", lambda route: route.fulfill(json={"csv_dates": [], "png_dates": ["2026-06-12"]}))
    page.route("**/api/bqm/image/2026-06-12", lambda route: route.fulfill(content_type="image/png", body=_png()))
    page.goto(live_server + "/?lang=en#bqm", wait_until="networkidle")

    page.locator(".bqm-day", has_text="12").first.click()
    frame = page.locator("#bqm-card")
    expect(frame).to_have_class("graph-frame")
    expect(frame.locator(".graph-frame-title")).to_have_text("Broadband Quality Monitor")
    expect(frame.locator("#bqm-window")).to_have_text("06/12/2026 · whole day")
    expect(frame.locator(".graph-frame-paper #bqm-image")).to_be_visible()
    expect(frame.locator(".graph-frame-foot")).to_contain_text("one graph per day")


def _serve_smokeping(page, requested):
    page.route("**/api/smokeping/targets", lambda route: route.fulfill(json=["Gateway", "DNS"]))

    def graph(route):
        requested.append(route.request.url.rsplit("/", 2)[-2:])
        route.fulfill(content_type="image/png", body=_png())

    page.route("**/api/smokeping/graph/**", graph)


def test_smokeping_follows_the_app_range_with_its_closest_graph(demo_page):
    page = demo_page
    requested = []
    _serve_smokeping(page, requested)
    open_view(page, "smokeping")

    frames = page.locator("#smokeping-content .graph-frame")
    expect(frames).to_have_count(2)
    expect(page.locator('#smokeping-tabs [data-smokeping-range="1d"]')).to_have_attribute("aria-pressed", "true")
    expect(frames.first.locator(".graph-frame-title")).to_have_text("SmokePing · Gateway")
    expect(frames.first.locator(".graph-frame-window")).to_have_text("last 30 hours")
    expect(frames.first.locator(".graph-frame-note")).to_have_text("closest to 1d")
    expect(frames.first.locator(".graph-frame-paper img")).to_be_visible()
    assert ["Gateway", "30h"] in requested and ["DNS", "30h"] in requested
    # Demo mode has no SmokePing address, so there is nothing to open.
    expect(frames.first.locator(".graph-frame-foot a")).to_have_count(0)

    page.locator('#smokeping-tabs [data-smokeping-range="7d"]').click()
    expect(frames.first.locator(".graph-frame-window")).to_have_text("last 10 days")
    expect(frames.first.locator(".graph-frame-note")).to_have_text("closest to 7d")
    assert page.evaluate("location.hash") == "#smokeping?range=7d"
    assert ["Gateway", "10d"] in requested


def test_smokeping_deep_link_and_source_link(demo_page):
    page = demo_page
    requested = []
    _serve_smokeping(page, requested)
    base = page.url.split("#", 1)[0].split("?", 1)[0]
    page.goto(base + "?lang=en#smokeping?range=90d", wait_until="networkidle")
    frames = page.locator("#smokeping-content .graph-frame")
    expect(frames.first.locator(".graph-frame-window")).to_have_text("last year")
    expect(page.locator('#smokeping-tabs [data-smokeping-range="90d"]')).to_have_attribute("aria-pressed", "true")

    # The server renders this link when a SmokePing address is configured (demo mode has none).
    page.evaluate("""() => document.getElementById('view-smokeping').insertAdjacentHTML('afterbegin',
        '<a id="smokeping-source-link" href="http://smokeping.lan/smokeping/" target="_blank" rel="noopener" hidden>Open in SmokePing</a>')""")
    page.locator('#smokeping-tabs [data-smokeping-range="1h"]').click()
    link = frames.first.locator(".graph-frame-foot a")
    expect(link).to_have_attribute("href", "http://smokeping.lan/smokeping/?target=Gateway")
    expect(link).to_have_attribute("rel", "noopener")
    expect(frames.first.locator(".graph-frame-window")).to_have_text("last 3 hours")


def test_a_graph_that_fails_to_load_says_so_inside_its_frame(demo_page):
    page = demo_page
    page.route("**/api/smokeping/targets", lambda route: route.fulfill(json=["Gateway"]))
    page.route("**/api/smokeping/graph/**", lambda route: route.fulfill(status=502, json={"error": "x"}))
    open_view(page, "smokeping")
    frame = page.locator("#smokeping-content .graph-frame").first
    expect(frame.locator(".graph-frame-message")).to_have_text("Could not load Smokeping graphs.")
    expect(frame.locator(".graph-frame-title")).to_be_visible()
