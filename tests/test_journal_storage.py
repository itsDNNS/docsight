"""Journal selection and assignment contracts against real SQLite storage."""

import pytest

from app.modules.journal.storage import JournalStorage
from app.storage.sqlite import write_transaction


@pytest.fixture
def journal(tmp_path):
    storage = JournalStorage(str(tmp_path / "journal.db"))
    incident = storage.save_incident("Intermittent outages")
    other = storage.save_incident("Other incident")
    rows = [
        ("2026-01-01", "Old note", "", incident),
        ("2026-01-02", "Support call", "Ticket 123", incident),
        ("2026-01-02", "Router restarted", "Support suggested this", incident),
        ("2026-01-03", "Unassigned note", "Support follow-up", None),
        ("2026-01-04", "Other note", "Support follow-up", other),
    ]
    for index, (date, title, description, incident_id) in enumerate(rows, 1):
        entry_id = storage.save_entry(date, title, description, incident_id=incident_id)
        # Deliberately distinct creation times establish the same-date ordering.
        with write_transaction(storage.db_path) as conn:
            conn.execute(
                "UPDATE journal_entries SET created_at=? WHERE id=?",
                (f"2026-01-05T00:00:0{index}Z", entry_id),
            )
    storage.save_attachment(2, "support.txt", "text/plain", b"Ticket evidence")
    storage.save_attachment(2, "reply.txt", "text/plain", b"Support reply")
    return storage


@pytest.mark.parametrize("incident_id, expected", [
    (None, [5, 4, 3, 2, 1]), (0, [4]), (1, [3, 2, 1]), (2, [5]), (999, []),
])
def test_list_and_export_selection(journal, incident_id, expected):
    entries = journal.get_entries(incident_id=incident_id)
    assert [entry["id"] for entry in entries] == expected
    assert journal.get_entries_for_export(incident_id=incident_id) == entries
    for entry in entries:
        assert set(entry) == {
            "id", "date", "title", "description", "icon", "incident_id",
            "created_at", "updated_at", "attachment_count",
        }
        assert entry["attachment_count"] == (2 if entry["id"] == 2 else 0)


@pytest.mark.parametrize("search, expected", [
    ("SUPPORT", [3, 2]), ("2026-01-01", [1]), ("Ticket", [2]),
    ("%' OR 1=1 --", []), ("missing", []),
])
def test_search_combines_with_incident_filter(journal, search, expected):
    assert [entry["id"] for entry in journal.get_entries(search=search, incident_id=1)] == expected


def test_pagination_follows_search_and_assignment_filters(journal):
    entries = journal.get_entries(1, 1, "Support", 1)
    assert [entry["id"] for entry in entries] == [2]
    assert journal.get_entries(limit=0) == []
    assert journal.get_entries(offset=5) == []


@pytest.mark.parametrize("date_from, date_to, incident_id, expected", [
    ("2026-01-02", "2026-01-03", None, [4, 3, 2]),
    ("2026-01-02", "2026-01-03", 1, [3, 2]),
    ("2026-01-02", "2026-01-03", 0, [4]),
    ("2026-01-02", "2026-01-02", 1, [3, 2]),
    (None, "2026-01-02", None, [3, 2, 1]),
    ("2026-01-03", None, None, [5, 4]),
    ("", "", 1, [3, 2, 1]),
    ("2026-01-03", "2026-01-01", None, []),
])
def test_export_date_bounds_are_inclusive(journal, date_from, date_to, incident_id, expected):
    entries = journal.get_entries_for_export(date_from, date_to, incident_id)
    assert [entry["id"] for entry in entries] == expected


def test_export_has_no_list_limit(journal):
    for index in range(101):
        journal.save_entry("2026-02-01", f"Note {index}", "", incident_id=1)
    assert len(journal.get_entries(incident_id=1)) == 100
    assert len(journal.get_active_entries()) == 100
    assert len(journal.get_entries_for_export(incident_id=1)) == 104
    assert len(journal.get_entries_for_export("2026-02-01", "2026-02-01", 1)) == 101


def test_assignment_changes_preserve_entries_and_attachments_on_reopen(journal):
    before = journal.get_entry(2)
    attachment = journal.get_attachment(1)
    assert journal.assign_entries_to_incident([], 2) == 0
    assert journal.assign_entries_to_incident([2, 2, 999], 2) == 1
    assert journal.get_incident(1)["entry_count"] == 2
    assert journal.get_incident(2)["entry_count"] == 2
    assert journal.unassign_entries([]) == 0
    assert journal.unassign_entries([2, 2, 999]) == 1
    assert journal.unassign_entries([2]) == 1

    reopened = JournalStorage(journal.db_path)
    assert reopened.get_entry(2) == {**before, "incident_id": None}
    assert reopened.get_attachment(1) == attachment
    assert [entry["id"] for entry in reopened.get_entries(incident_id=0)] == [4, 2]
    assert reopened.get_incident(2)["entry_count"] == 1
    assert reopened.get_entry(3)["incident_id"] == 1


def test_deleting_incident_preserves_evidence(journal):
    before = journal.get_entry(2)
    attachment = journal.get_attachment(1)
    assert journal.delete_incident(1)
    assert not journal.delete_incident(1)
    assert journal.get_entry(2) == {**before, "incident_id": None}
    assert journal.get_attachment(1) == attachment
    assert journal.get_entry(5)["incident_id"] == 2
    assert len(journal.get_entries_for_export()) == 5
