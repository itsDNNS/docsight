"""Module ownership, routing and dialog behavior in the browser."""

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import _new_target
from tests.e2e.support.lifecycle import running_processes
from tests.e2e.support.profiles import ServerProfile


@pytest.fixture
def root_module_servers(tmp_path_factory):
    """Keep the three delivery states in the root journey only."""
    targets, specs = {}, []
    for state in ("configured", "unconfigured", "disabled"):
        profile = ServerProfile(
            "module-views-" + state, configured=True,
            demo_mode=state != "unconfigured",
            disabled_modules="docsight.journal,docsight.bqm,docsight.speedtest" if state == "disabled" else "",
        )
        target, spec = _new_target("module-views-" + state,
                                   tmp_path_factory.mktemp("module-views-" + state), profile)
        targets[state] = target.base_url
        specs.append(spec)
    with running_processes(specs):
        yield targets


@pytest.fixture
def prefixed_module_server(tmp_path_factory):
    profile = ServerProfile(
        "module-views-docsight", configured=True, demo_mode=True,
        mount_path="/docsight",
    )
    target, spec = _new_target(
        "module-views-docsight",
        tmp_path_factory.mktemp("module-views-docsight"), profile,
    )
    with running_processes([spec]):
        yield target.base_url


def test_root_module_views_settings_disabled_actions_and_mobile_setup(page, root_module_servers):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    base = root_module_servers["configured"]
    for view in ("journal", "bqm", "speedtest"):
        page.goto(base + "/#" + view)
        expect(page.locator("#view-" + view)).to_be_visible()
        page.evaluate("view => { switchView('live'); switchView(view); switchView(view); }", view)
        expect(page.locator("#view-" + view)).to_be_visible()
        expect(page.locator(".main-content > .view.active")).to_have_count(1)
    page.goto(base + "/settings")
    page.wait_for_load_state("networkidle")
    for view in ("journal", "bqm", "speedtest"):
        expect(page.locator(f'script[src*="/modules/docsight.{view}/static/main.js?v="]')).to_have_count(1)

    base = root_module_servers["disabled"]
    page.goto(base + "/#journal")
    expect(page.locator("#view-dashboard")).to_be_visible()
    expect(page.locator(".main-content > .view.active")).to_have_count(1)
    expect(page).to_have_url(base + "/")
    for view in ("journal", "bqm", "speedtest", "unknown"):
        expect(page.locator("#view-" + view)).to_have_count(0)
        expect(page.locator(f'.nav-item[data-view="{view}"]')).to_have_count(0)
        expect(page.locator(f'.nav-item[onclick="open{view.title()}SetupModal()"]')).to_have_count(0)
        expect(page.locator(f'script[src*="/modules/docsight.{view}/static/main.js"]')).to_have_count(0)
    for view in ("bqm", "speedtest", "unknown"):
        page.evaluate("view => switchView(view)", view)
        expect(page.locator("#view-dashboard")).to_be_visible()
        expect(page.locator(".main-content > .view.active")).to_have_count(1)
        expect(page).to_have_url(base + "/")
    page.evaluate("switchView('evidence')")
    page.evaluate(
        """
        _evidenceRenderItems(['journal', 'bqm', 'speedtest'].map((key) => ({
            key: key,
            status: 'unavailable',
            hint_key: 'missing',
            action: key === 'journal' ? {view: 'journal', action: 'add_note'} : {view: key}
        })))
        """
    )
    expect(page.locator("#evidence-items .evidence-item").first).to_be_visible()
    expect(page.locator('[data-evidence-view="journal"], [data-evidence-view="bqm"], [data-evidence-view="speedtest"]')).to_have_count(0)
    expect(page.locator('[data-evidence-action="add_note"]')).to_have_count(0)

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(root_module_servers["unconfigured"])
    sidebar = page.locator("#sidebar")
    for view, hook in (("bqm", "Bqm"), ("speedtest", "Speedtest")):
        expect(page.locator("#view-" + view)).to_have_count(0)
        page.locator("#hamburger").click()
        expect(sidebar).to_have_attribute("aria-hidden", "false")
        trigger = page.locator(f'.nav-item[onclick="open{hook}SetupModal()"]')
        expect(trigger).to_be_visible()
        trigger.focus()
        expect(trigger).to_be_focused()
        trigger.press("Enter")
        dialog = page.locator(f"#{view}-setup-modal")
        expect(dialog).to_be_visible()
        close_button = dialog.locator(".modal-close")
        close_button.focus()
        expect(close_button).to_be_focused()
        close_button.press("Enter")
        expect(dialog).not_to_be_visible()
        page.evaluate("closeSidebar()")
        expect(sidebar).to_have_attribute("aria-hidden", "true")
    assert errors == []


def test_prefixed_module_hash_navigation_and_script_urls(page, prefixed_module_server):
    """Leave other delivery states to the root journey and Python ownership tests."""
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    base = prefixed_module_server
    page.goto(base + "/#journal")
    expect(page.locator("#view-journal")).to_be_visible()
    expect(page.locator(".main-content > .view.active")).to_have_count(1)
    expect(page).to_have_url(base + "/#journal")
    for view in ("journal", "bqm", "speedtest"):
        expect(page.locator(f'script[src^="/docsight/modules/docsight.{view}/static/main.js?v="]')).to_have_count(1)
    for view in ("live", "bqm", "speedtest", "journal"):
        page.locator(f'.nav-item[data-view="{view}"]').click()
        view_id = "dashboard" if view == "live" else view
        expect(page.locator("#view-" + view_id)).to_be_visible()
        expect(page.locator(".main-content > .view.active")).to_have_count(1)
        expected_hash = "#" if view == "live" else "#" + view
        expect(page).to_have_url(base + "/" + expected_hash)
        assert errors == []
    assert errors == []


@pytest.mark.parametrize("theme,width", [("light", 1280), ("dark", 1280), ("light", 390), ("dark", 390)])
@pytest.mark.parametrize("has_png", [False, True], ids=["csv-only", "csv-and-png"])
def test_bqm_quick_selection_and_sparse_range_axes(page, live_server, theme, width, has_png):
    """Real controls and uPlot callbacks retain the selected view with sparse CSV data."""
    from datetime import datetime, timezone
    from io import BytesIO

    from PIL import Image

    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.clock.install(time=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))
    page.set_viewport_size({"width": width, "height": 844})
    dates = ["2026-06-15", "2026-06-14", "2026-06-12"]
    page.route("**/api/bqm/data/dates", lambda route: route.fulfill(json={
        "csv_dates": dates, "png_dates": dates if has_png else [],
    }))
    png = BytesIO()
    Image.new("RGB", (64, 32), "blue").save(png, format="PNG")
    page.route("**/api/bqm/image/2026-*", lambda route: route.fulfill(
        content_type="image/png", body=png.getvalue(),
    ))
    # Both multi-day selections deliberately contain only a single day's samples.
    payload = {"points": 2, "data": {
        "timestamps": ["2026-06-15T12:00:00", "2026-06-15T12:05:00"],
        "latency_avg": [10, 11], "latency_min": [8, 9], "latency_max": [12, 13],
        "lost_polls": [0, 1], "sent_polls": [100, 100],
    }}
    page.route("**/api/bqm/data/range?*", lambda route: route.fulfill(json=payload))
    page.route("**/api/bqm/data/2026-*", lambda route: route.fulfill(json=payload))
    page.goto(live_server + "/#bqm")
    page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
    expect(page.locator("#bqm-today-btn")).to_have_attribute("aria-pressed", "true")
    page.locator("#bqm-today-btn").click()
    page.wait_for_function("() => !!charts['bqm-chart-container']")
    page.wait_for_load_state("networkidle")

    def selection(name):
        for key in ("today", "yesterday", "7d", "30d"):
            button = page.locator(f"#bqm-{key}-btn")
            expect(button).to_have_attribute("aria-pressed", str(key == name).lower())
            assert button.evaluate("el => el.classList.contains('active')") == (key == name)
        if name:
            active = page.locator(f"#bqm-{name}-btn")
            inactive = page.locator(".bqm-quick:not(.active)").first
            assert active.evaluate("el => getComputedStyle(el).backgroundColor") != inactive.evaluate(
                "el => getComputedStyle(el).backgroundColor")

    def click_chart(selector, modifiers=None):
        page.evaluate("window.previousBqmChart = charts['bqm-chart-container']")
        page.locator(selector).click(modifiers=modifiers or [])
        page.wait_for_function("() => charts['bqm-chart-container'] !== window.previousBqmChart")

    def axis(dates_mode):
        values = page.evaluate("""() => {
            const chart = charts['bqm-chart-container'];
            return chart.axes[0].values(chart, chart.data[0]);
        }""")
        assert values == (["06-15", "06-15"] if dates_mode else ["12:00", "12:05"])
        expect(page.locator("#bqm-chart-container .uplot canvas").first).to_be_visible()

    selection("today")
    for name in ("today", "yesterday", "7d", "30d"):
        if name == "yesterday":
            page.evaluate("startBqmLiveRefresh()")
        click_chart(f"#bqm-{name}-btn")
        selection(name)
        axis(name in ("7d", "30d"))
        if name in ("today", "yesterday"):
            date = dates[0] if name == "today" else dates[1]
            assert page.evaluate("[_bqmRangeStart, _bqmRangeEnd]") == [date, date]
            assert page.evaluate("_bqmLiveTimer === null")
            if has_png:
                expect(page.locator("#bqm-view-toggle")).to_be_visible()
                page.locator("#bqm-toggle-png").click()
                image = page.locator("#bqm-image")
                expect(image).to_be_visible()
                expect(image).to_have_attribute("src", "/api/bqm/image/" + date)
                page.wait_for_function("() => document.getElementById('bqm-image').naturalWidth === 64")
                assert page.evaluate("!charts['bqm-chart-container']")
                click_chart("#bqm-toggle-uplot")
                axis(False)
            else:
                expect(page.locator("#bqm-view-toggle")).not_to_be_visible()
        else:
            expect(page.locator("#bqm-view-toggle")).not_to_be_visible()
    page.locator("#bqm-month-prev").click()
    selection("30d")
    page.locator("#bqm-month-next").click()
    click_chart('.bqm-day[data-date="2026-06-12"]')
    selection(None)
    axis(False)
    click_chart('.bqm-day[data-date="2026-06-14"]', ["Shift"])
    selection(None)
    axis(True)
    click_chart("#bqm-yesterday-btn")
    selection("yesterday")
    axis(False)
    assert errors == []
