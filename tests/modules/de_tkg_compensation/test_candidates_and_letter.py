"""Pure supporting-adapter and deterministic letter tests."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from app.modules.de_tkg_compensation.candidates import (
    CONNECTION_CANDIDATE_MAX_RESULTS,
    CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET,
    chunk_report_windows,
    load_connection_monitor_candidates,
    load_incident_candidates,
)
from app.modules.de_tkg_compensation.letter import render_claim_letter
from app.modules.de_tkg_compensation.rules import (
    compute_missed_appointment,
    compute_outage_compensation,
    empty_compensation_breakdown,
)
from app.modules.de_tkg_compensation.rules_data import RULESET_DE_TKG58


def test_report_chunks_do_not_limit_claim_and_each_window_is_at_most_90_days():
    chunks = chunk_report_windows(
        "2026-01-01T00:00:00Z", "2026-05-01T00:00:00Z"
    )

    assert chunks == [
        {"index": 1, "from": "2026-01-01T00:00:00Z", "to": "2026-04-01T00:00:00Z"},
        {"index": 2, "from": "2026-04-01T00:00:01Z", "to": "2026-05-01T00:00:00Z"},
    ]


def test_letter_is_deterministic_and_uses_the_calculation_breakdown():
    breakdown = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 6),
        confirmed_full_outage_days=[date(2026, 1, 4), date(2026, 1, 6)],
        monthly_fee_cents=4_000,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 6),
    )
    claim = {
        "fault_report_received_date": "2026-01-01",
        "fault_report_channel": "Portal",
        "ticket_ref": "SYNTHETIC-7",
        "restored_date": "2026-01-06",
        "prior_credit": {"amount_cents": 1_169, "classification": "unclear"},
    }

    first = render_claim_letter(claim=claim, breakdown=breakdown)
    second = render_claim_letter(claim=claim, breakdown=breakdown)

    assert first == second
    assert "2026-01-04 (Tag 3 nach Eingang)" in first
    assert "2026-01-06 (Tag 5 nach Eingang)" in first
    assert "Voraussichtlicher Anspruch aus vollständigem Ausfall: 15,00 €" in first
    assert "Voraussichtlicher Gesamtanspruch: 15,00 €" in first
    assert "nicht automatisch" in first
    assert RULESET_DE_TKG58.rules_version in first
    assert "https://www.gesetze-im-internet.de/tkg_2021/__58.html" in first


def test_long_window_letter_contains_the_same_complete_120_day_breakdown():
    report_date = date(2026, 1, 1)
    confirmed = [date(2026, 1, 4) + timedelta(days=offset) for offset in range(120)]
    breakdown = compute_outage_compensation(
        fault_report_received=report_date,
        restored=confirmed[-1],
        confirmed_full_outage_days=confirmed,
        monthly_fee_cents=4_000,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=confirmed[-1],
    )

    letter = render_claim_letter(
        claim={"fault_report_received_date": report_date.isoformat(), "restored_date": confirmed[-1].isoformat()},
        breakdown=breakdown,
    )

    assert letter.count("; TKG §58 Abs.3") == 120
    assert confirmed[-1].isoformat() in letter
    assert "Voraussichtlicher Anspruch aus vollständigem Ausfall: 1190,00 €" in letter


def test_connection_monitor_candidates_keep_local_days_stable_across_dst(tmp_path):
    db_path = tmp_path / "connection_monitor.db"
    start = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc).timestamp()
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE connection_targets (id INTEGER PRIMARY KEY, enabled INTEGER)")
        conn.execute("CREATE TABLE connection_samples (target_id INTEGER, timestamp REAL, timeout INTEGER)")
        conn.execute("INSERT INTO connection_targets VALUES (1, 1)")
        conn.executemany(
            "INSERT INTO connection_samples VALUES (1, ?, 1)",
            [(start + offset,) for offset in range(5)],
        )
        conn.execute("INSERT INTO connection_samples VALUES (1, ?, 0)", (end,))

    candidates = load_connection_monitor_candidates(str(db_path), "Europe/Berlin")

    assert candidates[0]["suggested_days"] == ["2026-10-25", "2026-10-26"]


def test_appointment_only_letter_has_no_outage_assertion_for_flat_and_percentage_rates():
    for fee, expected in ((4_000, "10,00 €"), (6_000, "12,00 €")):
        breakdown = empty_compensation_breakdown(RULESET_DE_TKG58)
        appointment = compute_missed_appointment(
            monthly_fee_cents=fee, ruleset=RULESET_DE_TKG58
        )

        first = render_claim_letter(
            claim={"monthly_fee_cents": fee, "eligibility": {"missed_appointments": 1}},
            breakdown=breakdown,
            missed_appointments=(appointment,),
        )
        second = render_claim_letter(
            claim={"monthly_fee_cents": fee, "eligibility": {"missed_appointments": 1}},
            breakdown=breakdown,
            missed_appointments=(appointment,),
        )

        assert first == second
        assert f"Voraussichtlicher Gesamtanspruch: {expected}" in first
        assert "TKG §58 Abs.4" in first
        assert "vollständigen Dienstausfall" not in first
        assert "Störungsmeldung" not in first
        assert "Entstörungsdatum" not in first
        assert "TKG §58 Abs.3" not in first


def test_letter_calls_report_receipt_meldetag_and_labels_days_after_receipt():
    breakdown = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 4),
        confirmed_full_outage_days=[date(2026, 1, 1), date(2026, 1, 4)],
        monthly_fee_cents=4_000,
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 4),
    )

    letter = render_claim_letter(
        claim={
            "fault_report_received_date": "2026-01-01",
            "restored_date": "2026-01-04",
        },
        breakdown=breakdown,
    )

    assert "2026-01-01 (Meldetag): nicht angesetzt" in letter
    assert "2026-01-04 (Tag 3 nach Eingang)" in letter
    assert "Tag 0" in letter  # Natural waiting-period explanation, never a date label.
    assert "2026-01-01 (Tag 0)" not in letter


def test_combined_outage_and_appointment_letter_has_one_deterministic_total():
    breakdown = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 6),
        confirmed_full_outage_days=[date(2026, 1, 4), date(2026, 1, 6)],
        monthly_fee_cents=4_000,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 6),
    )
    appointment = compute_missed_appointment(
        monthly_fee_cents=4_000, ruleset=RULESET_DE_TKG58
    )
    claim = {
        "fault_report_received_date": "2026-01-01",
        "restored_date": "2026-01-06",
        "eligibility": {"complete_outage": True, "missed_appointments": 1},
    }

    first = render_claim_letter(
        claim=claim,
        breakdown=breakdown,
        missed_appointments=(appointment,),
    )
    second = render_claim_letter(
        claim=claim,
        breakdown=breakdown,
        missed_appointments=(appointment,),
    )

    assert first == second
    assert "Voraussichtlicher Anspruch aus vollständigem Ausfall: 15,00 €" in first
    assert "Summe verpasste Termine: 10,00 €" in first
    assert first.count("Voraussichtlicher Gesamtanspruch: 25,00 €") == 1


def test_letter_rows_show_full_max_comparison_and_natural_credit_labels():
    breakdown = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 4),
        confirmed_full_outage_days=[date(2026, 1, 4)],
        monthly_fee_cents=6_000,
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 4),
    )
    expected_labels = {
        "goodwill": "Kulanz",
        "reduction": "Entgeltminderung",
        "compensation": "Entschädigung",
        "unclear": "unklar",
    }

    for classification, label in expected_labels.items():
        letter = render_claim_letter(
            claim={
                "fault_report_received_date": "2026-01-01",
                "restored_date": "2026-01-04",
                "prior_credit": {"amount_cents": 100, "classification": classification},
            },
            breakdown=breakdown,
        )
        assert "max(5,00 €; 10 % = 6,00 €) = 6,00 €" in letter
        assert f"Nutzerseitige Einordnung: {label}" in letter


def test_open_incident_runs_through_configured_local_today_without_restoration(tmp_path):
    db_path = tmp_path / "docsis_history.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE incidents (id INTEGER PRIMARY KEY, name TEXT, start_date TEXT, "
            "end_date TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO incidents VALUES (1, 'Open incident', '2026-03-27', NULL, 'open')"
        )

    candidate = load_incident_candidates(
        str(db_path), "Europe/Berlin", local_today_value="2026-03-30"
    )[0]

    assert candidate["ongoing"] is True
    assert candidate["suggested_days"] == [
        "2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30"
    ]
    assert candidate["restoration_suggested"] is False


def test_ongoing_timeout_run_is_explicit_and_uses_latest_evidence(tmp_path):
    db_path = tmp_path / "connection_monitor.db"
    start = datetime(2026, 7, 1, 21, 59, tzinfo=timezone.utc).timestamp()
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE connection_targets (id INTEGER PRIMARY KEY, enabled INTEGER)")
        conn.execute("CREATE TABLE connection_samples (target_id INTEGER, timestamp REAL, timeout INTEGER)")
        conn.execute("CREATE INDEX idx_samples_target_ts ON connection_samples(target_id, timestamp)")
        conn.execute("INSERT INTO connection_targets VALUES (1, 1)")
        conn.executemany(
            "INSERT INTO connection_samples VALUES (1, ?, 1)",
            [(start + offset * 60,) for offset in range(7)],
        )

    candidate = load_connection_monitor_candidates(str(db_path), "Europe/Berlin")[0]

    assert candidate["ongoing"] is True
    assert candidate["restoration_suggested"] is False
    assert candidate["window_to"] == "2026-07-01T22:05:00Z"
    assert candidate["suggested_days"] == ["2026-07-01", "2026-07-02"]


def test_connection_monitor_candidate_generation_is_bounded_on_large_database(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager

    import app.modules.de_tkg_compensation.candidates as candidate_module

    db_path = tmp_path / "connection_monitor.db"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    sample_count = CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET * 3
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE connection_targets (id INTEGER PRIMARY KEY, enabled INTEGER)")
        conn.execute("CREATE TABLE connection_samples (target_id INTEGER, timestamp REAL, timeout INTEGER)")
        conn.execute("CREATE INDEX idx_samples_target_ts ON connection_samples(target_id, timestamp)")
        conn.execute("INSERT INTO connection_targets VALUES (1, 1)")
        conn.executemany(
            "INSERT INTO connection_samples VALUES (1, ?, ?)",
            ((base + offset, 1 if offset % 7 else 0) for offset in range(sample_count)),
        )
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT timestamp, timeout FROM connection_samples "
            "WHERE target_id = ? AND timestamp >= (SELECT COALESCE(MAX(timestamp), 0) - ? "
            "FROM connection_samples WHERE target_id = ?) ORDER BY timestamp DESC LIMIT ?",
            (1, 30 * 86_400, 1, CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET),
        ).fetchall()

    traces = []
    real_open_read = candidate_module.open_read

    @contextmanager
    def observed_open_read(path):
        with real_open_read(path) as conn:
            conn.set_trace_callback(traces.append)
            yield conn

    monkeypatch.setattr(candidate_module, "open_read", observed_open_read)

    candidates = load_connection_monitor_candidates(str(db_path), "Europe/Berlin")

    assert any("idx_samples_target_ts" in row[3] for row in plan)
    sample_queries = [query for query in traces if "FROM connection_samples" in query]
    assert sample_queries
    assert all("LIMIT 2000" in query for query in sample_queries)
    assert len(candidates) <= CONNECTION_CANDIDATE_MAX_RESULTS
    assert all(
        candidate["proposal_sample_limit"] == CONNECTION_CANDIDATE_MAX_SAMPLES_PER_TARGET
        for candidate in candidates
    )
