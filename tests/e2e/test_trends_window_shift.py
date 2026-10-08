"""Trends windows that end in the past: arrows, deep link, Back to now, swipe."""

import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect


def _record_trend_ends(page):
    ends = []

    def record(request):
        if "/api/trends?" in request.url:
            ends.append(parse_qs(urlparse(request.url).query).get("end", [None])[0])

    page.on("request", record)
    return ends


# Timestamps and ends are both wall-clock time in DOCSight's zone, so they compare as text.
def _shows_window_ending_at(page, end):
    page.wait_for_function(
        "end => _lastTrendData && _lastTrendData[_lastTrendData.length - 1].timestamp.slice(0, 16) <= end", arg=end)


def _shows_data_after(page, time):
    page.wait_for_function(
        "time => _lastTrendData && _lastTrendData[_lastTrendData.length - 1].timestamp.slice(0, 16) > time", arg=time)


def _hash_end(page):
    query = page.evaluate("location.hash").split("?", 1)[-1]
    return parse_qs(query).get("end", [None])[0]


def _instant(page, end):
    return page.evaluate("end => DOCSightWindowShift.fromParam(end)", end)


def _open(page, base, fragment):
    page.goto(f"{base}/?lang=en#{fragment}", wait_until="networkidle")
    expect(page.locator("#chart-ds-power .u-over")).to_be_visible()


def test_the_arrows_step_the_window_by_its_length_and_back_to_now(page, live_server):
    ends = _record_trend_ends(page)
    _open(page, live_server, "trends?range=1d")
    past = page.locator("#trend-window-past")
    later = page.locator("#trend-window-later")
    expect(past).to_be_hidden()
    expect(later).to_be_disabled()

    page.click("#trend-window-earlier")
    expect(past).to_be_visible()
    expect(later).to_be_enabled()
    first = _hash_end(page)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", first), first
    _shows_window_ending_at(page, first)
    assert first in ends

    page.click("#trend-window-earlier")
    page.wait_for_load_state("networkidle")
    second = _hash_end(page)
    _shows_window_ending_at(page, second)
    assert _instant(page, first) - _instant(page, second) == 24 * 3600 * 1000

    page.click("#trend-window-later")
    page.wait_for_load_state("networkidle")
    assert _hash_end(page) == first

    # One more step reaches now: the window follows new polls again.
    page.click("#trend-window-later")
    page.wait_for_load_state("networkidle")
    assert _hash_end(page) is None
    _shows_data_after(page, first)
    expect(past).to_be_hidden()
    expect(later).to_be_disabled()


def test_a_deep_link_restores_a_past_window_and_back_to_now_leaves_it(page, live_server):
    ends = _record_trend_ends(page)
    _open(page, live_server, "trends?range=6h")
    # Two days back, at 20:00 in DOCSight's zone.
    end = page.evaluate("DOCSightWindowShift.toParam(Date.now() - 2 * 86400000)")[:11] + "20:00"
    day_before = (date.fromisoformat(end[:10]) - timedelta(days=1)).strftime("%m/%d")

    _open(page, live_server, f"trends?range=6h&end={end}")
    page.reload(wait_until="networkidle")
    expect(page.locator("#trend-window-past")).to_be_visible()
    expect(page.locator("#trend-window-range")).to_have_text(re.compile(rf"{end[5:7]}/{end[8:10]}, .*"))
    assert end in ends
    expect(page.locator('#trend-tabs [data-range="6h"]')).to_have_attribute("aria-pressed", "true")
    _shows_window_ending_at(page, end)

    # A new range keeps the end; the span follows the new length.
    page.click('#trend-tabs [data-range="1d"]')
    page.wait_for_load_state("networkidle")
    assert _hash_end(page) == end
    expect(page.locator("#trend-window-range")).to_have_text(re.compile(rf"{day_before}, .*"))

    page.click("#trend-window-now")
    page.wait_for_load_state("networkidle")
    assert _hash_end(page) is None
    assert "range=1d" in page.evaluate("location.hash")
    expect(page.locator("#trend-window-past")).to_be_hidden()
    _shows_data_after(page, end)


def test_a_late_answer_for_an_earlier_step_does_not_replace_the_latest_window(page, live_server):
    _open(page, live_server, "trends?range=1d")
    held = []

    def hold_first_step(route):
        if "end=" in route.request.url and not held:
            held.append(route)  # answered later, after the second step
        else:
            route.continue_()

    page.route(re.compile(r".*/api/trends\?range=1d&end=.*"), hold_first_step)
    page.click("#trend-window-earlier")
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held
    page.click("#trend-window-earlier")
    second = _hash_end(page)
    _shows_window_ending_at(page, second)
    shown = page.evaluate("_lastTrendData.length")

    held[0].fulfill(json=[{"timestamp": "2020-01-01T00:00:00", "ds_power_avg": 99.0, "ds_snr_avg": 40.0,
                           "us_power_avg": 40.0}])
    page.wait_for_timeout(300)
    assert page.evaluate("_lastTrendData.length") == shown
    assert page.evaluate("_lastTrendData.every(row => row.ds_power_avg !== 99.0)")


@pytest.fixture
def phone(browser, live_server):
    context = browser.new_context(viewport={"width": 393, "height": 852}, has_touch=True, is_mobile=True)
    page = context.new_page()
    page.goto(f"{live_server}/?lang=en#trends?range=1d", wait_until="networkidle")
    expect(page.locator("#chart-ds-power .u-over")).to_be_visible()
    page.locator("#chart-ds-power").scroll_into_view_if_needed()
    cdp = context.new_cdp_session(page)
    yield page, cdp
    context.close()


def _touch(cdp, kind, x=None, y=None):
    points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


def _swipe(page, cdp, direction, hold_ms=0):
    box = page.locator("#chart-ds-power .u-over").bounding_box()
    y = box["y"] + box["height"] / 2
    start = box["x"] + box["width"] * (0.2 if direction > 0 else 0.8)
    _touch(cdp, "touchStart", start, y)
    if hold_ms:
        page.wait_for_timeout(hold_ms)
    for step in range(1, 7):
        _touch(cdp, "touchMove", start + direction * step * 30, y)
    _touch(cdp, "touchEnd")
    page.wait_for_load_state("networkidle")


def test_a_swipe_on_a_phone_steps_the_window_and_holding_reads_values(phone):
    page, cdp = phone
    expect(page.locator("#trend-window-hint")).to_be_visible()

    _swipe(page, cdp, 1)
    end = _hash_end(page)
    assert end is not None
    expect(page.locator("#trend-window-past")).to_be_visible()
    # The hint has done its job after the first swipe.
    expect(page.locator("#trend-window-hint")).to_be_hidden()

    # Press and hold, then slide: reads values, does not move the window.
    _swipe(page, cdp, -1, hold_ms=500)
    assert _hash_end(page) == end

    _swipe(page, cdp, -1)
    assert _hash_end(page) is None
    expect(page.locator("#trend-window-past")).to_be_hidden()
