"""Clicking a chart point opens the snapshot taken at that time."""

import re

from playwright.sync_api import expect


def _open_trends(page, width=1440):
    page.set_viewport_size({"width": width, "height": 900})
    base = page.url.split("#", 1)[0].split("?", 1)[0]
    page.goto(base + "?lang=en#trends?range=7d", wait_until="networkidle")
    over = page.locator("#chart-ds-snr .u-over")
    expect(over).to_be_visible()
    over.evaluate("el => el.scrollIntoView({block: 'center'})")
    return over


def _click(page, over, fraction=0.5):
    box = over.bounding_box()
    page.mouse.click(box["x"] + box["width"] * fraction, box["y"] + box["height"] / 2)


def test_a_point_opens_its_snapshot_and_steps_through_neighbours(demo_page):
    page = demo_page
    over = _open_trends(page)
    _click(page, over, 0.3)

    panel = page.locator("#snapshot-panel")
    expect(panel).to_be_visible()
    title = page.locator("#snapshot-panel-title")
    expect(title).to_have_text(re.compile(r"^Snapshot · "))
    expect(title).to_be_focused()
    expect(page.locator("#snapshot-panel-sub")).to_contain_text("From DS SNR")
    expect(page.locator(".snapshot-kpi")).to_have_count(4)
    expect(page.locator(".snapshot-kpi").nth(3)).to_contain_text("New uncorrectable")
    expect(page.locator(".snapshot-channels tbody tr")).to_have_count(4)
    marked = page.evaluate("charts['chart-ds-snr']._docsightMarkedIdx")
    assert isinstance(marked, int)

    first = title.inner_text()
    page.locator("#snapshot-next").click()
    expect(title).not_to_have_text(first)
    # Stepping leaves the clicked point, so the chart no longer marks it.
    assert page.evaluate("charts['chart-ds-snr']._docsightMarkedIdx") is None
    page.locator("#snapshot-prev").click()
    expect(title).to_have_text(first)

    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()


def test_a_drag_does_not_open_a_snapshot(demo_page):
    page = demo_page
    over = _open_trends(page)
    box = over.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] / 2, steps=5)
    page.mouse.up()
    expect(page.locator("#snapshot-panel")).to_be_hidden()


def test_the_weakest_channel_opens_in_the_channel_timeline(demo_page):
    page = demo_page
    over = _open_trends(page)
    _click(page, over)
    button = page.locator("#snapshot-open-channel")
    expect(button).to_have_text(re.compile(r"^Open channel \d+$"))
    channel = button.get_attribute("data-channel")
    button.click()
    expect(page.locator("#snapshot-panel")).to_be_hidden()
    expect(page).to_have_url(re.compile(rf"#channels\?mode=timeline&dir=ds&channel={channel}&range=1d$"))


def test_copy_as_text_and_the_channel_timeline_point(demo_page):
    page = demo_page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    over = _open_trends(page)
    _click(page, over)
    page.locator("#snapshot-copy").click()
    text = page.evaluate("navigator.clipboard.readText()")
    assert text.startswith("Snapshot · ")
    assert "DS SNR:" in text and "New uncorrectable:" in text
    page.locator("#snapshot-close").click()

    page.goto(page.url.split("#", 1)[0] + "#channels?mode=timeline&dir=ds&range=1d", wait_until="networkidle")
    chart = page.locator("#chart-ch-power .u-over")
    expect(chart).to_be_visible()
    chart.evaluate("el => el.scrollIntoView({block: 'center'})")
    _click(page, chart)
    expect(page.locator("#snapshot-panel")).to_be_visible()
    expect(page.locator("#snapshot-panel-sub")).to_contain_text("From Power")


def test_the_panel_is_a_sheet_above_the_navigation_on_phones(demo_page):
    page = demo_page
    over = _open_trends(page, width=390)
    _click(page, over)
    panel = page.locator("#snapshot-panel").bounding_box()
    nav = page.locator(".topnav-nav").bounding_box()
    assert panel["x"] == 0 and panel["width"] == 390
    assert panel["y"] + panel["height"] <= nav["y"] + 1
    for button in ("#snapshot-prev", "#snapshot-next", "#snapshot-close"):
        box = page.locator(button).bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44
