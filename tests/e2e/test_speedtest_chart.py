"""Speedtest history chart: shared chart engine, readable time axis."""

import re

import pytest
from playwright.sync_api import expect

# Axis labels as drawn: left and right edge of each label in CSS pixels.
LABEL_BOXES = """() => {
    const u = charts['speedtest-chart'];
    const axis = u.axes[0];
    const ctx = document.createElement('canvas').getContext('2d');
    ctx.font = axis.font[0];
    return {font: axis.font[0], boxes: axis._splits.map((value, i) => {
        const x = u.bbox.left / devicePixelRatio + u.valToPos(value, 'x');
        const width = ctx.measureText(axis._values[i]).width;
        return [x - width / 2, x + width / 2];
    })};
}"""


def _open(page, base, rng):
    page.goto(f"{base}/#speedtest?range={rng}")
    page.wait_for_function("() => typeof charts !== 'undefined' && charts['speedtest-chart']")


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("rng", ["7", "30", "90"])
def test_axis_labels_keep_apart_and_use_the_chart_font(page, live_server, width, rng):
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, live_server, rng)
    result = page.evaluate(LABEL_BOXES)
    assert result["font"] == "12px system-ui"
    boxes = result["boxes"]
    assert boxes, "the time axis has labels"
    chart_width = page.evaluate("() => charts['speedtest-chart'].width")
    assert boxes[0][0] >= 0 and boxes[-1][1] <= chart_width, boxes
    for (_, right), (left, _) in zip(boxes, boxes[1:]):
        assert left - right >= 12, boxes


def test_tooltip_names_the_full_time_and_rows_keep_the_booked_limit(page, live_server):
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server, "30")
    # The axis shows dates only; the tooltip still names the time of the result.
    box = page.locator("#speedtest-chart .u-over").bounding_box()
    last_x = page.evaluate("() => { const u = charts['speedtest-chart']; return u.valToPos(u.data[0][u.data[0].length - 1], 'x'); }")
    page.mouse.move(box["x"] + last_x, box["y"] + box["height"] / 2)
    expect(page.locator("#speedtest-chart .uplot-tooltip-time")).to_have_text(re.compile(r"\d:\d\d"))
    # The booked speed moved from the replaced canvas to the container.
    assert page.evaluate("() => _speedtestBooked('download')") > 0


def test_speedtest_header_sorts_once_and_reports_the_order(demo_page, live_server):
    """Each header click sorts once; aria-sort names the column and direction actually shown."""
    page = demo_page
    _open(page, live_server, "all")
    expect(page.locator("#speedtest-tbody tr").first).to_be_visible()
    headers = page.locator("#speedtest-table th[aria-sort]")
    expect(headers).to_have_count(1)
    expect(page.locator("#speedtest-table th[data-col='timestamp']")).to_have_attribute("aria-sort", "descending")

    download = page.locator("#speedtest-table th[data-col='download_mbps']")
    download.click()
    expect(download).to_have_attribute("aria-sort", "ascending")
    expect(headers).to_have_count(1)
    first, second = page.locator("#speedtest-tbody tr .st-col-dl strong").evaluate_all(
        "els => els.slice(0, 2).map(e => parseFloat(e.textContent))"
    )
    assert first <= second
