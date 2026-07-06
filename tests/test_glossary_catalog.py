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


def test_core_docsis_glossary_contains_required_terms_and_levels():
    terms = {term["id"]: term for term in get_glossary_terms("en")}
    required_terms = {
        "docsis",
        "dsl_vs_cable",
        "coaxial_cable",
        "cable_modem_router",
        "cmts",
        "node_segment",
        "shared_medium",
        "downstream",
        "upstream",
        "channel_bonding",
        "sc_qam",
        "ofdm",
        "ofdma",
        "qam_modulation_order",
        "channel_width_symbol_rate",
        "power_level",
        "snr_mer",
        "attenuation",
        "ingress_noise",
        "correctable_errors",
        "uncorrectable_errors",
        "layer1_capacity",
        "gross_vs_net_capacity",
        "ip_throughput",
        "speedtest",
        "tariff_speed",
        "segment_utilization",
        "capacity_vs_throughput",
        "provisioning",
        "bootfile_config_file",
        "partial_service",
        "resync_reboot",
    }

    assert required_terms.issubset(terms)
    for term_id in required_terms:
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
    assert {"cable_basics", "modulation_channels", "signal_quality", "error_counters", "capacity_throughput", "modem_state"}.issubset(categories)
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


def test_core_glossary_preserves_required_technical_tokens():
    expected_tokens = {
        "docsis": {"DOCSIS", "DSL"},
        "cmts": {"CMTS", "DOCSIS"},
        "sc_qam": {"SC-QAM", "QAM", "Layer-1"},
        "ofdm": {"OFDM", "DOCSIS"},
        "ofdma": {"OFDMA", "DOCSIS"},
        "capacity_vs_throughput": {"Speedtest", "IP", "Layer-1"},
        "snr_mer": {"SNR", "MER"},
    }

    for term_id, tokens in expected_tokens.items():
        term = get_glossary_term(term_id, "en")
        assert term is not None
        joined = " ".join([term["title"], *term["aliases"], *term["levels"].values(), *term["misconceptions"]])
        for token in tokens:
            assert token in term["protected_terms"]
            assert token in joined


def test_glossary_aliases_do_not_duplicate_other_term_titles_or_aliases():
    seen = {}
    for term in get_glossary_terms("en"):
        for value in (term["title"], *term["aliases"]):
            normalized = value.casefold()
            previous = seen.setdefault(normalized, term["id"])
            assert previous == term["id"], f"{term['id']} duplicates alias/title {value!r} from {previous}"
