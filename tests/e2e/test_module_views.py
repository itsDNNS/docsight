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
