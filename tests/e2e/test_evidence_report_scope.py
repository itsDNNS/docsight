"""Evidence Journey → fixed-window report browser contracts."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect


FROM = "2026-06-10T18:00:00Z"
TO = "2026-06-10T23:00:00Z"


def _payload(kind="range"):
    window = {
        "kind": kind,
        "label": "Evening outage" if kind == "range" else "Recurring packet loss",
        "from": FROM,
        "to": TO,
    }
    if kind == "incident":
        window["incident_id"] = 42
    items = [
        {"key": "signal", "label_key": "docsight.evidence.item.signal.label", "status": "present"},
        {"key": "speedtest", "label_key": "docsight.evidence.item.speedtest.label", "status": "stale"},
        {"key": "latency", "label_key": "docsight.evidence.item.latency.label", "status": "missing"},
        {"key": "bnetz", "label_key": "docsight.evidence.item.bnetz.label", "status": "optional"},
        {"key": "events", "label_key": "docsight.evidence.item.events.label", "status": "not_applicable"},
        {"key": "journal", "label_key": "docsight.evidence.item.journal.label", "status": "unavailable"},
    ]
    items.append({
        "key": "report",
        "label_key": "docsight.evidence.item.report.label",
        "hint_key": "docsight.evidence.item.report.present",
        "status": "present",
        "action": {"action": "report"},
    })
    return {
        "window": window,
        "summary": {
            "present": 2,
            "stale": 1,
            "missing": 1,
            "optional": 1,
            "not_applicable": 1,
        },
        "items": items,
        "capabilities": {"demo_mode": False},
    }


def _open_scoped_report(page, payload):
    page.route("**/api/evidence/checklist?**", lambda route: route.fulfill(json=payload))
    page.evaluate("switchView('evidence')")
    page.locator("#evidence-run").click()
    expect(page.locator("#evidence-results")).to_be_visible()
    page.get_by_role("button", name="Generate report").click()
    modal = page.locator("#report-modal")
    expect(modal).to_be_visible()
    return modal


def test_first_visit_builds_the_last_24_hours_and_shows_results_only_when_ready(demo_page):
    held = []
    demo_page.route("**/api/evidence/checklist?**", lambda route: held.append(route))
    with demo_page.expect_request("**/api/evidence/checklist?**") as request:
        demo_page.evaluate("switchView('evidence')")
    assert "from=" in request.value.url and "to=" in request.value.url

    # The default window is evaluated right away; until it arrives only the loading state shows.
    expect(demo_page.locator('.evidence-chip[data-evidence-range="last24h"]')).to_have_attribute("aria-pressed", "true")
    expect(demo_page.locator("#evidence-loading")).to_be_visible()
    expect(demo_page.locator("#evidence-results")).to_be_hidden()
    expect(demo_page.locator("#evidence-copy")).to_be_hidden()
    assert len(held) == 1

    held[0].fulfill(json=_payload())
    expect(demo_page.locator("#evidence-results")).to_be_visible()
    expect(demo_page.locator("#evidence-copy")).to_be_visible()
    expect(demo_page.locator("#evidence-loading")).to_be_hidden()
    expect(demo_page.locator("#evidence-demo-banner")).to_be_hidden()


@pytest.mark.parametrize("viewport", [
    {"width": 1280, "height": 900},
    {"width": 393, "height": 852},
], ids=["desktop", "mobile"])
def test_evidence_report_preview_and_pdf_keep_exact_canonical_window(demo_page, viewport):
    demo_page.set_viewport_size(viewport)
    modal = _open_scoped_report(demo_page, _payload())

    expect(modal.get_by_role("heading", name="Problem window")).to_be_visible()
    expect(modal).to_contain_text("Evening outage")
    expect(modal.locator("#report-period-from")).to_have_attribute("datetime", FROM)
    expect(modal.locator("#report-period-to")).to_have_attribute("datetime", TO)
    expect(modal.locator("#report-days-field")).to_be_hidden()
    expect(modal.locator("#report-days")).to_be_disabled()
    for status in ["Ready", "Stale", "Missing", "Optional", "Not applicable", "Unavailable"]:
        expect(modal.locator("#report-readiness-list")).to_contain_text(status)
    expect(modal.get_by_role("heading", name="Supporting evidence")).to_be_visible()
    if viewport["width"] < 720:
        body_geometry = modal.locator(".modal-body").evaluate(
            "el => ({scrollHeight: el.scrollHeight, clientHeight: el.clientHeight})"
        )
        assert body_geometry["scrollHeight"] > body_geometry["clientHeight"]
        expect(modal.locator(".modal-footer")).to_be_visible()

    demo_page.route(
        "**/api/complaint?**",
        lambda route: route.fulfill(json={
            "text": "Editable complaint preview.",
            "lang": "en",
            "window": {"from": FROM, "to": TO},
        }),
    )
    with demo_page.expect_request("**/api/complaint?**") as complaint_request:
        modal.get_by_role("button", name="Build evidence package").click()
    complaint_params = parse_qs(urlparse(complaint_request.value.url).query)
    assert complaint_params["from"] == [FROM]
    assert complaint_params["to"] == [TO]
    assert "days" not in complaint_params
    expect(modal.locator("#report-complaint-text")).to_have_value("Editable complaint preview.")

    if viewport["width"] < 720:
        expect(modal.locator("#report-complaint-text")).to_be_editable()
        expect(modal.get_by_role("button", name="Download PDF package")).to_be_visible()

    overflow = modal.evaluate(
        "el => ({modal: el.scrollWidth - el.clientWidth, document: document.documentElement.scrollWidth - window.innerWidth})"
    )
    assert overflow["modal"] <= 1
    assert overflow["document"] <= 1

    demo_page.route(
        "**/api/report?**",
        lambda route: route.fulfill(status=200, content_type="application/pdf", body="%PDF-1.4\n%%EOF"),
    )
    with demo_page.expect_request("**/api/report?**") as pdf_request:
        modal.get_by_role("button", name="Download PDF package").click()
    pdf_params = parse_qs(urlparse(pdf_request.value.url).query)
    assert pdf_params["from"] == complaint_params["from"]
    assert pdf_params["to"] == complaint_params["to"]
    assert "days" not in pdf_params


@pytest.mark.parametrize(("kind", "focus_id"), [
    ("range", "evidence-from"),
    ("incident", "evidence-incident-id"),
])
def test_change_problem_window_returns_to_deterministic_evidence_control(demo_page, kind, focus_id):
    modal = _open_scoped_report(demo_page, _payload(kind))

    modal.get_by_role("button", name="Change problem window").click()

    expect(modal).to_be_hidden()
    expect(demo_page.locator("#view-evidence")).to_have_class("view active")
    expect(demo_page.locator(f"#{focus_id}")).to_be_focused()
    assert demo_page.evaluate("document.querySelector('#report-days').disabled") is False


def test_mismatched_fixed_window_response_stays_on_step_one_with_live_error(demo_page):
    modal = _open_scoped_report(demo_page, _payload())
    demo_page.route(
        "**/api/complaint?**",
        lambda route: route.fulfill(json={
            "text": "This text must not be shown.",
            "lang": "en",
            "window": {"from": FROM, "to": "2026-06-10T23:05:00Z"},
        }),
    )

    modal.get_by_role("button", name="Build evidence package").click()

    expect(modal.locator("#report-step1")).to_be_visible()
    expect(modal.locator("#report-step2")).to_be_hidden()
    expect(modal.locator("#report-complaint-text")).to_have_value("")
    status = modal.locator("#report-builder-status")
    expect(status).to_have_attribute("aria-live", "polite")
    expect(status).to_contain_text("different problem window")
    expect(status).to_contain_text("Change problem window")


def _local_input(page, offset_ms, round_up):
    return page.evaluate(
        "([offset, up]) => DOCSightBrowserContracts.localInputValue(Date.now() + offset, DOCSIGHT_TIME_ZONE, up)",
        [offset_ms, round_up],
    )


def test_quick_ranges_fill_the_window_in_the_configured_time_zone(demo_page):
    requests = []
    demo_page.route("**/api/evidence/checklist?**", lambda route: (requests.append(route.request.url), route.fulfill(json=_payload())))
    demo_page.evaluate("switchView('evidence')")
    expect(demo_page.locator("#evidence-results")).to_be_visible()

    demo_page.locator('.evidence-chip[data-evidence-range="yesterday_evening"]').click()
    yesterday = _local_input(demo_page, -24 * 3600 * 1000, False)[:10]
    expect(demo_page.locator("#evidence-from")).to_have_value(f"{yesterday}T18:00")
    expect(demo_page.locator("#evidence-to")).to_have_value(f"{yesterday}T23:00")
    expect(demo_page.locator('.evidence-chip[data-evidence-range="yesterday_evening"]')).to_have_attribute("aria-pressed", "true")
    expect(demo_page.locator('.evidence-chip[data-evidence-range="last24h"]')).to_have_attribute("aria-pressed", "false")

    with demo_page.expect_request("**/api/evidence/checklist?**"):
        demo_page.locator('.evidence-chip[data-evidence-range="last7d"]').click()
    expect(demo_page.locator("#evidence-from")).to_have_value(_local_input(demo_page, -7 * 24 * 3600 * 1000, False))
    assert len(requests) >= 3

    # Editing the window by hand leaves the quick ranges.
    demo_page.locator("#evidence-from").fill(f"{yesterday}T10:00")
    expect(demo_page.locator('.evidence-chip[aria-pressed="true"]')).to_have_count(0)


def _shortest_closed_case(incidents):
    """The demo's open case spans months; a short closed case keeps the checklist quick."""
    from datetime import date

    closed = [incident for incident in incidents if incident["status"] != "open" and incident.get("end_date")]
    return min(closed, key=lambda incident: date.fromisoformat(incident["end_date"][:10]) - date.fromisoformat(incident["start_date"][:10]))


def test_case_picker_lists_open_cases_first_and_builds_the_case_checklist(demo_page, live_server):
    incidents = demo_page.request.get(f"{live_server}/api/incidents").json()
    open_cases = [incident for incident in incidents if incident["status"] == "open"]
    case = _shortest_closed_case(incidents)
    demo_page.evaluate("switchView('evidence')")
    picker = demo_page.locator("#evidence-incident-id")
    expect(picker.locator("option")).to_have_count(len(incidents) + 1)

    first_case = picker.locator("option").nth(1)
    expect(first_case).to_have_attribute("value", str(open_cases[0]["id"]))
    expect(first_case).to_contain_text(open_cases[0]["name"])

    with demo_page.expect_request("**/api/evidence/checklist?incident_id=*") as request:
        picker.select_option(str(case["id"]))
    assert f"incident_id={case['id']}" in request.value.url
    expect(demo_page.locator('.evidence-chip[aria-pressed="true"]')).to_have_count(0)
    expect(demo_page.locator("#evidence-window-label")).to_contain_text(case["name"], timeout=15000)
    # A case keeps its name as the title, with its window below in the dashboard's time format.
    window_range = demo_page.locator("#evidence-window-range")
    expect(window_range).to_be_visible()
    assert not ISO_TIMESTAMP.search(window_range.inner_text())


ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def test_window_and_latest_times_read_like_the_rest_of_the_dashboard(demo_page):
    demo_page.evaluate("switchView('evidence')")
    expect(demo_page.locator("#evidence-results")).to_be_visible(timeout=15000)
    # A plain range is its own title; the second line would only repeat it.
    assert not ISO_TIMESTAMP.search(demo_page.locator("#evidence-window-label").inner_text())
    expect(demo_page.locator("#evidence-window-range")).to_be_hidden()

    latest = demo_page.locator("#evidence-items time[datetime]").first
    expect(latest).to_be_visible()
    stamp = latest.get_attribute("datetime")
    assert ISO_TIMESTAMP.match(stamp)
    expect(latest).to_have_text(demo_page.evaluate("value => formatDocsightTime(value)", stamp))
    expect(latest.locator("xpath=..")).to_contain_text("Latest:")
    assert not ISO_TIMESTAMP.search(demo_page.locator("#evidence-items").inner_text())


def test_a_slow_earlier_window_cannot_replace_a_newer_case_result(demo_page, live_server):
    incidents = demo_page.request.get(f"{live_server}/api/incidents").json()
    case = _shortest_closed_case(incidents)
    held = []
    demo_page.route("**/api/evidence/checklist?from=**", lambda route: held.append(route))
    demo_page.evaluate("switchView('evidence')")
    picker = demo_page.locator("#evidence-incident-id")
    expect(picker.locator("option")).to_have_count(len(incidents) + 1)

    picker.select_option(str(case["id"]))
    expect(demo_page.locator("#evidence-window-label")).to_contain_text(case["name"], timeout=15000)
    # The automatic last-24-hours request answers late and must be ignored.
    held[0].fulfill(json=_payload())
    demo_page.wait_for_timeout(300)
    expect(demo_page.locator("#evidence-window-label")).to_contain_text(case["name"])


def test_counts_say_what_they_count(demo_page):
    demo_page.evaluate("switchView('evidence')")
    expect(demo_page.locator("#evidence-results")).to_be_visible(timeout=15000)
    pill = demo_page.locator("#evidence-items .evidence-count-pill").first
    expect(pill).to_be_visible()
    expect(pill).to_have_attribute("title", "Data points in this window")
    number = pill.evaluate("node => [...node.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('')")
    assert number.isdigit()
    expect(pill.locator(".sr-only")).to_have_text("Data points in this window: ")
