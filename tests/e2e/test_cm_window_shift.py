"""Connection Monitor windows that end in the past: no refresh, no pinning of today."""

import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect


def _sample_ends(page):
    ends = []

    def record(request):
        url = urlparse(request.url)
        if "/api/connection-monitor/samples/" in url.path:
            ends.append(float(parse_qs(url.query)["end"][0]))

    page.on("request", record)
    return ends


def _eventually(page, condition):
    for _ in range(100):
        if condition():
            return True
        page.wait_for_timeout(50)
    return condition()


def _hash_end(page):
    query = page.evaluate("location.hash").split("?", 1)[-1]
    return parse_qs(query).get("end", [None])[0]


def test_a_past_window_loads_its_samples_and_pauses_the_refresh(page, live_server):
    page.clock.install()
    ends = _sample_ends(page)
    page.goto(f"{live_server}/?lang=en#connection-monitor?range=1d", wait_until="networkidle")
    expect(page.locator("#cm-pin-day-btn")).to_be_visible()

    page.click("#cm-window-earlier")
    end = _hash_end(page)
    assert end is not None
    end_s = page.evaluate("end => DOCSightWindowShift.fromParam(end) / 1000", end)
    assert _eventually(page, lambda: ends and ends[-1] == end_s)
    expect(page.locator("#cm-window-past")).to_be_visible()
    # "Pin this day" pins today, which is not the day shown.
    expect(page.locator("#cm-pin-day-btn")).to_be_hidden()

    # The 1d window refreshes every 10 s while it ends now, never in the past.
    count = len(ends)
    page.clock.run_for(25000)
    page.wait_for_timeout(500)
    assert len(ends) == count

    page.click("#cm-window-now")
    assert _hash_end(page) is None
    expect(page.locator("#cm-pin-day-btn")).to_be_visible()
    count = len(ends)
    page.clock.run_for(25000)
    assert _eventually(page, lambda: len(ends) > count)


def test_a_deep_link_opens_the_past_window(page, live_server):
    ends = _sample_ends(page)
    page.goto(f"{live_server}/?lang=en#connection-monitor?range=6h", wait_until="networkidle")
    end = page.evaluate("DOCSightWindowShift.toParam(Date.now() - 2 * 86400000)")[:11] + "20:00"
    end_s = page.evaluate("end => DOCSightWindowShift.fromParam(end) / 1000", end)

    page.goto(f"{live_server}/?lang=en#connection-monitor?range=6h&end={end}")
    page.reload(wait_until="networkidle")
    expect(page.locator("#cm-window-past")).to_be_visible()
    assert ends[-1] == end_s
    expect(page.locator('#cm-range-tabs [data-cm-range="21600"]')).to_have_attribute("aria-pressed", "true")


def test_a_late_answer_for_an_earlier_step_does_not_replace_the_latest_window(page, live_server):
    page.goto(f"{live_server}/?lang=en#connection-monitor?range=1d", wait_until="networkidle")
    expect(page.locator("#cm-combined-chart .u-over")).to_be_visible()
    held = []

    # Hold one sample request of the first step; the rest of the page keeps loading.
    def hold_first_step(route):
        if not held and "end=" in route.request.url:
            held.append(route)
        else:
            route.continue_()

    page.evaluate("window.__chartBefore = charts['cm-combined-chart']")
    page.route(re.compile(r".*/api/connection-monitor/samples/.*"), hold_first_step)
    page.click("#cm-window-earlier")
    assert _eventually(page, lambda: held)
    page.click("#cm-window-earlier")
    page.wait_for_function("() => charts['cm-combined-chart'] !== window.__chartBefore")
    page.evaluate("window.__chartSecond = charts['cm-combined-chart']")

    held[0].fulfill(json={"meta": {"resolution": "raw"}, "samples": [
        {"timestamp": 1577836800, "latency_ms": 99.0, "timeout": False}]})
    page.wait_for_timeout(500)
    assert page.evaluate("charts['cm-combined-chart'] === window.__chartSecond")


def test_a_zoom_does_not_follow_into_the_next_window(page, live_server):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{live_server}/?lang=en#connection-monitor?range=1d", wait_until="networkidle")
    over = page.locator("#cm-combined-chart .u-over")
    expect(over).to_be_visible()
    box = over.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * 0.4, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.6, y, steps=8)
    page.mouse.up()
    expect(page.locator("#cm-combined-chart .chart-zoom-reset")).to_be_visible()
    page.evaluate("window.__chartBefore = charts['cm-combined-chart']")

    page.click("#cm-window-earlier")
    page.wait_for_function("() => charts['cm-combined-chart'] !== window.__chartBefore")
    assert page.evaluate("charts['cm-combined-chart']._zoomRange") is None
    expect(page.locator("#cm-combined-chart .chart-zoom-reset")).to_have_count(0)
