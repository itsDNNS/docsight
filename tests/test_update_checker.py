import logging

import requests

from app.runtime import UpdateChecker


def test_update_checker_is_disabled_without_spawning():
    spawned = []
    checker = UpdateChecker(
        app_version="2026-01-01.1",
        is_enabled=lambda: False,
        spawn=spawned.append,
    )
    assert checker.latest() is None
    assert spawned == []


def test_update_checker_has_one_inflight_fetch_and_honors_ttl():
    now = [100.0]
    spawned = []
    checker = UpdateChecker(
        app_version="2026-01-01.1",
        is_enabled=lambda: True,
        fetch=lambda: "v2026-01-02.1",
        clock=lambda: now[0],
        spawn=spawned.append,
        ttl=60,
    )
    assert checker.latest() is None
    assert checker.latest() is None
    assert len(spawned) == 1
    spawned.pop()()
    assert checker.latest() == "v2026-01-02.1"
    now[0] += 61
    assert checker.latest() == "v2026-01-02.1"
    assert len(spawned) == 1


def test_update_checker_skips_dev_versions():
    spawned = []
    checker = UpdateChecker(
        app_version="dev", is_enabled=lambda: True, spawn=spawned.append
    )
    assert checker.latest() is None
    assert spawned == []


def test_update_checker_logs_a_failed_fetch_without_its_message(caplog):
    def fetch():
        raise requests.ConnectionError("https://api.github.com/private-detail")

    spawned = []
    checker = UpdateChecker(
        app_version="2026-01-01.1", is_enabled=lambda: True, fetch=fetch, spawn=spawned.append
    )
    checker.latest()
    with caplog.at_level(logging.DEBUG, logger="docsis.runtime"):
        spawned.pop()()
    assert caplog.record_tuples == [("docsis.runtime", logging.DEBUG, "Release update check failed (ConnectionError)")]
    assert checker.snapshot()["checking"] is False
