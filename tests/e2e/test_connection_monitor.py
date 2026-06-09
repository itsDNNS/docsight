"""E2E coverage for Connection Monitor workflows."""

from playwright.sync_api import expect


def test_connection_monitor_uses_shared_page_header_action_layout(demo_page):
    """Connection Monitor range controls should live in the same top header pattern as other views."""
    page = demo_page
    page.evaluate("switchView('connection-monitor')")
    page.wait_for_selector("#view-connection-monitor.active", state="visible")

    header = page.locator("#view-connection-monitor .view-page-header")
    expect(header).to_be_visible()
    expect(header.locator(".view-page-title")).to_have_text("Connection Monitor")
    expect(header.locator(".view-page-actions .cm-range-picker")).to_be_visible()
    expect(header.locator(".view-page-actions [data-cm-range='3600']")).to_be_visible()
    expect(header.locator(".view-page-actions #cm-capability-info")).to_be_visible()
    expect(page.locator("#view-connection-monitor .cm-control-strip")).to_have_count(0)


def test_connection_monitor_raw_ping_log_panel_is_discoverable(demo_page):
    """The Connection Monitor view should expose the ISP-ready raw ping log export panel."""
    page = demo_page
    page.evaluate("switchView('connection-monitor')")
    page.wait_for_selector("#view-connection-monitor.active", state="visible")

    panel = page.locator("#cm-raw-log-panel")
    expect(panel).to_be_visible()
    expect(panel.get_by_text("Raw Ping Log")).to_be_visible()
    expect(panel.get_by_text("Download per-ping raw samples")).to_be_visible()


def test_connection_monitor_mobile_surfaces_raw_ping_log_without_deep_scroll(demo_page):
    """Mobile users should see raw-log downloads before the long chart/details stack."""
    page = demo_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("switchView('connection-monitor')")
    page.wait_for_selector("#view-connection-monitor.active", state="visible")

    first_raw_log_button = page.locator("#cm-raw-log-links .cm-chip-btn").first
    expect(first_raw_log_button).to_be_visible()
    button_box = first_raw_log_button.bounding_box()
    chart_box = page.locator("#cm-charts-section").bounding_box()
    panel_box = page.locator("#cm-raw-log-panel").bounding_box()
    assert button_box is not None
    assert chart_box is not None
    assert panel_box is not None
    assert 0 <= panel_box["y"]
    assert 0 <= button_box["y"]
    assert panel_box["y"] < chart_box["y"], "raw log panel should appear before the long chart stack"
    assert button_box["y"] + button_box["height"] <= 844, "raw log download actions should be fully visible without deep mobile scrolling"
