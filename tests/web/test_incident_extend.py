"""Journal entry and case routes: payload checks, filters and case windows."""

import io
from unittest.mock import patch

import pytest

from werkzeug.datastructures import FileStorage
from werkzeug.test import EnvironBuilder

from app.modules.journal import routes
from app.modules.journal.import_parser import MAX_FILE_SIZE
from app.modules.journal.storage import JournalStorage
from app.runtime import get_runtime
from app.tz import local_date_to_utc_range, local_today


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


_ENTRY = {"date": "2026-10-03", "title": "Call"}
_CASE = {"name": "Evening dropouts"}
_DATE_ERROR = "Invalid date format (YYYY-MM-DD)"


def _submit(client, url, valid, method, payload):
    """POST the payload, or POST a valid record and PUT the payload over it; return the response and the stored record."""
    record = None
    if method == "PUT":
        record = f"{url}/{client.post(url, json=valid).get_json()['id']}"
    resp = client.open(record or url, method=method, json=payload)
    if resp.status_code == 201:
        record = f"{url}/{resp.get_json()['id']}"
    return resp, client.get(record).get_json() if record else None


def _check(resp, stored, expected, success):
    if isinstance(expected, str):
        assert (resp.status_code, resp.get_json()) == (400, {"error": expected})
    else:
        assert resp.status_code == success
        assert {key: stored[key] for key in expected} == expected


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("payload, expected", [
    ({}, "No data"),
    ({"title": ""}, _DATE_ERROR),
    ({"date": "2026-02-30", "title": "Call"}, _DATE_ERROR),
    ({"date": "03.10.2026", "title": "Call"}, _DATE_ERROR),
    ({"date": "2026-10-03", "title": "   "}, "Title is required"),
    ({"date": "2026-10-03", "title": "x" * 201}, "Title too long (max 200 characters)"),
    ({**_ENTRY, "description": "d" * 10001}, "Description too long (max 10000 characters)"),
    ({"date": " 2026-10-04 ", "title": f" {'x' * 200} ", "description": f" {'d' * 10000} ", "icon": " phone "},
     {"date": "2026-10-04", "title": "x" * 200, "description": "d" * 10000, "icon": "phone", "incident_id": None}),
    ({**_ENTRY, "description": None, "icon": "  "}, {"description": "", "icon": None, "incident_id": None}),
    ({**_ENTRY, "incident_id": "7"}, {"incident_id": 7}),
    ({**_ENTRY, "incident_id": 7.9}, {"incident_id": 7}),
    ({**_ENTRY, "incident_id": ""}, {"incident_id": None}),
    ({**_ENTRY, "incident_id": 0}, {"incident_id": None}),
    ({**_ENTRY, "incident_id": "abc"}, {"incident_id": None}),
    ({**_ENTRY, "incident_id": [7]}, {"incident_id": None}),
])
def test_entry_payloads_are_checked_alike_on_create_and_update(client, method, payload, expected):
    resp, stored = _submit(client, "/api/journal", {**_ENTRY, "incident_id": 3}, method, payload)
    _check(resp, stored, expected, 201 if method == "POST" else 200)


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("payload, expected", [
    ({}, "No data"),
    ({"name": " ", "status": "closed"}, "Name is required"),
    ({"name": "x" * 201}, "Name too long (max 200 characters)"),
    ({**_CASE, "description": "d" * 5001}, "Description too long (max 5000 characters)"),
    ({**_CASE, "status": "closed", "start_date": "bad"}, "Invalid status (open, resolved, escalated)"),
    ({**_CASE, "start_date": "2026-13-01", "end_date": "bad"}, "Invalid start_date format (YYYY-MM-DD)"),
    ({**_CASE, "end_date": "2026/10/03"}, "Invalid end_date format (YYYY-MM-DD)"),
    ({"name": f" {'x' * 200} ", "description": f" {'d' * 5000} ", "status": " resolved ",
      "start_date": " 2026-10-05 ", "end_date": " 2026-10-03 ", "icon": " zap "},
     {"name": "x" * 200, "description": "d" * 5000, "status": "resolved",
      "start_date": "2026-10-05", "end_date": "2026-10-03", "icon": "zap"}),
    ({**_CASE, "description": None, "status": "", "start_date": "", "end_date": None, "icon": " "},
     {"description": "", "status": "open", "start_date": None, "end_date": None, "icon": None}),
])
def test_case_payloads_are_checked_alike_on_create_and_update(client, method, payload, expected):
    valid = {**_CASE, "description": "Old", "status": "escalated", "start_date": "2026-10-01", "icon": "x"}
    resp, stored = _submit(client, "/api/incidents", valid, method, payload)
    _check(resp, stored, expected, 201 if method == "POST" else 200)


@pytest.mark.parametrize("url, valid", [("/api/journal", _ENTRY), ("/api/incidents", _CASE)])
def test_updates_check_the_payload_before_looking_up_the_record(client, url, valid):
    resp = client.put(f"{url}/999999", json={})
    assert (resp.status_code, resp.get_json()) == (400, {"error": "No data"})
    assert client.put(f"{url}/999999", json=valid).status_code == 404


@pytest.mark.parametrize("url", ["/api/journal?incident_id=", "/api/journal/export?format=json&incident_id="])
@pytest.mark.parametrize("value, titles", [
    ("7", ["Assigned"]), (" 7 ", ["Assigned"]), ("0", ["Loose"]), ("-1", []),
    ("", ["Loose", "Assigned"]), ("abc", ["Loose", "Assigned"]), ("7.0", ["Loose", "Assigned"]),
])
def test_the_case_filter_ignores_values_that_are_not_whole_numbers(client, url, value, titles):
    client.post("/api/journal", json={**_ENTRY, "title": "Assigned", "incident_id": 7})
    client.post("/api/journal", json={**_ENTRY, "title": "Loose"})
    assert sorted(e["title"] for e in client.get(url + value).get_json()) == sorted(titles)


@pytest.mark.parametrize("method, url, key, result", [
    ("DELETE", "/api/journal/batch", "ids", "deleted"),
    ("POST", "/api/journal/unassign", "entry_ids", "updated"),
    ("POST", "/api/incidents/{case}/assign", "entry_ids", "updated"),
])
def test_id_lists_keep_only_numbers(client, method, url, key, result):
    case = _case(client)
    ids = [client.post("/api/journal", json={**_ENTRY, "incident_id": case}).get_json()["id"] for _ in range(3)]
    resp = client.open(url.format(case=case), method=method, json={key: [ids[0], float(ids[1]), str(ids[2]), None]})
    assert resp.get_json() == {result: 2}


@pytest.mark.parametrize("view, query", [("timeline", "get_correlation_timeline"), ("report", "get_range_data")])
def test_an_open_case_runs_until_today_in_the_configured_zone(
    app, client, config_mgr, mock_storage, foreign_system_tz, view, query,
):
    config_mgr.save({"timezone": "Pacific/Pago_Pago"})
    get_runtime(app).storage = mock_storage
    mock_storage.get_correlation_timeline.return_value = []
    case = _case(client, start_date="2026-10-03")
    with patch("app.modules.reports.report.generate_incident_report", return_value=b"%PDF-1.4"):
        assert client.get(f"/api/incidents/{case}/{view}").status_code == 200
    start, _ = local_date_to_utc_range("2026-10-03", "Pacific/Pago_Pago")
    _, end = local_date_to_utc_range(local_today("Pacific/Pago_Pago"), "Pacific/Pago_Pago")
    assert getattr(mock_storage, query).call_args.args == (start, end)


def test_the_case_report_carries_the_attachments_of_its_entries(client, journal):
    case = _case(client)
    with_file, without = (client.post("/api/journal", json={**_ENTRY, "incident_id": case}).get_json()["id"] for _ in "ab")
    journal.save_attachment(with_file, "photo.png", "image/png", b"png")
    with patch("app.modules.reports.report.generate_incident_report", return_value=b"%PDF-1.4") as generate:
        assert client.get(f"/api/incidents/{case}/report").status_code == 200
    attachments = {entry["id"]: entry.get("attachments") for entry in generate.call_args.args[1]}
    assert [a["filename"] for a in attachments[with_file]] == ["photo.png"]
    assert not attachments[without]


@pytest.mark.parametrize("name, size, error, reads", [
    ("journal.txt", 10, "Only .xlsx and .csv files are supported", []),
    ("journal.txt", MAX_FILE_SIZE + 1, "Only .xlsx and .csv files are supported", []),
    ("journal.CSV", MAX_FILE_SIZE + 2, "File too large (max 5 MB)", [MAX_FILE_SIZE + 1]),
])
def test_the_import_preview_rejects_other_files_without_reading_them_in_full(client, name, size, error, reads):
    read = []

    def counted_read(upload, *args):
        data = upload.stream.read(*args)
        read.append(len(data))
        return data

    upload = EnvironBuilder("/api/journal/import/preview", method="POST",
                            data={"file": (io.BytesIO(b"x" * size), name)}).get_environ()
    with patch.object(FileStorage, "read", counted_read, create=True):
        resp = client.open(upload)
    assert (resp.status_code, resp.get_json()) == (400, {"error": error})
    assert read == reads
