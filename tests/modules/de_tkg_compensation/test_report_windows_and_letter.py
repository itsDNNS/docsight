"""Pure supporting-adapter and deterministic letter tests."""

from __future__ import annotations

from datetime import date, timedelta

from app.modules.de_tkg_compensation.report_windows import chunk_report_windows
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


