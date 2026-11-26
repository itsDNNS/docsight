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


def _open_cm(page, width=1440, range_="7d", query=""):
    page.set_viewport_size({"width": width, "height": 900 if width > 500 else 844})
    page.goto(page.url.split("#", 1)[0] + f"{query}#connection-monitor?range={range_}", wait_until="networkidle")
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
    page.evaluate("window.previousCmChart = window.charts['cm-combined-chart']")
    page.locator('#cm-range-tabs [data-cm-range="86400"]').click()
    page.wait_for_function("() => window.charts['cm-combined-chart'] !== window.previousCmChart")
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


@pytest.mark.parametrize("duration_format", ["native", "fallback"])
def test_connection_monitor_outage_durations_are_whole_units(demo_page, duration_format):
    """Outage durations arrive with one decimal and must not leak float noise into the log."""
    page = demo_page
    if duration_format == "fallback":
        page.add_init_script("delete Intl.DurationFormat")
    now = time.time()
    page.route("**/api/connection-monitor/targets", lambda route: route.fulfill(json=[
        {"id": 1, "enabled": True, "label": "Probe", "host": "example.net"},
    ]))
    page.route("**/api/connection-monitor/samples/1?**", lambda route: route.fulfill(json={
        "samples": [{"timestamp": now, "latency_ms": 12, "packet_loss_pct": 0, "sample_count": 1}],
        "meta": {"resolution": "raw"},
    }))
    page.route("**/api/connection-monitor/stats?**", lambda route: route.fulfill(json={}))
    page.route("**/api/connection-monitor/outages/1?**", lambda route: route.fulfill(json=[
        {"start": now - 9000, "end": now - 5280, "duration_seconds": 3720.0},
        {"start": now - 3000, "end": now - 2874.7, "duration_seconds": 125.3},
        {"start": now - 600, "end": now - 557.4, "duration_seconds": 42.6},
    ]))
    page.reload(wait_until="networkidle")
    page.evaluate("switchView('connection-monitor')")

    durations = page.locator("#cm-outage-table tbody td.dt-num")
    expect(durations).to_have_text(["43s", "2m 5s", "1h 2m"])


def test_connection_monitor_tcp_hint_is_keyboard_reachable(demo_page):
    """The TCP mode hint is added after load and must still become a focusable toggletip."""
    page = demo_page
    page.route("**/api/connection-monitor/capability", lambda route: route.fulfill(json={"method": "tcp"}))
    page.reload(wait_until="networkidle")
    page.evaluate("switchView('connection-monitor')")

    hint = page.locator("#cm-capability-info .glossary-hint")
    expect(hint).to_have_attribute("tabindex", "0")
    expect(hint).to_have_attribute("role", "button")


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


@pytest.mark.parametrize("reached,status", [(True, "Ziel erreicht"), (False, "Ziel nicht erreicht")])
def test_connection_monitor_traceroute_result_and_triggers_follow_the_language(demo_page, reached, status):
    """The traceroute banner and the trigger column use the page language instead of English or raw values."""
    page = demo_page
    page.route(re.compile(r".*/api/connection-monitor/traceroute/\d+$"), lambda route: route.fulfill(
        json={"reached_target": reached, "hop_count": 5, "route_fingerprint": "0123456789abcdef"}))
    _open_cm(page, query="?lang=de")
    page.locator("#cm-traceroute-target-select").get_by_role("button", name="Cloudflare DNS").click()
    expect(page.locator("#cm-traceroute-tbody td:last-child")).to_have_text(["Manuell", "Paketverlust", "Ausfall"])
    page.locator("#cm-traceroute-btn").click()
    expect(page.locator("#cm-traceroute-result")).to_have_text(f"{status} \u2014 5 Hops, Fingerabdruck: 0123456789ab")


def _fail(route):
    route.fulfill(status=500, body="down")


def _handled(page, matches, action):
    """Run action and return once the page has handled the answer to the request it sends or releases."""
    with page.expect_event("requestfinished", matches):
        action()
    page.evaluate("() => new Promise(resolve => setTimeout(resolve))")


def _answer_late(page, route, **reply):
    """Answer a held request and return once the page has handled the answer."""
    _handled(page, lambda request: request is route.request, lambda: route.fulfill(**reply))


@pytest.mark.parametrize("api", ["samples", "stats", "outages"])
def test_connection_monitor_failed_load_replaces_the_previous_range_with_a_retry(demo_page, api):
    """A failed load after a range change must not leave the previous range on screen as if it were current."""
    page = demo_page
    _open_cm(page)
    pattern = re.compile(rf".*/api/connection-monitor/{api}\b.*")
    page.route(pattern, _fail)
    page.locator('#cm-range-tabs [data-cm-range="86400"]').click()

    empty = page.locator("#cm-no-data")
    expect(empty.locator(".view-empty-title")).to_have_text("Could not load the data")
    for stale in ("#cm-charts-section", "#cm-target-chips", "#cm-outage-panel"):
        expect(page.locator(stale)).to_be_hidden()
    page.unroute(pattern)
    empty.locator(".view-empty-action").click()
    expect(empty).to_be_hidden()
    expect(page.locator("#cm-target-chips .cm-target-chip").first).to_be_visible()


def test_connection_monitor_trace_requests_report_failures(demo_page):
    """Trace history, trace details and a manual run say that their request failed."""
    page = demo_page
    page.route("**/api/connection-monitor/traces/*", _fail)
    page.reload()
    _open_cm(page)
    expect(page.locator("#cm-traceroute-tbody tr")).to_have_text(["Network error"])

    page.unroute("**/api/connection-monitor/traces/*")
    page.locator("#cm-traceroute-target-select .cm-chip-btn", has_text="Cloudflare DNS").click()
    toggle = page.locator("#cm-traceroute-tbody .cm-trace-toggle").first
    page.route("**/api/connection-monitor/trace/*", _fail)
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#cm-traceroute-tbody .trace-detail-row")).to_have_text("Network error")

    page.route("**/api/connection-monitor/traceroute/*", _fail)
    page.locator("#cm-traceroute-btn").click()
    expect(page.locator("#cm-traceroute-result")).to_have_text("Network error")
    expect(page.locator("#cm-traceroute-btn")).to_be_enabled()


def test_connection_monitor_settings_report_failed_target_requests(page, live_server):
    """A failed target load is not shown as an empty list, and a failed removal keeps the row with a message."""
    page.route("**/api/connection-monitor/targets", _fail)
    page.goto(f"{live_server}/settings#mod-docsight_connection_monitor", wait_until="networkidle")
    error = page.locator("#cm-targets-error")
    expect(error).to_contain_text("Network error")
    rows = page.locator("#cm-targets-list [data-target-id]")
    expect(rows).to_have_count(0)

    page.unroute("**/api/connection-monitor/targets")
    error.get_by_role("button", name="Try again").click()
    expect(error).to_be_hidden()
    expect(rows.first).to_be_visible()
    count = rows.count()

    page.route("**/api/connection-monitor/targets/*", _fail)
    rows.first.get_by_role("button", name="Remove").click()
    expect(error).to_contain_text("Network error")
    expect(rows).to_have_count(count)


def test_connection_monitor_trace_history_keeps_the_last_chosen_target(demo_page):
    """A late history answer for an earlier target must not replace the target chosen after it."""
    page = demo_page
    _open_cm(page)
    held = []
    page.route("**/api/connection-monitor/traces/*", lambda route: route.fallback() if held else held.append(route))
    chips = page.locator("#cm-traceroute-target-select .cm-chip-btn")
    chips.filter(has_text="Cloudflare DNS").click()
    chips.filter(has_text="Google DNS").click()
    rows = page.locator("#cm-traceroute-tbody .cm-trace-row")
    expect(rows.first).to_be_visible()
    count = rows.count()

    _answer_late(page, held[0], json=[])
    expect(rows).to_have_count(count)


def test_connection_monitor_keeps_the_target_error_until_targets_load(demo_page):
    """A range change after a failed target load tries the targets again instead of claiming there are none."""
    page = demo_page
    page.route("**/api/connection-monitor/targets", _fail)
    page.reload()
    page.evaluate("switchView('connection-monitor')")
    title = page.locator("#cm-no-data .view-empty-title")
    expect(title).to_have_text("Could not load the data")

    with page.expect_response("**/api/connection-monitor/targets", timeout=5000):
        page.locator('#cm-range-tabs [data-cm-range="86400"]').click()
    expect(title).to_have_text("Could not load the data")


def test_connection_monitor_settings_list_shows_only_the_latest_load(page, live_server):
    """Adding a target reloads the list, and a late answer of an older list load cannot replace a newer one."""
    held = []

    def targets(route):
        if route.request.method == "POST":
            route.fulfill(status=201, json={"id": 999})
        elif held:
            _fail(route)
        else:
            held.append(route)

    page.route("**/api/connection-monitor/targets", targets)
    page.goto(f"{live_server}/settings#mod-docsight_connection_monitor")
    page.locator("#cm-add-target-btn").click()
    retry = page.locator("#cm-targets-error").get_by_role("button", name="Try again")
    expect(retry).to_be_visible()

    _answer_late(page, held[0], json=[{"id": 1, "label": "Old", "host": "old.example"}])
    expect(retry).to_be_visible()
    expect(page.locator("#cm-targets-list [data-target-id]")).to_have_count(0)


def test_connection_monitor_manual_run_reports_http_errors_and_keeps_them_visible(demo_page):
    """A JSON error answer is a failed run, server refusals keep their text, and an older result timer hides nothing."""
    page = demo_page
    page.clock.install()
    page.reload()
    _open_cm(page)
    runs = [
        {"json": {"reached_target": True, "hop_count": 3, "route_fingerprint": "0123456789ab"}},
        {"status": 503, "json": {"message": "busy"}},
        {"status": 404, "json": {"error": "Target not found"}},
    ]
    page.route("**/api/connection-monitor/traceroute/*", lambda route: route.fulfill(**runs.pop(0)))
    history = []
    page.on("request", lambda request: history.append(request) if "/traces/" in request.url else None)
    result = page.locator("#cm-traceroute-result")
    button = page.locator("#cm-traceroute-btn")

    with page.expect_request("**/api/connection-monitor/traces/*"):
        button.click()
    expect(result).to_contain_text("Target reached")
    loads = len(history)
    page.clock.run_for(5000)
    button.click()
    expect(result).to_have_text("Network error")
    page.clock.run_for(5000)
    expect(result).to_be_visible()
    assert len(history) == loads

    button.click()
    expect(result).to_have_text("Target not found")


def test_connection_monitor_late_target_answer_keeps_the_chosen_trace_target(demo_page):
    """An older target list answer must not rebuild the traceroute targets after a newer one."""
    page = demo_page
    held = []
    page.route("**/api/connection-monitor/targets", lambda route: route.fallback() if held else held.append(route))
    page.reload()
    page.evaluate("switchView('connection-monitor')")
    page.locator('#cm-range-tabs [data-cm-range="86400"]').click()
    chosen = page.locator("#cm-traceroute-target-select .cm-chip-btn", has_text="Cloudflare DNS")
    chosen.click()

    _answer_late(page, held[0], json=[{"id": 99, "enabled": True, "label": "Late", "host": "late.example"}])
    expect(chosen).to_have_class(re.compile(r"\bactive\b"))


def test_connection_monitor_settings_keep_the_list_retry_only_while_the_list_is_stale(page, live_server):
    """A failed add keeps "Try again" while the list may be stale; a list load that succeeds removes it."""
    gets = []

    def targets(route):
        if route.request.method == "GET":
            gets.append(route)
        if route.request.method == "POST" or len(gets) == 1:
            _fail(route)

    page.route("**/api/connection-monitor/targets", targets)
    page.goto(f"{live_server}/settings#mod-docsight_connection_monitor")
    error = page.locator("#cm-targets-error")
    retry = error.get_by_role("button", name="Try again")
    retry.click()

    _handled(page, lambda request: request.method == "POST", page.locator("#cm-add-target-btn").click)
    expect(retry).to_be_visible()
    _answer_late(page, gets[1], json=[])
    expect(retry).to_have_count(0)
    expect(error).to_have_text("Network error")
