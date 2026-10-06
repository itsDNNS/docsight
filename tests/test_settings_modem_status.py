"""The settings modem card says where polling stands."""

import time

from app.web import _modem_poll_status


def test_waiting_until_the_first_reading():
    assert _modem_poll_status({"last_update_at": None, "error": None}) == {"kind": "waiting"}


def test_reports_minutes_since_the_last_reading_and_until_the_next():
    now = time.time()
    status = _modem_poll_status({"last_update_at": now - (5 * 60 + 10), "poll_interval": 900}, now=now)
    assert status == {"kind": "ok", "minutes_ago": 5, "next_in": 10}


def test_an_overdue_reading_is_due_now_not_negative():
    now = time.time()
    status = _modem_poll_status({"last_update_at": now - 40 * 60, "poll_interval": 900}, now=now)
    assert status["next_in"] == 0


def test_an_error_wins_over_an_older_successful_reading():
    now = time.time()
    status = _modem_poll_status({"last_update_at": now - 60, "error": "Connection refused"}, now=now)
    assert status == {"kind": "error", "error": "Connection refused"}


def test_a_reading_records_its_time_independent_of_the_local_time_zone(monkeypatch):
    from app.runtime import RuntimeState

    state = RuntimeState()
    before = time.time()
    # A changed TZ without tzset() must not shift the recorded reading time.
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    state.update(analysis={"summary": {}})
    recorded = state.snapshot()["last_update_at"]
    assert before <= recorded <= time.time()
    assert _modem_poll_status({"last_update_at": recorded, "poll_interval": 900})["minutes_ago"] == 0
