from app.modules.evidence.checklist import build_checklist


WINDOW = {"from": "2026-06-10T18:00:00Z", "to": "2026-06-10T23:00:00Z", "label": "Bad evening"}


def _by_key(items):
    return {item["key"]: item for item in items}


def test_build_checklist_marks_available_sources_present():
    items = _by_key(build_checklist(
        WINDOW,
        timeline=[
            {"timestamp": "2026-06-10T22:50:00Z", "source": "modem", "health": "critical"},
            {"timestamp": "2026-06-10T22:20:00Z", "source": "speedtest", "download_mbps": 120},
            {"timestamp": "2026-06-10T18:30:00Z", "source": "event", "severity": "critical"},
            {"timestamp": "2026-06-10T19:00:00Z", "source": "bnetz", "verdict_download": "not_ok"},
        ],
        journal_entries=[{"id": 1, "date": "2026-06-10", "title": "Outage note"}],
        bqm_rows=[{"timestamp": "2026-06-10T22:10:00Z", "latency_avg_ms": 34}],
        capabilities={"docsis_supported": True, "speedtest_configured": True, "bqm_configured": True, "demo_mode": False},
    ))

    assert items["signal"]["status"] == "present"
    assert items["speedtest"]["status"] == "present"
    assert items["latency"]["status"] == "present"
    assert items["events"]["status"] == "present"
    assert items["journal"]["status"] == "present"
    assert items["bnetz"]["status"] == "present"
    assert items["comparison"]["status"] == "optional"
    assert items["comparison"]["action"]["view"] == "comparison"
    assert items["report"]["status"] == "present"
    assert items["report"]["action"]["action"] == "report"
    assert items["review"]["status"] == "optional"


def test_build_checklist_distinguishes_missing_optional_and_not_applicable():
    items = _by_key(build_checklist(
        WINDOW,
        timeline=[],
        journal_entries=[],
        bqm_rows=[],
        capabilities={"docsis_supported": False, "speedtest_configured": False, "bqm_configured": False, "demo_mode": False},
    ))

    assert items["signal"]["status"] == "not_applicable"
    assert items["events"]["status"] == "not_applicable"
    assert items["speedtest"]["status"] == "optional"
    assert items["latency"]["status"] == "optional"
    assert items["journal"]["status"] == "missing"
    assert items["report"]["status"] == "missing"


def test_build_checklist_flags_stale_sources_when_latest_sample_is_old():
    items = _by_key(build_checklist(
        WINDOW,
        timeline=[
            {"timestamp": "2026-06-10T18:05:00Z", "source": "modem"},
            {"timestamp": "2026-06-10T18:10:00Z", "source": "speedtest"},
        ],
        journal_entries=[],
        bqm_rows=[{"timestamp": "2026-06-10T18:15:00Z"}],
        capabilities={"docsis_supported": True, "speedtest_configured": True, "bqm_configured": True, "demo_mode": False},
    ))

    assert items["signal"]["status"] == "stale"
    assert items["speedtest"]["status"] == "stale"
    assert items["latency"]["status"] == "stale"


def test_build_checklist_marks_demo_mode_on_payload():
    payload = build_checklist(
        WINDOW,
        timeline=[{"timestamp": "2026-06-10T22:55:00Z", "source": "modem"}],
        journal_entries=[],
        bqm_rows=[],
        capabilities={"docsis_supported": True, "speedtest_configured": True, "bqm_configured": False, "demo_mode": True},
    )

    assert all(item["demo"] is True for item in payload)
