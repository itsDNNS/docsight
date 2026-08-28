"""Pure calculation domain for German TKG § 58 compensation.

This module intentionally has no Flask, clock, filesystem, database, or network
dependency. Callers provide the review date used for technical future checks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence


@dataclass(frozen=True)
class LegalSource:
    label: str
    url: str


@dataclass(frozen=True)
class RuleSet:
    rules_version: str
    jurisdiction: str
    effective_date: str
    review_date: str
    sources: tuple[LegalSource, ...]
    source_review_note: str


@dataclass(frozen=True)
class DailyEntitlement:
    date: str
    day_index: int
    category: str
    basis: str
    flat_cents: int
    percentage: int
    percentage_cents: int
    amount_cents: int
    rounding_applied: bool
    rule_ref: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExcludedDay:
    date: str
    day_index: int
    reason: str
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompensationBreakdown:
    days: tuple[DailyEntitlement, ...]
    exclusions: tuple[ExcludedDay, ...]
    total_cents: int
    rules_version: str
    jurisdiction: str
    effective_date: str
    review_date: str
    sources: tuple[LegalSource, ...]
    rounding_note: str | None
    source_review_note: str

    def to_dict(self) -> dict:
        return {
            "days": [item.to_dict() for item in self.days],
            "exclusions": [item.to_dict() for item in self.exclusions],
            "total_cents": self.total_cents,
            "rules_version": self.rules_version,
            "jurisdiction": self.jurisdiction,
            "effective_date": self.effective_date,
            "review_date": self.review_date,
            "sources": [asdict(source) for source in self.sources],
            "rounding_note": self.rounding_note,
            "source_review_note": self.source_review_note,
        }


class RuleValidationError(ValueError):
    """Stable technical or eligibility validation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def empty_compensation_breakdown(ruleset: RuleSet) -> CompensationBreakdown:
    """Return a version-consistent empty outage result for § 58(4)-only claims."""
    return CompensationBreakdown(
        days=(),
        exclusions=(),
        total_cents=0,
        rules_version=ruleset.rules_version,
        jurisdiction=ruleset.jurisdiction,
        effective_date=ruleset.effective_date,
        review_date=ruleset.review_date,
        sources=ruleset.sources,
        rounding_note=None,
        source_review_note=ruleset.source_review_note,
    )


def _validate_monthly_fee(monthly_fee_cents: int | None) -> int:
    if monthly_fee_cents is None or isinstance(monthly_fee_cents, bool):
        raise RuleValidationError(
            "technical_monthly_fee_required", "Monthly fee is required"
        )
    if not isinstance(monthly_fee_cents, int):
        raise RuleValidationError(
            "technical_monthly_fee_invalid", "Monthly fee must be integer cents"
        )
    if monthly_fee_cents < 0:
        raise RuleValidationError(
            "technical_monthly_fee_negative", "Monthly fee cannot be negative"
        )
    return monthly_fee_cents


def _percentage_amount(monthly_fee_cents: int, percentage: int) -> tuple[int, bool]:
    exact = (Decimal(monthly_fee_cents) * Decimal(percentage)) / Decimal(100)
    rounded = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded), exact != rounded


def _entitlement_for_index(
    *, day: date, day_index: int, monthly_fee_cents: int, rule_ref: str
) -> DailyEntitlement:
    if day_index in (3, 4):
        category, flat_cents, percentage = "day_3_4", 500, 10
    else:
        category, flat_cents, percentage = "day_5_plus", 1_000, 20
    percentage_cents, rounded = _percentage_amount(monthly_fee_cents, percentage)
    basis = "percent" if percentage_cents > flat_cents else "flat"
    return DailyEntitlement(
        date=day.isoformat(),
        day_index=day_index,
        category=category,
        basis=basis,
        flat_cents=flat_cents,
        percentage=percentage,
        percentage_cents=percentage_cents,
        amount_cents=max(flat_cents, percentage_cents),
        rounding_applied=rounded,
        rule_ref=rule_ref,
    )


def compute_outage_compensation(
    *,
    fault_report_received: date,
    restored: date | None,
    confirmed_full_outage_days: Sequence[date],
    monthly_fee_cents: int | None,
    replacement_solution_days: Sequence[date] = (),
    claim_window_start: date | None = None,
    claim_window_end: date | None = None,
    ruleset: RuleSet,
    today: date,
) -> CompensationBreakdown:
    """Calculate confirmed complete-outage days without a duration cap.

    The report-receipt date is day 0. Entitlement begins on the third calendar
    day after receipt (day index 3). Every confirmed date represents a full local
    calendar day of complete outage. A restoration day participates only when it
    appears in ``confirmed_full_outage_days``. Provider replacement solutions
    exclude only explicitly confirmed local days.
    """
    fee = _validate_monthly_fee(monthly_fee_cents)
    if not isinstance(fault_report_received, date) or not isinstance(today, date):
        raise RuleValidationError("technical_date_invalid", "Dates must be calendar dates")
    if fault_report_received > today:
        raise RuleValidationError(
            "technical_report_in_future", "Fault report date cannot be in the future"
        )
    if restored is not None and restored < fault_report_received:
        raise RuleValidationError(
            "technical_restored_before_report",
            "Restoration date cannot be before fault report receipt",
        )
    if restored is not None and restored > today:
        raise RuleValidationError(
            "technical_restored_in_future", "Restoration date cannot be in the future"
        )
    if (claim_window_start is None) != (claim_window_end is None):
        raise RuleValidationError(
            "technical_claim_window_required", "Both selected claim-window bounds are required"
        )
    if claim_window_start is not None and claim_window_end is not None:
        if not isinstance(claim_window_start, date) or not isinstance(claim_window_end, date):
            raise RuleValidationError(
                "technical_claim_window_invalid", "Claim-window bounds must be calendar dates"
            )
        if claim_window_end < claim_window_start:
            raise RuleValidationError(
                "technical_claim_window_reversed", "Claim-window end cannot precede its start"
            )

    confirmed = sorted(set(confirmed_full_outage_days))
    replacement = set(replacement_solution_days)
    if any(not isinstance(day, date) for day in confirmed) or any(
        not isinstance(day, date) for day in replacement
    ):
        raise RuleValidationError(
            "technical_confirmed_day_invalid", "Confirmed days must be calendar dates"
        )
    for day in confirmed:
        if (
            claim_window_start is not None
            and claim_window_end is not None
            and not claim_window_start <= day <= claim_window_end
        ):
            raise RuleValidationError(
                "technical_confirmed_day_outside_claim_window",
                "Confirmed day lies outside the selected claim window",
            )
        if day < fault_report_received or day > (restored or today) or day > today:
            raise RuleValidationError(
                "technical_confirmed_day_outside_window",
                "Confirmed day lies outside the reported outage window",
            )
    if not replacement.issubset(set(confirmed)):
        raise RuleValidationError(
            "technical_replacement_day_unconfirmed",
            "Replacement-solution days must also be confirmed outage days",
        )

    entitlements: list[DailyEntitlement] = []
    exclusions: list[ExcludedDay] = []
    for day in confirmed:
        day_index = (day - fault_report_received).days
        if day_index < 3:
            exclusions.append(
                ExcludedDay(
                    date=day.isoformat(),
                    day_index=day_index,
                    reason="statutory_waiting_period",
                    explanation=(
                        "The report-receipt date is day 0; no § 58(3) entitlement "
                        "is calculated before the third calendar day after receipt."
                    ),
                )
            )
            continue
        if day in replacement:
            exclusions.append(
                ExcludedDay(
                    date=day.isoformat(),
                    day_index=day_index,
                    reason="provider_replacement_solution_confirmed",
                    explanation=(
                        "Excluded conservatively because the user confirmed that the "
                        "provider made a replacement solution available on this day."
                    ),
                )
            )
            continue
        entitlements.append(
            _entitlement_for_index(
                day=day,
                day_index=day_index,
                monthly_fee_cents=fee,
                rule_ref="TKG §58 Abs.3",
            )
        )

    rounded = any(item.rounding_applied for item in entitlements)
    return CompensationBreakdown(
        days=tuple(entitlements),
        exclusions=tuple(exclusions),
        total_cents=sum(item.amount_cents for item in entitlements),
        rules_version=ruleset.rules_version,
        jurisdiction=ruleset.jurisdiction,
        effective_date=ruleset.effective_date,
        review_date=ruleset.review_date,
        sources=ruleset.sources,
        rounding_note=(
            "Fractional-cent percentage results were rounded to the nearest cent "
            "using Decimal ROUND_HALF_UP. The statute states the percentage but "
            "does not prescribe a sub-cent rounding mode."
            if rounded
            else None
        ),
        source_review_note=ruleset.source_review_note,
    )


def compute_missed_appointment(
    *, monthly_fee_cents: int | None, ruleset: RuleSet
) -> DailyEntitlement:
    """Calculate one missed appointment under TKG § 58(4)."""
    fee = _validate_monthly_fee(monthly_fee_cents)
    percentage_cents, rounded = _percentage_amount(fee, 20)
    return DailyEntitlement(
        date="",
        day_index=0,
        category="missed_appointment",
        basis="percent" if percentage_cents > 1_000 else "flat",
        flat_cents=1_000,
        percentage=20,
        percentage_cents=percentage_cents,
        amount_cents=max(1_000, percentage_cents),
        rounding_applied=rounded,
        rule_ref="TKG §58 Abs.4",
    )
