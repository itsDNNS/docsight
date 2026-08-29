"""Release-versioned legal source metadata for the German TKG rules."""

from .rules import LegalSource, RuleSet


RULESET_DE_TKG58 = RuleSet(
    rules_version="de-tkg58-2026.1",
    jurisdiction="DE",
    effective_date="2021-12-01",
    review_date="2026-08-28",
    sources=(
        LegalSource(
            "TKG § 58",
            "https://www.gesetze-im-internet.de/tkg_2021/__58.html",
        ),
        LegalSource(
            "TKG § 57",
            "https://www.gesetze-im-internet.de/tkg_2021/__57.html",
        ),
        LegalSource(
            "Bundesnetzagentur: Störung",
            "https://www.bundesnetzagentur.de/DE/Vportal/TK/InternetTelefon/Stoerung/start.html",
        ),
        LegalSource(
            "Verbraucherzentrale: Internet- und Telefonstörungen",
            "https://www.verbraucherzentrale.de/infothek/was-tun-bei-stoerungen-von-internet-und-telefon-38208",
        ),
        LegalSource(
            "Verbraucherzentrale: Musterformular",
            "https://www.verbraucherzentrale.de/media/32565/download",
        ),
    ),
    source_review_note=(
        "Source review: the cited statute defines the daily percentages but does "
        "not prescribe a sub-cent rounding rule. ROUND_HALF_UP is the documented "
        "product calculation rule, not quoted statutory wording. A provider "
        "replacement solution is excluded only for a day the user explicitly "
        "confirms it was made available; no acceptance or suitability is inferred. "
        "For statutory day counting, the report-receipt date is day 0 and "
        "compensation is first considered on the third calendar day after receipt. "
        "Each confirmed day must be a full local calendar day of complete outage."
    ),
)

RULESETS = {RULESET_DE_TKG58.rules_version: RULESET_DE_TKG58}


def resolve_ruleset(rules_version: str) -> RuleSet:
    """Resolve persisted rule metadata without silently relabeling calculations."""
    from .rules import RuleValidationError

    try:
        return RULESETS[rules_version]
    except (KeyError, TypeError):
        raise RuleValidationError(
            "technical_rules_version_unsupported",
            f"Unsupported persisted rules version: {rules_version!r}",
        ) from None
