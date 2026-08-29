"""Pure deterministic German claim-letter rendering."""

from __future__ import annotations

from .rules import CompensationBreakdown, DailyEntitlement


def _euros(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d} €"


def _outage_day_label(day_index: int) -> str:
    return "Meldetag" if day_index == 0 else f"Tag {day_index} nach Eingang"


def render_claim_letter(
    *,
    claim: dict,
    breakdown: CompensationBreakdown,
    missed_appointments: tuple[DailyEntitlement, ...] = (),
    customer: dict | None = None,
) -> str:
    """Render an original, editable German text from confirmed user facts."""
    customer = customer or {}
    appointment_total_cents = sum(
        item.amount_cents for item in missed_appointments
    )
    outage_claim = bool(
        (claim.get("eligibility") or {}).get("complete_outage")
        or breakdown.days
        or breakdown.exclusions
    )
    lines: list[str] = []
    if customer.get("name"):
        lines.append(str(customer["name"]))
    if customer.get("address"):
        lines.extend(str(customer["address"]).splitlines())
    if customer.get("customer_number"):
        lines.append(f"Kunden-/Vertragsnummer: {customer['customer_number']}")
    if lines:
        lines.append("")
    lines.extend([
        "Betreff: Voraussichtlicher Entschädigungsanspruch nach § 58 TKG",
        "",
        "Sehr geehrte Damen und Herren,",
        "",
        "hiermit mache ich auf Grundlage meiner bestätigten Angaben einen "
        "voraussichtlichen Entschädigungsanspruch geltend.",
    ])
    if outage_claim:
        lines.extend([
            "Ich bestätige für die nachfolgend aufgeführten Tage einen vollständigen Dienstausfall.",
            f"Eingang der Störungsmeldung: {claim['fault_report_received_date']}",
        ])
        if claim.get("fault_report_channel"):
            lines.append(f"Meldekanal: {claim['fault_report_channel']}")
        if claim.get("ticket_ref"):
            lines.append(f"Ticket-/Vorgangsnummer: {claim['ticket_ref']}")
        if claim.get("restored_date"):
            lines.append(f"Bestätigtes Entstörungsdatum: {claim['restored_date']}")
        else:
            lines.append("Der Ausfall dauert nach meinen Angaben an.")
        lines.extend(["", "Berechnung nach TKG §58 Abs.3:"])
        for item in breakdown.days:
            lines.append(
                f"- {item.date} ({_outage_day_label(item.day_index)}): "
                f"max({_euros(item.flat_cents)}; {item.percentage} % = "
                f"{_euros(item.percentage_cents)}) = {_euros(item.amount_cents)}; "
                f"{item.rule_ref}"
            )
        for item in breakdown.exclusions:
            reason = (
                "Wartezeit: Der Eingangstag der Störungsmeldung ist Tag 0; vor "
                "dem dritten Kalendertag nach Eingang wird kein Anspruch nach "
                "§ 58 Abs. 3 berechnet."
                if item.reason == "statutory_waiting_period"
                else (
                    "Vorsorglich ausgeschlossen, weil die Nutzerangabe bestätigt, dass "
                    "der Anbieter an diesem Tag eine Ersatzlösung bereitgestellt hat; "
                    "Annahme oder Eignung werden nicht unterstellt."
                )
            )
            lines.append(
                f"- {item.date} ({_outage_day_label(item.day_index)}): "
                f"nicht angesetzt – {reason}"
            )
        lines.append(
            "Voraussichtlicher Anspruch aus vollständigem Ausfall: "
            + _euros(breakdown.total_cents)
        )

    if missed_appointments:
        heading = (
            "Zusätzliche verpasste Termine nach TKG §58 Abs.4:"
            if outage_claim
            else "Verpasste Termine nach TKG §58 Abs.4:"
        )
        lines.extend(["", heading])
        for index, item in enumerate(missed_appointments, start=1):
            lines.append(
                f"- Termin {index}: max({_euros(item.flat_cents)}; "
                f"{item.percentage} % = {_euros(item.percentage_cents)}) = "
                f"{_euros(item.amount_cents)}"
            )
        lines.append(
            "Summe verpasste Termine: "
            + _euros(appointment_total_cents)
        )

    lines.extend([
        "",
        "Voraussichtlicher Gesamtanspruch: "
        + _euros(breakdown.total_cents + appointment_total_cents),
    ])

    prior_credit = claim.get("prior_credit") or {}
    if prior_credit.get("amount_cents") is not None:
        classification = {
            "goodwill": "Kulanz",
            "reduction": "Entgeltminderung",
            "compensation": "Entschädigung",
            "unclear": "unklar",
        }.get(prior_credit.get("classification"), "unklar")
        lines.extend([
            "",
            f"Bereits ausgewiesene Gutschrift: {_euros(int(prior_credit['amount_cents']))}",
            f"Nutzerseitige Einordnung: {classification}",
            "Diese Gutschrift wurde nicht automatisch mit dem voraussichtlichen Anspruch verrechnet.",
        ])

    lines.extend([
        "",
        f"Regelwerk: {breakdown.rules_version}; Gültigkeitsstand: {breakdown.effective_date}",
    ])
    if breakdown.rounding_note:
        lines.append(
            "Prozentbeträge mit Bruchteilen eines Cents wurden mit Decimal "
            "ROUND_HALF_UP auf den nächsten Cent gerundet. Das Gesetz nennt den "
            "Prozentsatz, schreibt aber keine Rundung von Bruchteilen eines Cents vor."
        )
    lines.append("Quellen:")
    lines.extend(f"- {source.label}: {source.url}" for source in breakdown.sources)
    lines.extend([
        "Ich bitte um Prüfung und nachvollziehbare Abrechnung des Anspruchs.",
        "",
        "Mit freundlichen Grüßen",
        "",
        (
            "Hinweis: Diese Berechnung ist keine Rechtsberatung und kein "
            "Erfolgsversprechen. Anbieter oder Gerichte können den Sachverhalt "
            "abweichend bewerten."
        ),
    ])
    return "\n".join(lines)
