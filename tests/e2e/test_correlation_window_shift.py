"""Correlation windows that end in the past: every source follows the window."""

import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect


def _record(page):
    seen = []

    def record(request):
        url = urlparse(request.url)
        if url.path.endswith(("/api/correlation", "/api/channel-status")):
            seen.append((url.path.rsplit("/", 1)[-1], parse_qs(url.query)))

    page.on("request", record)
    return seen


def _eventually(page, condition):
    for _ in range(100):
        if condition():
            return True
        page.wait_for_timeout(50)
    return condition()


def _hash_end(page):
    query = page.evaluate("location.hash").split("?", 1)[-1]
    return parse_qs(query).get("end", [None])[0]


def test_stepping_back_moves_every_source_and_the_chart_axis(page, live_server):
    seen = _record(page)
    page.goto(f"{live_server}/?lang=en#correlation?range=1d", wait_until="networkidle")
    expect(page.locator("#correlation-chart-container")).to_be_visible()
    seen.clear()

    page.click("#correlation-window-earlier")
    end = _hash_end(page)
    assert end is not None
    expect(page.locator("#correlation-window-past")).to_be_visible()
    assert _eventually(page, lambda: any(path == "channel-status" for path, _ in seen))

    correlation = [query for path, query in seen if path == "correlation"]
    status = [query for path, query in seen if path == "channel-status"]
    assert correlation and correlation[-1]["end"] == [end]
    assert status and status[-1]["end"] == [end + ":00"]
    assert "range" not in status[-1]
    # The chart spans the past window, so "Save as case" and exports cover it too.
    end_ms = page.evaluate("end => DOCSightWindowShift.fromParam(end)", end)
    span = page.evaluate("_corrSelectedRange")
    assert abs(span["endMs"] - end_ms) < 1000
    assert abs(span["endMs"] - span["startMs"] - 24 * 3600 * 1000) < 2000


def test_a_deep_link_restores_the_past_window_and_back_to_now_leaves_it(page, live_server):
    seen = _record(page)
    page.goto(f"{live_server}/?lang=en#correlation?range=6h", wait_until="networkidle")
    end = page.evaluate("DOCSightWindowShift.toParam(Date.now() - 2 * 86400000)")[:11] + "20:00"

    page.goto(f"{live_server}/?lang=en#correlation?range=6h&end={end}")
    page.reload(wait_until="networkidle")
    expect(page.locator("#correlation-window-past")).to_be_visible()
    assert any(path == "correlation" and query.get("end") == [end] for path, query in seen)

    page.click("#correlation-window-now")
    assert _hash_end(page) is None
    expect(page.locator("#correlation-window-past")).to_be_hidden()
    assert _eventually(page, lambda: [query for path, query in seen if path == "correlation"][-1].get("end") is None)


def test_a_swipe_on_the_correlation_chart_steps_the_window(browser, live_server):
    context = browser.new_context(viewport={"width": 393, "height": 852}, has_touch=True, is_mobile=True)
    page = context.new_page()
    page.goto(f"{live_server}/?lang=en#correlation?range=1d", wait_until="networkidle")
    overlay = page.locator("#correlation-overlay")
    expect(overlay).to_be_visible()
    overlay.scroll_into_view_if_needed()
    box = overlay.bounding_box()
    cdp = context.new_cdp_session(page)
    y = box["y"] + box["height"] / 3
    x = box["x"] + box["width"] * 0.2
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for step in range(1, 7):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x + step * 30, "y": y}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

    assert _hash_end(page) is not None
    expect(page.locator("#correlation-window-past")).to_be_visible()
    context.close()


def test_a_late_answer_for_an_earlier_step_does_not_replace_the_latest_window(page, live_server):
    page.goto(f"{live_server}/?lang=en#correlation?range=1d", wait_until="networkidle")
    expect(page.locator("#correlation-chart-container")).to_be_visible()
    held = []

    def hold_first_step(route):
        if not held:
            held.append(route)  # answered later, after the second step
        else:
            route.continue_()

    page.evaluate("window.__stateBefore = _corrChartState")
    page.route(re.compile(r".*/api/correlation\?.*&end=.*"), hold_first_step)
    page.click("#correlation-window-earlier")
    assert _eventually(page, lambda: held)
    page.click("#correlation-window-earlier")
    page.wait_for_function("() => _corrChartState !== window.__stateBefore")
    shown = page.evaluate("_correlationData.length")
    assert shown > 1

    held[0].fulfill(json=[{"timestamp": "2020-01-01T00:00:00Z", "source": "modem", "health": "good"}])
    page.wait_for_timeout(500)
    assert page.evaluate("_correlationData.length") == shown
