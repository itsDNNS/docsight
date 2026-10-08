"""The Connection Monitor chart on a time axis: pauses show, zoom labels what is in view."""

import re
import time

from playwright.sync_api import expect


def _samples():
    now = int(time.time()) // 60 * 60
    # One sample a minute, then the monitor was off for two hours, then on again.
    stamps = [now - 6 * 3600 + i * 60 for i in range(120)] + [now - 2 * 3600 + i * 60 for i in range(120)]
    return {
        "meta": {"resolution": "raw", "blended": False, "mixed": False, "tiers_used": ["raw"]},
        "samples": [{"timestamp": t, "latency_ms": 12.0 + (i % 5), "timeout": False,
                     "packet_loss_pct": 50.0 if i == 30 else 0.0} for i, t in enumerate(stamps)],
    }


def _open(page, base):
    data = _samples()
    page.route(re.compile(r".*/api/connection-monitor/samples/\d+\?.*"), lambda route: route.fulfill(json=data))
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{base}/?lang=en#connection-monitor?range=6h", wait_until="networkidle")
    expect(page.locator("#cm-combined-chart .u-over")).to_be_visible()
    return data


def test_a_pause_in_the_monitoring_breaks_the_line_on_a_time_axis(page, live_server):
    data = _open(page, live_server)
    chart = page.evaluate("""() => {
        const u = charts['cm-combined-chart'];
        return {x: Array.from(u.data[0]), original: u._docsightOriginal};
    }""")
    assert chart["original"].count(None) == 1
    gap = chart["original"].index(None)
    assert chart["x"][gap + 1] - chart["x"][gap - 1] > 3600
    assert chart["x"][0] == data["samples"][0]["timestamp"]


def test_zoom_labels_the_time_in_view_and_a_double_click_resets_it(page, live_server):
    _open(page, live_server)
    over = page.locator("#cm-combined-chart .u-over")
    box = over.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * 0.6, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.8, y, steps=8)
    page.mouse.up()
    expect(page.locator("#cm-combined-chart .chart-zoom-reset")).to_be_visible()

    zoomed = page.evaluate("""() => {
        const u = charts['cm-combined-chart'];
        return {min: u.scales.x.min, max: u.scales.x.max, splits: Array.from(u.axes[0]._splits || [])};
    }""")
    assert len(zoomed["splits"]) >= 2
    assert all(zoomed["min"] <= t <= zoomed["max"] for t in zoomed["splits"])

    over.dblclick()
    full = page.evaluate("""() => {
        const u = charts['cm-combined-chart'];
        return {min: u.scales.x.min, max: u.scales.x.max, first: u.data[0][0], last: u.data[0][u.data[0].length - 1]};
    }""")
    assert full["min"] <= full["first"] and full["max"] >= full["last"]
    assert full["max"] - full["min"] > zoomed["max"] - zoomed["min"]
