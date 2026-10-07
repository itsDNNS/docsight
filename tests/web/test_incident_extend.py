"""Adding events to a case widens its window so the case timeline covers them."""

from unittest.mock import patch

import pytest

from app.modules.journal import routes
from app.modules.journal.storage import JournalStorage


@pytest.fixture(autouse=True)
def journal(tmp_path):
    storage = JournalStorage(str(tmp_path / "journal.db"))
    with patch.object(routes, "_get_journal_storage", return_value=storage):
        yield storage


def _case(client, **window):
    resp = client.post("/api/incidents", json={"name": "Evening dropouts", **window})
    assert resp.status_code == 201
    return resp.get_json()["id"]


def _window(client, incident_id):
    data = client.get(f"/api/incidents/{incident_id}").get_json()
    return data["start_date"], data["end_date"]


def test_the_window_only_grows(client):
    incident_id = _case(client, start_date="2026-10-03", end_date="2026-10-05")

    resp = client.post(f"/api/incidents/{incident_id}/extend", json={"start_date": "2026-10-01", "end_date": "2026-10-04"})
    assert resp.get_json() == {"success": True, "start_date": "2026-10-01", "end_date": "2026-10-05", "changed": True}
    assert _window(client, incident_id) == ("2026-10-01", "2026-10-05")

    resp = client.post(f"/api/incidents/{incident_id}/extend", json={"start_date": "2026-10-02", "end_date": "2026-10-07"})
    assert _window(client, incident_id) == ("2026-10-01", "2026-10-07")

    resp = client.post(f"/api/incidents/{incident_id}/extend", json={"start_date": "2026-10-02", "end_date": "2026-10-03"})
    assert resp.get_json()["changed"] is False


def test_an_open_ended_case_keeps_running_and_a_case_without_window_gets_one(client):
    running = _case(client, start_date="2026-10-03")
    client.post(f"/api/incidents/{running}/extend", json={"start_date": "2026-10-04", "end_date": "2026-10-06"})
    assert _window(client, running) == ("2026-10-03", None)

    empty = _case(client)
    client.post(f"/api/incidents/{empty}/extend", json={"start_date": "2026-10-04", "end_date": "2026-10-06"})
    assert _window(client, empty) == ("2026-10-04", "2026-10-06")


@pytest.mark.parametrize("payload", [
    None, {}, {"start_date": "2026-10-04"}, {"start_date": "2026-10-06", "end_date": "2026-10-04"},
    {"start_date": "04.10.2026", "end_date": "2026-10-06"}, [1],
])
def test_invalid_windows_are_rejected(client, payload):
    incident_id = _case(client)
    assert client.post(f"/api/incidents/{incident_id}/extend", json=payload).status_code == 400


def test_unknown_case(client):
    resp = client.post("/api/incidents/999999/extend", json={"start_date": "2026-10-04", "end_date": "2026-10-04"})
    assert resp.status_code == 404
