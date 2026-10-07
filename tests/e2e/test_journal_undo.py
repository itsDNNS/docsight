"""Deleting a single journal entry: it disappears at once and can be brought back."""

import re

from playwright.sync_api import expect


def _open_first_entry(page):
    page.evaluate("switchView('journal')")
    row = page.locator("#journal-tbody tr[data-entry-id], #journal-tbody tr").first
    expect(row).to_be_visible()
    entry = page.evaluate("_journalAllData[0]")
    page.evaluate("id => openEntryModal(id)", entry["id"])
    expect(page.locator("#entry-modal")).to_be_visible()
    expect(page.locator("#entry-delete-btn")).to_be_visible()
    return entry


def _route_deletes(page):
    deleted = []

    def handle(route):
        if route.request.method == "DELETE":
            deleted.append(route.request.url.rsplit("/", 1)[-1])
            route.fulfill(json={"success": True})
        else:
            route.continue_()

    page.route(re.compile(r".*/api/journal/\d+$"), handle)
    return deleted


def test_undo_brings_a_deleted_entry_back_without_deleting_it(demo_page):
    page = demo_page
    deleted = _route_deletes(page)
    entry = _open_first_entry(page)

    page.locator("#entry-delete-btn").click()
    expect(page.locator("#docsight-confirm-modal")).to_have_count(0)
    expect(page.locator("#entry-modal")).to_be_hidden()
    expect(page.locator("#journal-tbody")).not_to_contain_text(entry["title"])
    toast = page.locator("#toast")
    expect(toast).to_contain_text("Entry deleted")

    toast.get_by_role("button", name="Undo").click()
    expect(page.locator("#journal-tbody")).to_contain_text(entry["title"])
    assert deleted == []


def test_a_deleted_entry_is_sent_when_the_undo_time_runs_out(demo_page):
    page = demo_page
    page.clock.install()
    page.reload(wait_until="networkidle")
    _route_deletes(page)
    entry = _open_first_entry(page)

    page.locator("#entry-delete-btn").click()
    expect(page.locator("#toast")).to_contain_text("Entry deleted")
    page.mouse.move(5, 5)
    with page.expect_request(lambda request: request.method == "DELETE") as request:
        page.clock.run_for(6500)
    assert request.value.url.endswith(f"/api/journal/{entry['id']}")
    expect(page.locator("#toast")).to_be_hidden()
    expect(page.locator("#journal-tbody")).not_to_contain_text(entry["title"])
