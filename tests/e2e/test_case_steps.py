"""Inside a case: window, evidence and export as three steps, with the action for each open item."""

import re

from playwright.sync_api import expect

CASES = [
    {"id": 7, "name": "Evening dropouts", "status": "open", "description": "", "icon": None,
     "start_date": "2026-10-01", "end_date": "2026-10-05", "entry_count": 0},
    {"id": 8, "name": "All collected", "status": "resolved", "description": "", "icon": None,
     "start_date": "2026-09-01", "end_date": "2026-09-03", "entry_count": 0},
    {"id": 9, "name": "No window yet", "status": "open", "description": "", "icon": None,
     "start_date": None, "end_date": None, "entry_count": 0},
]


def _item(key, status, action):
    return {"key": key, "status": status, "label_key": f"docsight.evidence.item.{key}.label", "action": action}


CHECKLISTS = {
    "7": [
        _item("signal", "stale", {"view": "correlation"}),
        _item("speedtest", "missing", {"view": "speedtest"}),
        _item("events", "present", {"view": "events"}),
        _item("journal", "missing", {"view": "journal", "action": "add_note"}),
        _item("comparison", "optional", {"view": "comparison"}),
        _item("bnetz", "not_applicable", {"view": "bnetz"}),
        _item("report", "present", {"action": "report"}),
    ],
    "8": [
        _item("signal", "present", {"view": "correlation"}),
        _item("events", "present", {"view": "events"}),
        _item("report", "present", {"action": "report"}),
    ],
}


def _serve(page):
    page.route(re.compile(r".*/api/incidents$"), lambda route: route.fulfill(json=CASES))
    page.route(
        re.compile(r".*/api/incidents/\d+/timeline$"),
        lambda route: route.fulfill(json={
            "incident": next(c for c in CASES if str(c["id"]) == route.request.url.rsplit("/", 2)[1]),
            "entries": [], "timeline": [], "bnetz": [],
        }),
    )
    page.route(
        re.compile(r".*/api/evidence/checklist\?incident_id=\d+$"),
        lambda route: route.fulfill(json={"summary": {}, "items": CHECKLISTS[route.request.url.rsplit("=", 1)[1]]}),
    )


def _open_case(page, incident_id):
    page.goto(page.url.split("#", 1)[0].split("?", 1)[0] + "?lang=en#journal", wait_until="networkidle")
    expect(page.locator("#case-cards .case-card")).to_have_count(3)
    page.evaluate("id => openIncidentTimeline(id)", incident_id)
    expect(page.locator("#incident-timeline-steps")).to_be_visible()


def test_open_evidence_is_the_current_step_and_offers_its_action(demo_page):
    page = demo_page
    _serve(page)
    _open_case(page, 7)

    steps = page.locator("#incident-timeline-steps .case-step")
    expect(steps.nth(0)).to_have_class(re.compile(r"case-step-done"))
    expect(steps.nth(0)).to_contain_text("Window · ")
    # The report item is the export step, so it is not counted as evidence.
    expect(steps.nth(1)).to_contain_text("Evidence · 1 of 4 ready")
    expect(steps.nth(1)).to_have_attribute("aria-current", "step")
    expect(steps.nth(2)).to_have_class(re.compile(r"case-step-later"))

    expect(page.locator(".case-evidence-details")).to_have_attribute("open", "")
    rows = page.locator(".case-evidence-item")
    expect(rows).to_have_count(5)
    expect(rows.nth(0)).to_contain_text("Stale")
    expect(rows.nth(2).get_by_role("button")).to_have_count(0)

    rows.nth(3).get_by_role("button", name="Add note").click()
    expect(page.locator("#entry-modal")).to_be_visible()
    expect(page.locator("#entry-incident-select")).to_have_value("7")
    page.keyboard.press("Escape")

    page.get_by_role("link", name="Open the full evidence checklist").click()
    expect(page.locator("#view-evidence")).to_be_visible()
    expect(page).to_have_url(re.compile(r"#evidence\?case=7$"))
    expect(page.locator("#evidence-incident-id")).to_have_value("7")
    page.go_back()
    page.evaluate("id => openIncidentTimeline(id)", 7)

    page.locator(".case-evidence-item").nth(0).get_by_role("button", name="Review correlation").click()
    expect(page.locator("#view-correlation")).to_be_visible()


def test_a_case_with_all_evidence_moves_on_to_export(demo_page):
    page = demo_page
    _serve(page)
    _open_case(page, 8)

    steps = page.locator("#incident-timeline-steps .case-step")
    expect(steps.nth(1)).to_contain_text("Evidence · 2 of 2 ready")
    expect(steps.nth(2)).to_have_attribute("aria-current", "step")
    expect(page.locator(".case-evidence-details")).not_to_have_attribute("open", "")
    expect(page.locator(".case-evidence-item").first).to_be_hidden()


def test_a_case_without_window_asks_for_one_first(demo_page):
    page = demo_page
    _serve(page)
    _open_case(page, 9)

    steps = page.locator("#incident-timeline-steps .case-step")
    expect(steps.nth(0)).to_contain_text("Window · not set yet")
    expect(steps.nth(0)).to_have_attribute("aria-current", "step")
    page.locator("#incident-timeline-steps").get_by_role("button", name="Set window").click()
    expect(page.locator("#incident-container-modal")).to_be_visible()
    expect(page.locator("#incident-container-start")).to_be_visible()

    page.locator("#incident-container-modal").get_by_role("button", name=re.compile("Cancel|Close")).first.click()
    page.locator(".incident-timeline-back").click()
    expect(page.locator("#incident-timeline-steps")).to_be_hidden()


def test_without_the_evidence_module_the_window_leads_straight_to_export(demo_page):
    page = demo_page
    _serve(page)
    page.goto(page.url.split("#", 1)[0].split("?", 1)[0] + "?lang=en#journal", wait_until="networkidle")
    expect(page.locator("#case-cards .case-card")).to_have_count(3)
    page.evaluate("document.getElementById('view-evidence').remove()")
    page.evaluate("id => openIncidentTimeline(id)", 7)

    steps = page.locator("#incident-timeline-steps .case-step")
    expect(steps).to_have_count(2)
    expect(steps.nth(1)).to_contain_text("Export")
    expect(steps.nth(1)).to_have_attribute("aria-current", "step")
    expect(page.locator(".case-evidence-details")).to_have_count(0)
