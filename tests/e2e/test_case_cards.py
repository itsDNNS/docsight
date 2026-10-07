"""The case overview above the journal: one card per case with its evidence state."""

import re

from playwright.sync_api import expect

CASES = [
    {"id": 3, "name": "Resolved earlier", "status": "resolved", "start_date": "2026-09-01", "end_date": "2026-09-03", "entry_count": 1},
    {"id": 7, "name": "Evening dropouts", "status": "open", "start_date": "2026-10-01", "end_date": None, "entry_count": 3},
]


def _checklist(summary, items):
    return {"window": {"kind": "incident", "label": "x", "from": "2026-10-01T00:00:00Z", "to": "2026-10-07T00:00:00Z"},
            "summary": summary, "items": items, "capabilities": {}}


CHECKLISTS = {
    "3": _checklist({"present": 6, "stale": 0, "missing": 0}, [{"key": "signal", "status": "present", "label_key": "docsight.evidence.item.signal.label"}]),
    "7": _checklist({"present": 4, "stale": 1, "missing": 1}, [
        {"key": "signal", "status": "stale", "label_key": "docsight.evidence.item.signal.label"},
        {"key": "speedtest", "status": "missing", "label_key": "docsight.evidence.item.speedtest.label"},
    ]),
}


def _serve(page):
    page.route(re.compile(r".*/api/incidents$"), lambda route: route.fulfill(json=CASES))
    page.route(
        re.compile(r".*/api/evidence/checklist\?incident_id=\d+$"),
        lambda route: route.fulfill(json=CHECKLISTS[route.request.url.rsplit("=", 1)[1]]),
    )


def _open_journal(page):
    page.goto(page.url.split("#", 1)[0].split("?", 1)[0] + "?lang=en#journal", wait_until="networkidle")
    expect(page.locator("#case-cards .case-card")).to_have_count(2)


def test_cards_show_each_case_with_its_evidence_state(demo_page):
    page = demo_page
    _serve(page)
    _open_journal(page)

    cards = page.locator("#case-cards .case-card")
    open_card, resolved_card = cards.nth(0), cards.nth(1)
    expect(open_card.locator(".case-card-name")).to_have_text("Evening dropouts")
    expect(open_card.locator(".badge")).to_have_text("Open")
    expect(open_card.locator(".case-card-meta")).to_contain_text("ongoing · 3 notes")
    expect(open_card.locator(".case-light")).to_have_text(["4 ready", "1 stale", "1 missing"])
    # A missing item comes before a stale one as the next step.
    expect(open_card.locator(".case-card-next")).to_have_text(re.compile(r"^Missing: "))
    expect(resolved_card.locator(".badge")).to_have_text("Resolved")
    expect(resolved_card.locator(".case-card-meta")).to_contain_text("1 note")
    expect(resolved_card.locator(".case-card-next")).to_have_text("Evidence ready")


def test_continue_opens_the_case_checklist_and_open_shows_the_timeline(demo_page):
    page = demo_page
    _serve(page)
    _open_journal(page)

    cards = page.locator("#case-cards .case-card")
    cards.nth(1).get_by_role("button", name="Open").click()
    expect(page.locator("#incident-timeline-view")).to_be_visible()
    expect(page.locator("#case-cards")).to_be_hidden()
    page.locator(".incident-timeline-back").click()
    expect(page.locator("#case-cards")).to_be_visible()

    cards.nth(0).get_by_role("button", name="Continue").click()
    expect(page.locator("#view-evidence")).to_be_visible()
    expect(page).to_have_url(re.compile(r"#evidence\?case=7$"))
    expect(page.locator("#evidence-incident-id")).to_have_value("7")
    expect(page.locator("#evidence-results")).to_be_visible()
