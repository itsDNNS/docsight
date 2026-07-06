"""Tests for the canonical in-app glossary catalog."""

from app.glossary import (
    GLOSSARY_LEVELS,
    get_glossary_categories,
    get_glossary_term,
    get_glossary_terms,
    get_related_terms,
    validate_glossary_catalog,
)


def test_glossary_catalog_schema_is_valid():
    assert validate_glossary_catalog() == []


def test_minimal_vertical_slice_contains_required_foundation_terms():
    terms = {term["id"]: term for term in get_glossary_terms("en")}

    for term_id in {"docsis", "shared_medium", "sc_qam", "ofdm", "capacity_vs_throughput"}:
        assert term_id in terms
        term = terms[term_id]
        assert term["title"]
        assert term["category"]
        assert term["aliases"]
        assert term["protected_terms"]
        assert set(term["levels"]) == set(GLOSSARY_LEVELS)
        for level in GLOSSARY_LEVELS:
            assert len(term["levels"][level]) > 60


def test_related_glossary_terms_resolve_to_existing_terms():
    for term in get_glossary_terms("en"):
        related = get_related_terms(term, "en")
        assert len(related) == len(term["related"])
        assert all(item["id"] in term["related"] for item in related)


def test_categories_are_localized_and_used_by_terms():
    categories = {category["id"]: category for category in get_glossary_categories("en")}
    assert {"cable_basics", "modulation_channels", "capacity_throughput"}.issubset(categories)
    for category in categories.values():
        assert category["title"]
        assert category["description"]
    for term in get_glossary_terms("en"):
        assert term["category"] in categories


def test_glossary_lookup_falls_back_to_english_for_untranslated_locale():
    term = get_glossary_term("docsis", "de")
    assert term is not None
    assert term["title"] == "DOCSIS"
    assert "DOCSIS is the language" in term["levels"]["eli5"]


def test_capacity_term_preserves_no_speedtest_overclaim_boundary():
    term = get_glossary_term("capacity_vs_throughput", "en")
    assert term is not None
    joined = " ".join(term["levels"].values())
    assert "not your tariff speed" in joined
    assert "not a speedtest" in joined
    assert "not guaranteed real IP throughput" in joined
