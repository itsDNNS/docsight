"""Canonical in-app glossary data model and loader."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

GLOSSARY_LEVELS: tuple[str, ...] = ("eli5", "basic", "advanced", "technician")


@dataclass(frozen=True)
class GlossaryTerm:
    """A canonical glossary term with stable IDs and multi-level explanations."""

    id: str
    category: str
    title: dict[str, str]
    aliases: dict[str, tuple[str, ...]]
    levels: dict[str, dict[str, str]]
    misconceptions: dict[str, tuple[str, ...]]
    related: tuple[str, ...]
    protected_terms: tuple[str, ...]

    def localized(self, lang: str = "en") -> dict[str, Any]:
        """Return a template-friendly localized term, falling back to English."""
        title = self.title.get(lang) or self.title["en"]
        aliases = self.aliases.get(lang) or self.aliases.get("en", ())
        levels = self.levels.get(lang) or self.levels["en"]
        misconceptions = self.misconceptions.get(lang) or self.misconceptions.get("en", ())
        return {
            "id": self.id,
            "category": self.category,
            "title": title,
            "aliases": list(aliases),
            "levels": dict(levels),
            "misconceptions": list(misconceptions),
            "related": list(self.related),
            "protected_terms": list(self.protected_terms),
        }


@dataclass(frozen=True)
class GlossaryCategory:
    """A glossary category for browsing and future filtering."""

    id: str
    title: dict[str, str]
    description: dict[str, str]

    def localized(self, lang: str = "en") -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title.get(lang) or self.title["en"],
            "description": self.description.get(lang) or self.description["en"],
        }


_CATEGORIES: tuple[GlossaryCategory, ...] = (
    GlossaryCategory(
        id="cable_basics",
        title={"en": "Cable/DOCSIS basics"},
        description={
            "en": "Core terms for understanding cable internet and what DOCSight can observe.",
        },
    ),
    GlossaryCategory(
        id="modulation_channels",
        title={"en": "Modulation and channels"},
        description={
            "en": "How DOCSIS channels carry data and why channel technology matters.",
        },
    ),
    GlossaryCategory(
        id="capacity_throughput",
        title={"en": "Capacity and throughput"},
        description={
            "en": "Boundaries between channel diagnostics, gross capacity, tariff speed, and speedtests.",
        },
    ),
)

_TERMS: tuple[GlossaryTerm, ...] = (
    GlossaryTerm(
        id="docsis",
        category="cable_basics",
        title={"en": "DOCSIS"},
        aliases={"en": ("Cable internet", "Data Over Cable Service Interface Specification")},
        protected_terms=("DOCSIS", "DSL", "DOCSight"),
        related=("shared_medium", "sc_qam", "capacity_vs_throughput"),
        levels={
            "en": {
                "eli5": "DOCSIS is the language a cable modem uses to talk to the cable network. It is cable internet, not DSL over a phone line.",
                "basic": "DOCSIS carries internet service over coax cable. DOCSight reads modem, channel, and signal data from supported cable devices, so its diagnostics describe the cable link rather than a DSL line.",
                "advanced": "DOCSIS networks combine downstream and upstream channels such as SC-QAM, OFDM, and OFDMA. DOCSight can interpret local modem-visible signal and channel data, but it cannot see every provider-side segment or routing condition.",
                "technician": "DOCSIS defines the cable modem access layer between the CM and CMTS over the HFC/coax segment. Local channel telemetry is useful for RF and MAC-layer diagnostics, but provider provisioning, segment load, CMTS policy, and IP routing remain outside the modem-only evidence boundary.",
            }
        },
        misconceptions={
            "en": (
                "DOCSIS is not DSL; DSL values and cable channel values should not be compared one-to-one.",
            )
        },
    ),
    GlossaryTerm(
        id="shared_medium",
        category="cable_basics",
        title={"en": "Shared medium"},
        aliases={"en": ("Segment", "Cable segment", "Node")},
        protected_terms=("DOCSIS", "CMTS", "DOCSight"),
        related=("docsis", "capacity_vs_throughput"),
        levels={
            "en": {
                "eli5": "A cable segment is like a road that several homes use. Your modem can have a clean signal even when the road is busy.",
                "basic": "Cable networks share parts of the access network between multiple users. Segment load can affect real speeds, and DOCSight cannot directly measure every other modem on the segment.",
                "advanced": "DOCSIS capacity is shared across channels and service groups. Local modem stats show your channel and signal state, while contention and scheduling happen at the provider side.",
                "technician": "Shared-medium behavior depends on service-group sizing, CMTS scheduling, OFDMA/OFDM profiles, provisioning, and active subscriber demand. DOCSight can highlight local RF/channel symptoms but should not infer complete segment utilization unless a supported data source exposes it.",
            }
        },
        misconceptions={
            "en": (
                "A good signal level does not prove that the provider segment is uncongested.",
            )
        },
    ),
    GlossaryTerm(
        id="sc_qam",
        category="modulation_channels",
        title={"en": "SC-QAM"},
        aliases={"en": ("Single-carrier QAM", "DOCSIS 3.0 channel")},
        protected_terms=("SC-QAM", "DOCSIS", "QAM", "Layer-1"),
        related=("docsis", "ofdm", "capacity_vs_throughput"),
        levels={
            "en": {
                "eli5": "SC-QAM is one kind of cable channel. Think of it as one lane that can carry data between the cable network and your modem.",
                "basic": "SC-QAM channels are traditional DOCSIS channels. DOCSight can often estimate their gross Layer-1 capacity from modulation and channel details.",
                "advanced": "SC-QAM uses a single carrier with a fixed channel width and QAM modulation order. Higher modulation can carry more bits per symbol, but the estimate is still gross channel capacity, not IP throughput.",
                "technician": "For DOCSIS SC-QAM channels, modulation order, symbol rate, channel width, and PHY overhead determine gross Layer-1 estimates. FEC, MAC framing, scheduling, bonding, and IP overhead separate that estimate from usable application throughput.",
            }
        },
        misconceptions={
            "en": (
                "An SC-QAM capacity estimate is not a speedtest result.",
            )
        },
    ),
    GlossaryTerm(
        id="ofdm",
        category="modulation_channels",
        title={"en": "OFDM/OFDMA"},
        aliases={"en": ("DOCSIS 3.1 channel", "OFDM", "OFDMA")},
        protected_terms=("OFDM", "OFDMA", "DOCSIS", "SC-QAM"),
        related=("docsis", "sc_qam", "capacity_vs_throughput"),
        levels={
            "en": {
                "eli5": "OFDM and OFDMA are newer cable channel types that split a wide channel into many tiny pieces.",
                "basic": "DOCSIS 3.1 uses OFDM downstream and OFDMA upstream for flexible, high-capacity channels. DOCSight may show their signal state even when it cannot calculate the same simple capacity number as SC-QAM.",
                "advanced": "OFDM/OFDMA channels use many subcarriers and profiles. Their real capacity depends on profile assignment, subcarrier health, exclusion bands, and provider-side scheduling.",
                "technician": "OFDM/OFDMA telemetry requires profile/subcarrier context to estimate capacity safely. Without sufficient profile data, DOCSight should treat these channels as observed but not included in SC-QAM-only gross capacity sums.",
            }
        },
        misconceptions={
            "en": (
                "Missing OFDM/OFDMA capacity does not mean the channel is unused; it may mean DOCSight lacks safe profile-level data.",
            )
        },
    ),
    GlossaryTerm(
        id="capacity_vs_throughput",
        category="capacity_throughput",
        title={"en": "Capacity vs. speedtest"},
        aliases={"en": ("Throughput", "Tariff speed", "Gross capacity", "IP speed")},
        protected_terms=("Layer-1", "SC-QAM", "Speedtest", "IP", "DOCSight"),
        related=("docsis", "sc_qam", "shared_medium"),
        levels={
            "en": {
                "eli5": "Capacity is what the cable lane could carry in theory. A speedtest is what your connection delivers right now after many other things are included.",
                "basic": "DOCSight capacity estimates describe channel-level gross capacity, especially for supported SC-QAM channels. They are not your tariff speed, not a speedtest, and not guaranteed real IP throughput.",
                "advanced": "Layer-1 channel capacity is before MAC, FEC, scheduling, bonding, segment load, traffic shaping, and IP/application overhead. Speedtests measure an end-to-end path at one moment in time.",
                "technician": "Do not equate PHY gross capacity with service-flow rate limits or TCP/UDP goodput. CMTS scheduling, provisioning, OFDM/OFDMA profile availability, RF impairment, queueing, peering, and test-server behavior can all dominate observed throughput.",
            }
        },
        misconceptions={
            "en": (
                "A channel capacity sum is not proof that a customer should see the same number in a speedtest.",
                "Tariff speed is a product configuration; DOCSight channel diagnostics are local evidence.",
            )
        },
    ),
)


def _category_ids() -> set[str]:
    return {category.id for category in _CATEGORIES}


def _term_ids() -> set[str]:
    return {term.id for term in _TERMS}


def validate_glossary_catalog(terms: Iterable[GlossaryTerm] = _TERMS) -> list[str]:
    """Return schema/link validation errors for the glossary catalog."""
    errors: list[str] = []
    seen: set[str] = set()
    term_list = list(terms)
    term_ids = {term.id for term in term_list}
    category_ids = _category_ids()

    for term in term_list:
        if not term.id:
            errors.append("term id is required")
        if term.id in seen:
            errors.append(f"duplicate term id: {term.id}")
        seen.add(term.id)
        if term.category not in category_ids:
            errors.append(f"{term.id}: unknown category {term.category}")
        if not term.title.get("en"):
            errors.append(f"{term.id}: missing English title")
        if "en" not in term.levels:
            errors.append(f"{term.id}: missing English levels")
            continue
        for level in GLOSSARY_LEVELS:
            text = term.levels["en"].get(level, "").strip()
            if not text:
                errors.append(f"{term.id}: missing {level} level")
        for related_id in term.related:
            if related_id not in term_ids:
                errors.append(f"{term.id}: unknown related term {related_id}")
        for token in term.protected_terms:
            if not token:
                errors.append(f"{term.id}: empty protected term")

    return errors


def get_glossary_categories(lang: str = "en") -> list[dict[str, str]]:
    """Return localized glossary categories."""
    return [category.localized(lang) for category in _CATEGORIES]


def get_glossary_terms(lang: str = "en") -> list[dict[str, Any]]:
    """Return localized glossary terms sorted by category order and title."""
    localized = [term.localized(lang) for term in _TERMS]
    category_order = {category.id: index for index, category in enumerate(_CATEGORIES)}
    return sorted(
        localized,
        key=lambda item: (category_order.get(item["category"], 999), item["title"].lower()),
    )


def get_glossary_term(term_id: str, lang: str = "en") -> dict[str, Any] | None:
    """Return one localized glossary term by stable ID."""
    for term in _TERMS:
        if term.id == term_id:
            return term.localized(lang)
    return None


def get_related_terms(term: dict[str, Any], lang: str = "en") -> list[dict[str, Any]]:
    """Resolve related term IDs for a localized term dict."""
    related = []
    for term_id in term.get("related", []):
        resolved = get_glossary_term(term_id, lang)
        if resolved:
            related.append(resolved)
    return related
