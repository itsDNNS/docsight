"""Regression vectors for the German TKG outage-compensation rules."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.modules.de_tkg_compensation.rules import (
    RuleValidationError,
    compute_missed_appointment,
    compute_outage_compensation,
)
from app.modules.de_tkg_compensation.rules_data import RULESET_DE_TKG58


def _days(start: date, count: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(count)]


def test_report_receipt_is_day_zero_and_thursday_is_first_eligible_day():
    result = compute_outage_compensation(
        fault_report_received=date(2026, 1, 5),  # Monday
        restored=date(2026, 1, 8),
        confirmed_full_outage_days=[
            date(2026, 1, 7),  # Wednesday: second calendar day after receipt
            date(2026, 1, 8),  # Thursday: third calendar day after receipt
        ],
        monthly_fee_cents=4_000,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 8),
    )

    assert [(item.date, item.day_index) for item in result.exclusions] == [
        ("2026-01-07", 2)
    ]
    assert result.exclusions[0].reason == "statutory_waiting_period"
    assert [(item.date, item.day_index, item.amount_cents) for item in result.days] == [
        ("2026-01-08", 3, 500)
    ]
    assert "report-receipt date is day 0" in result.source_review_note
    assert "full local calendar day of complete outage" in result.source_review_note


@pytest.mark.parametrize(
    ("monthly_fee_cents", "confirmed_day", "expected_cents", "expected_basis"),
    [
        (4_000, date(2026, 1, 4), 500, "flat"),
        (4_000, date(2026, 1, 5), 500, "flat"),
        (4_000, date(2026, 1, 6), 1_000, "flat"),
        (6_000, date(2026, 1, 4), 600, "percent"),
        (6_000, date(2026, 1, 6), 1_200, "percent"),
    ],
)
def test_outage_vectors_v1_to_v5(
    monthly_fee_cents, confirmed_day, expected_cents, expected_basis
):
    result = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 7),
        confirmed_full_outage_days=[confirmed_day],
        monthly_fee_cents=monthly_fee_cents,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 8),
    )

    assert result.total_cents == expected_cents
    assert result.days[0].day_index == (confirmed_day - date(2026, 1, 1)).days
    assert result.days[0].basis == expected_basis
    assert result.days[0].amount_cents == expected_cents


@pytest.mark.parametrize(
    ("monthly_fee_cents", "expected_cents", "expected_basis"),
    [(4_000, 1_000, "flat"), (6_000, 1_200, "percent")],
)
def test_missed_appointment_vectors_v6_and_v7(
    monthly_fee_cents, expected_cents, expected_basis
):
    item = compute_missed_appointment(
        monthly_fee_cents=monthly_fee_cents,
        ruleset=RULESET_DE_TKG58,
    )

    assert item.amount_cents == expected_cents
    assert item.basis == expected_basis
    assert item.rule_ref == "TKG §58 Abs.4"


def test_long_window_v8_has_no_legal_or_hidden_90_day_cap():
    report_date = date(2026, 1, 1)
    confirmed = _days(report_date + timedelta(days=3), 120)

    result = compute_outage_compensation(
        fault_report_received=report_date,
        restored=confirmed[-1],
        confirmed_full_outage_days=confirmed,
        monthly_fee_cents=4_000,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=confirmed[-1],
    )

    assert len(result.days) == 120
    assert result.total_cents == 500 + 500 + (118 * 1_000)


def test_fractional_cent_percentages_use_decimal_half_up_and_disclose_rounding():
    result = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 4),
        confirmed_full_outage_days=[date(2026, 1, 4)],
        monthly_fee_cents=5_555,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 4),
    )

    assert result.days[0].amount_cents == 556
    assert result.days[0].rounding_applied is True
    assert result.rounding_note


def test_replacement_solution_excludes_only_explicitly_confirmed_days():
    result = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 6),
        confirmed_full_outage_days=[date(2026, 1, 4), date(2026, 1, 5)],
        monthly_fee_cents=4_000,
        replacement_solution_days=[date(2026, 1, 5)],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 6),
    )

    assert [item.date for item in result.days] == ["2026-01-04"]
    assert result.exclusions[0].date == "2026-01-05"
    assert result.exclusions[0].reason == "provider_replacement_solution_confirmed"


def test_restoration_day_is_controlled_by_explicit_day_confirmation():
    result = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 4),
        confirmed_full_outage_days=[date(2026, 1, 4)],
        monthly_fee_cents=4_000,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 4),
    )

    assert [item.date for item in result.days] == ["2026-01-04"]


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"monthly_fee_cents": None}, "technical_monthly_fee_required"),
        ({"monthly_fee_cents": -1}, "technical_monthly_fee_negative"),
        ({"restored": date(2025, 12, 31)}, "technical_restored_before_report"),
        ({"fault_report_received": date(2026, 1, 8)}, "technical_report_in_future"),
        (
            {"confirmed_full_outage_days": [date(2025, 12, 31)]},
            "technical_confirmed_day_outside_window",
        ),
    ],
)
def test_stable_technical_validation_codes(kwargs, code):
    values = {
        "fault_report_received": date(2026, 1, 1),
        "restored": date(2026, 1, 6),
        "confirmed_full_outage_days": [date(2026, 1, 4)],
        "monthly_fee_cents": 4_000,
        "replacement_solution_days": [],
        "ruleset": RULESET_DE_TKG58,
        "today": date(2026, 1, 7),
    }
    values.update(kwargs)

    with pytest.raises(RuleValidationError) as exc_info:
        compute_outage_compensation(**values)

    assert exc_info.value.code == code


def test_zero_monthly_fee_uses_statutory_flat_amounts():
    result = compute_outage_compensation(
        fault_report_received=date(2026, 1, 1),
        restored=date(2026, 1, 6),
        confirmed_full_outage_days=[date(2026, 1, 4), date(2026, 1, 6)],
        monthly_fee_cents=0,
        replacement_solution_days=[],
        ruleset=RULESET_DE_TKG58,
        today=date(2026, 1, 6),
    )

    assert [item.amount_cents for item in result.days] == [500, 1_000]


def test_confirmed_day_must_be_inside_selected_local_claim_window():
    with pytest.raises(RuleValidationError) as exc_info:
        compute_outage_compensation(
            fault_report_received=date(2026, 1, 1),
            restored=date(2026, 1, 5),
            confirmed_full_outage_days=[date(2026, 1, 4)],
            monthly_fee_cents=4_000,
            replacement_solution_days=[],
            claim_window_start=date(2026, 1, 5),
            claim_window_end=date(2026, 1, 6),
            ruleset=RULESET_DE_TKG58,
            today=date(2026, 1, 5),
        )

    assert exc_info.value.code == "technical_confirmed_day_outside_claim_window"
