"""Evidence Journey → fixed-window report browser contracts."""

from __future__ import annotations

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
