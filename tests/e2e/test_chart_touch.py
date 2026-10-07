"""Charts on phones: a swipe scrolls the page, press and hold reads values."""

import pytest
from playwright.sync_api import expect


@pytest.fixture
def phone(browser, live_server):
    context = browser.new_context(viewport={"width": 393, "height": 852}, has_touch=True, is_mobile=True)
    page = context.new_page()
    page.goto(f"{live_server}/?lang=en#trends?range=7d", wait_until="networkidle")
    expect(page.locator("#chart-ds-power .u-over")).to_be_visible()
    page.locator("#chart-ds-power").scroll_into_view_if_needed()
    cdp = context.new_cdp_session(page)
    yield page, cdp
    context.close()


def _touch(cdp, kind, x=None, y=None):
    points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


def _plot(page):
    box = page.locator("#chart-ds-power .u-over").bounding_box()
    return box["x"], box["y"] + box["height"] / 2, box["width"]


def test_holding_a_finger_reads_values_and_sliding_follows_it(phone):
    page, cdp = phone
    x, y, width = _plot(page)
    tooltip = page.locator("#chart-ds-power .uplot-tooltip")
    scroll = page.evaluate("scrollY")

    _touch(cdp, "touchStart", x + width * 0.25, y)
    page.wait_for_timeout(500)
    expect(tooltip).to_be_visible()
    first = tooltip.locator(".uplot-tooltip-time").inner_text()

    for step in range(1, 6):
        _touch(cdp, "touchMove", x + width * (0.25 + step * 0.1), y + step)
    expect(tooltip.locator(".uplot-tooltip-time")).not_to_have_text(first)
    # Sliding reads values instead of scrolling the page.
    assert page.evaluate("scrollY") == scroll
    _touch(cdp, "touchEnd")
    expect(page.locator("#chart-ds-power .u-over")).not_to_have_class("u-over is-scrubbing")


def test_a_quick_swipe_scrolls_the_page_without_a_tooltip(phone):
    page, cdp = phone
    x, y, width = _plot(page)
    scroll = page.evaluate("scrollY")

    _touch(cdp, "touchStart", x + width / 2, y)
    for step in range(1, 9):
        _touch(cdp, "touchMove", x + width / 2, y - step * 20)
    _touch(cdp, "touchEnd")
    page.wait_for_timeout(500)

    expect(page.locator("#chart-ds-power .uplot-tooltip")).to_be_hidden()
    assert page.evaluate("scrollY") > scroll


def test_the_tooltip_follows_the_theme(phone):
    page, cdp = phone
    x, y, width = _plot(page)
    _touch(cdp, "touchStart", x + width / 2, y)
    page.wait_for_timeout(500)
    tooltip = page.locator("#chart-ds-power .uplot-tooltip")
    expect(tooltip).to_be_visible()
    colors = tooltip.evaluate(
        """el => {
            const probe = document.createElement('div');
            probe.style.background = 'var(--elevated)';
            document.body.appendChild(probe);
            const expected = getComputedStyle(probe).backgroundColor;
            probe.remove();
            return [getComputedStyle(el).backgroundColor, expected];
        }"""
    )
    assert colors[0] == colors[1]
    _touch(cdp, "touchEnd")


def test_holding_a_finger_on_the_correlation_chart_reads_values(phone):
    page, cdp = phone
    page.goto(page.url.split("#", 1)[0] + "#correlation?range=7d", wait_until="networkidle")
    overlay = page.locator("#correlation-overlay")
    expect(overlay).to_be_visible()
    overlay.scroll_into_view_if_needed()
    box = overlay.bounding_box()
    _touch(cdp, "touchStart", box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.4)
    page.wait_for_timeout(500)
    expect(page.locator("#correlation-tooltip")).to_be_visible()
    _touch(cdp, "touchEnd")
