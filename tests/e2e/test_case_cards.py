"""The case overview above the journal: one card per case with its evidence state."""

import re

from playwright.sync_api import expect

CASES = [
    {"id": 3, "name": "Resolved earlier", "status": "resolved", "start_date": "2026-09-01", "end_date": "2026-09-03", "entry_count": 1},
    {"id": 7, "name": "Evening dropouts", "status": "open", "start_date": "2026-10-01", "end_date": None, "entry_count": 3},
]


def _checklist(statuses):
    items = [{"key": key, "status": status, "label_key": f"docsight.evidence.item.{key}.label"} for key, status in statuses]
    # The report item is the export step and never counts as evidence.
    items.append({"key": "report", "status": "missing", "label_key": "docsight.evidence.item.report.label"})
    return {"window": {"kind": "incident", "label": "x", "from": "2026-10-01T00:00:00Z", "to": "2026-10-07T00:00:00Z"},
            "summary": {}, "items": items, "capabilities": {}}


READY = ["events", "journal", "bnetz", "latency"]
CHECKLISTS = {
    "3": _checklist([(key, "present") for key in READY + ["signal", "speedtest"]]),
    "7": _checklist([("signal", "stale"), ("speedtest", "missing")] + [(key, "present") for key in READY]),
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


def test_continue_and_open_both_lead_into_the_case(demo_page):
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
    expect(page.locator("#incident-timeline-view")).to_be_visible()
    expect(page.locator("#incident-timeline-steps .case-step").nth(1)).to_contain_text("Evidence · 4 of 6 ready")
