"""E2E coverage for Connection Monitor workflows."""

import re
import time

import pytest
from playwright.sync_api import expect


def test_connection_monitor_uses_shared_page_header_action_layout(demo_page):
    """Connection Monitor range controls should live in the same top header pattern as other views."""
    page = demo_page
    page.evaluate("switchView('connection-monitor')")
    page.wait_for_selector("#view-connection-monitor.active", state="visible")

    header = page.locator("#view-connection-monitor .view-page-header")
    expect(header).to_be_visible()
    expect(header.locator(".view-page-title")).to_have_text("Connection Monitor")
    expect(header.locator(".view-page-actions #cm-range-tabs")).to_be_visible()
    expect(header.locator(".view-page-actions [data-cm-range='3600']")).to_be_visible()
    expect(header.locator(".view-page-actions #cm-capability-info")).to_be_visible()
    expect(page.locator("#view-connection-monitor .cm-control-strip")).to_have_count(0)


def test_connection_monitor_pin_day_action_does_not_shift_range_navigation(demo_page):
    """Showing the 1d-only pin action must not move the time-range navigation."""
    page = demo_page
    page.evaluate("switchView('connection-monitor')")
    page.wait_for_selector("#view-connection-monitor.active", state="visible")

    range_picker = page.locator("#view-connection-monitor .view-page-actions #cm-range-tabs")
    expect(range_picker).to_be_visible()
    before = range_picker.bounding_box()
    assert before is not None

    page.locator("#view-connection-monitor [data-cm-range='86400']").click()
    expect(page.locator("#cm-pin-day-btn")).to_be_visible()

    after = range_picker.bounding_box()
    assert after is not None
    assert abs(before["x"] - after["x"]) <= 1, "1d pin action should not shift the time-range controls horizontally"
    expect(page.locator("#view-connection-monitor #cm-range-tabs #cm-pin-day-btn")).to_have_count(0)


def _open_cm(page, width=1440, range_="7d"):
    page.set_viewport_size({"width": width, "height": 900 if width > 500 else 844})
    page.goto(page.url.split("#", 1)[0] + f"#connection-monitor?range={range_}", wait_until="networkidle")
    expect(page.locator("#cm-target-chips .cm-target-chip").first).to_be_visible()


def test_connection_monitor_downloads_live_in_the_more_menu(demo_page):
    """Raw ping logs and outage CSVs per target are one menu away instead of a page panel."""
    page = demo_page
    _open_cm(page)
    expect(page.locator("#cm-raw-log-panel")).to_have_count(0)
    targets = page.locator("#cm-target-chips .cm-target-chip").count()

    toggle = page.locator("#cm-more > summary")
    expect(toggle).to_have_attribute("aria-label", "More actions")
    menu = page.locator("#cm-more .cm-more-menu")
    expect(menu).to_be_hidden()
    toggle.click()
    expect(menu).to_be_visible()
    expect(menu).to_contain_text("Download raw log")
    expect(menu).to_contain_text("Export outages (CSV)")
    expect(page.locator("#cm-raw-log-links .cm-more-item")).to_have_count(targets)
    expect(page.locator("#cm-export-links .cm-more-item")).to_have_count(targets)

    with page.expect_download() as download:
        page.locator("#cm-raw-log-links .cm-more-item").first.click()
    assert "/api/connection-monitor/export/" in download.value.url
    assert "format=pinglog" in download.value.url
    expect(menu).to_be_hidden()

    toggle.click()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(toggle).to_be_focused()
    toggle.click()
    page.locator("#cm-target-chips").click(position={"x": 2, "y": 2})
    expect(menu).to_be_hidden()


def test_connection_monitor_target_chips_show_and_hide_lines(demo_page):
    """Each target is a chip with its line color and loss; pressing it hides the line and it stays hidden."""
    page = demo_page
    _open_cm(page)
    chips = page.locator("#cm-target-chips .cm-target-chip")
    first = chips.first
    expect(first).to_have_attribute("aria-pressed", "true")
    expect(first.locator(".cm-target-chip-loss")).to_contain_text("loss")
    expect(page.locator("#cm-combined-chart .u-legend")).to_have_count(0)
    target_id = first.get_attribute("data-target-id")
    series_shown = """id => {
        const chart = window.charts['cm-combined-chart'];
        const label = document.querySelector(`#cm-target-chips [data-target-id="${id}"] .cm-target-chip-name`).textContent;
        return chart.series.find(s => String(s.label).startsWith(label)).show;
    }"""
    assert page.evaluate(series_shown, target_id) is True

    first.click()
    expect(first).to_have_attribute("aria-pressed", "false")
    assert page.evaluate(series_shown, target_id) is False

    # A new range redraws the chart; the hidden target stays hidden.
    page.locator('#cm-range-tabs [data-cm-range="86400"]').click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(f'#cm-target-chips [data-target-id="{target_id}"]')).to_have_attribute("aria-pressed", "false")
    assert page.evaluate(series_shown, target_id) is False
    page.locator(f'#cm-target-chips [data-target-id="{target_id}"]').click()
    assert page.evaluate(series_shown, target_id) is True


def test_connection_monitor_mobile_keeps_chips_and_menu_above_the_chart(demo_page):
    """On phones the targets and the download menu are reachable before the long chart stack."""
    page = demo_page
    _open_cm(page, width=390)
    chips = page.locator("#cm-target-chips").bounding_box()
    toggle = page.locator("#cm-more > summary").bounding_box()
    chart = page.locator("#cm-charts-section").bounding_box()
    assert chips["y"] < chart["y"]
    assert toggle["y"] + toggle["height"] <= 844
    assert toggle["width"] >= 44 and toggle["height"] >= 44
    for box in page.locator("#cm-target-chips .cm-target-chip").evaluate_all("els => els.map(e => e.getBoundingClientRect().height)"):
        assert box >= 44
    page.locator("#cm-more > summary").click()
    menu = page.locator("#cm-more .cm-more-menu").bounding_box()
    assert menu["x"] >= 0 and menu["x"] + menu["width"] <= 390, menu
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


@pytest.mark.parametrize("width", [1440, 390])
def test_connection_monitor_keeps_observations_per_target_without_fault_inference(demo_page, width):
    page = demo_page
    page.set_viewport_size({"width": width, "height": 900})
    now = time.time()
    targets = [
        {"id": 1, "enabled": True, "label": "Local probe", "host": "10.0.0.10"},
        {"id": 2, "enabled": True, "label": "Public probe", "host": "example.net"},
    ]
    page.route("**/api/connection-monitor/targets", lambda route: route.fulfill(json=targets))
    page.route("**/api/connection-monitor/samples/1?**", lambda route: route.fulfill(json={"samples": [], "meta": {"resolution": "raw"}}))
    page.route("**/api/connection-monitor/samples/2?**", lambda route: route.fulfill(json={
        "samples": [
            {"timestamp": now - 10, "latency_ms": 10, "packet_loss_pct": 0, "sample_count": 1},
            {"timestamp": now - 5, "latency_ms": None, "packet_loss_pct": 100, "sample_count": 1},
            {"timestamp": now, "latency_ms": 30, "packet_loss_pct": 0, "sample_count": 1},
        ],
        "meta": {"resolution": "raw"},
    }))
    page.route("**/api/connection-monitor/stats?**", lambda route: route.fulfill(json={
        "1": {"sample_count": 0, "avg_latency_ms": None, "p95_latency_ms": None, "packet_loss_pct": None},
        "2": {"sample_count": 120, "avg_latency_ms": 21.5, "p95_latency_ms": 48, "packet_loss_pct": 5},
    }))
    page.route("**/api/connection-monitor/outages/*?**", lambda route: route.fulfill(json=[]))
    page.reload(wait_until="networkidle")
    page.evaluate("switchView('connection-monitor')")

    rows = page.locator('#cm-per-target-stats tbody tr')
    expect(rows).to_have_count(2)
    expect(rows.nth(0).locator('td')).to_have_text(['Local probe(10.0.0.10)', '-', '-', '-', '0'])
    expect(rows.nth(1).locator('td')).to_have_text(['Public probe(example.net)', '21.5 ms', '48.0 ms', '5.00%', '120'])
    expect(page.locator('#cm-combined-chart .uplot')).to_be_visible()
    expect(page.locator('#cm-export-links .cm-more-item')).to_have_count(2)
    expect(page.locator('#cm-raw-log-links .cm-more-item')).to_have_count(2)
    chips = page.locator('#cm-target-chips .cm-target-chip')
    expect(chips).to_have_count(2)
    expect(chips.nth(0)).to_contain_text('Local probe')
    expect(chips.nth(1)).to_contain_text('21.5 ms')
    expect(chips.nth(1).locator('.cm-target-chip-loss')).to_have_class(re.compile(r'is-crit'))
    expect(page.locator('.cm-diagnosis, #cm-stats-cards, #cm-availability')).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')


def test_connection_monitor_reset_zoom_follows_the_theme(demo_page):
    """The reset button after a drag-zoom uses the shared chart style instead of fixed dark colors."""
    page = demo_page
    page.goto(page.url.split("#", 1)[0] + "#connection-monitor?range=7d", wait_until="networkidle")
    over = page.locator("#cm-combined-chart .u-over")
    expect(over).to_be_visible()
    box = over.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()

    reset = page.locator("#cm-combined-chart .chart-zoom-reset")
    expect(reset).to_be_visible()
    colors = reset.evaluate(
        """el => {
            const probe = document.createElement('div');
            probe.style.background = 'var(--accent)';
            document.body.appendChild(probe);
            const accent = getComputedStyle(probe).backgroundColor;
            probe.remove();
            return [getComputedStyle(el).backgroundColor, accent];
        }"""
    )
    assert colors[0] == colors[1]
    reset.click()
    expect(reset).to_be_hidden()
