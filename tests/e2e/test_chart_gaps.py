"""A pause in the polls stays visible: the line breaks and the gap is marked."""

import re
from datetime import datetime, timedelta

from playwright.sync_api import expect


def _rows():
    start = datetime(2026, 10, 7, 6, 0)
    rows = []
    # 15-minute polls, then nothing for six hours, then polls again.
    for block_start, count in ((start, 24), (start + timedelta(hours=12), 24)):
        for i in range(count):
            ts = block_start + timedelta(minutes=15 * i)
            rows.append({"timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"), "ds_power_avg": 4.5, "ds_snr_avg": 37.0,
                         "us_power_avg": 44.0, "ds_uncorrectable_errors": 100 + i})
    return rows


def _open(page, requested=None):
    page.route(re.compile(r".*/api/trends\?range=1d.*"), lambda route: route.fulfill(json=_rows()))
    if requested is not None:
        def snapshot(route):
            requested.append(route.request.url)
            route.fulfill(status=404, json={"error": "not found"})
        page.route(re.compile(r".*/api/snapshots/at\?.*"), snapshot)
    base = page.url.split("#", 1)[0].split("?", 1)[0]
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base + "?lang=en#trends?range=1d", wait_until="networkidle")
    expect(page.locator("#chart-ds-power .u-over")).to_be_visible()


def test_the_line_breaks_at_a_pause_and_the_points_keep_their_time(demo_page):
    page = demo_page
    _open(page)
    chart = page.evaluate("""() => {
        const u = charts['chart-ds-power'];
        return {x: Array.from(u.data[0]), y: Array.from(u.data[1]), original: u._docsightOriginal};
    }""")
    assert chart["original"].count(None) == 1
    gap = chart["original"].index(None)
    assert chart["y"][gap] is None
    # Before the gap the points are 15 minutes apart; across it, six hours and more.
    assert chart["x"][1] - chart["x"][0] == 900
    assert chart["x"][gap + 1] - chart["x"][gap - 1] > 6 * 3600
    # All four Trends charts share the time axis, so the crosshair stays in sync.
    for chart_id in ("chart-ds-snr", "chart-us-power"):
        assert page.evaluate(f"charts['{chart_id}'].data[0].length") == len(chart["x"])


def test_a_click_after_the_gap_opens_the_snapshot_of_that_time(demo_page):
    page = demo_page
    requested = []
    _open(page, requested)
    over = page.locator("#chart-ds-power .u-over")
    over.evaluate("el => el.scrollIntoView({block: 'center'})")
    box = over.bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.9, box["y"] + box["height"] / 2)
    expect(page.locator("#snapshot-panel")).to_be_visible()
    page.wait_for_timeout(300)
    assert requested, "no snapshot request"
    time = re.search(r"time=([^&]+)", requested[-1]).group(1).replace("%3A", ":")
    # The click lands on the second stretch of polls, which starts at 18:00.
    assert time >= "2026-10-07T18:00:00", time
