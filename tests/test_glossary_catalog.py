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


def test_core_glossary_contains_only_docsis_terms_and_docsight_features():
    terms = {term["id"]: term for term in get_glossary_terms("en")}
    expected_docsis_terms = {
        "docsis", "downstream", "upstream", "channel_bonding", "sc_qam", "ofdm", "ofdma",
        "mixed_mode", "qam_modulation_order", "qpsk", "power_level", "snr_mer",
        "correctable_errors", "uncorrectable_errors", "t3_t4_timeout", "cmts", "vcmts",
        "remote_phy", "return_path_interference", "node_segment", "shared_medium", "health_status",
    }
    expected_docsight_features = {
        "dashboard", "in_app_glossary", "channel_timeline", "signal_trends",
        "modulation_performance", "segment_utilization", "correlation_analysis",
        "before_after_comparison", "connection_monitor", "event_log", "incident_journal",
        "smart_capture", "speedtest", "bqm", "smokeping", "bnetza", "gaming_index",
        "llm_export", "doctor_diagnostics", "pwa_offline",
    }

    assert set(terms) == expected_docsis_terms | expected_docsight_features
    for term in terms.values():
        assert term["category"] in {"docsis_terms", "docsight_features"}
        assert term["title"]
        assert term["aliases"]
        assert term["source_pages"]
        assert term["tags"]
        assert term["ui_contexts"]
        assert set(term["levels"]) == set(GLOSSARY_LEVELS)
        for level in GLOSSARY_LEVELS:
            assert len(term["levels"][level]) > 40


def test_derived_explainer_terms_do_not_appear_as_top_level_glossary_entries():
    term_ids = {term["id"] for term in get_glossary_terms("en")}
    removed_explainers = {
        "dsl_vs_cable", "coaxial_cable", "cable_modem_router", "channel_width_symbol_rate",
        "attenuation", "ingress_noise", "layer1_capacity", "gross_vs_net_capacity",
        "ip_throughput", "tariff_speed", "capacity_vs_throughput", "provisioning",
        "bootfile_config_file", "partial_service", "resync_reboot",
    }
    assert term_ids.isdisjoint(removed_explainers)

def test_related_glossary_terms_resolve_to_existing_terms():
    for term in get_glossary_terms("en"):
        related = get_related_terms(term, "en")
        assert len(related) == len(term["related"])
        assert all(item["id"] in term["related"] for item in related)


def test_categories_are_localized_and_used_by_terms():
    categories = {category["id"]: category for category in get_glossary_categories("en")}
    assert set(categories) == {"docsis_terms", "docsight_features"}
    for category in categories.values():
        assert category["title"]
        assert category["description"]
    for term in get_glossary_terms("en"):
        assert term["category"] in categories


def test_glossary_lookup_falls_back_to_english_for_unsupported_locale():
    term = get_glossary_term("docsis", "zz")
    assert term is not None
    assert term["title"] == "DOCSIS"
    assert "DOCSIS is the standard cable modems use" in term["levels"]["eli5"]


def test_speedtest_feature_keeps_throughput_boundary_in_app_terms():
    term = get_glossary_term("speedtest", "en")
    assert term is not None
    joined = " ".join(term["levels"].values())
    assert "download" in joined
    assert "latency" in joined
    assert "DOCSIS evidence" in joined

def test_core_glossary_preserves_required_technical_tokens():
    expected_tokens = {
        "docsis": {"DOCSIS", "DSL"},
        "cmts": {"CMTS", "DOCSIS"},
        "vcmts": {"vCMTS", "CMTS"},
        "sc_qam": {"SC-QAM", "QAM"},
        "ofdm": {"OFDM", "DOCSIS"},
        "ofdma": {"OFDMA", "DOCSIS"},
        "qpsk": {"QPSK", "QAM"},
        "snr_mer": {"SNR", "MER"},
    }

    for term_id, tokens in expected_tokens.items():
        term = get_glossary_term(term_id, "en")
        assert term is not None
        joined = " ".join([term["title"], *term["aliases"], *term["levels"].values(), *term["misconceptions"]])
        for token in tokens:
            assert token in term["protected_terms"]
            assert token in joined


def test_wiki_source_vocabulary_is_indexed_as_tags_aliases_and_source_pages():
    terms = {term["id"]: term for term in get_glossary_terms("en")}
    expected = {
        "docsis": {"DOCSIS-Glossary.md", "Features-Glossary.md"},
        "power_level": {"DOCSIS-Glossary.md", "Features-Glossary.md"},
        "snr_mer": {"DOCSIS-Glossary.md", "Features-Glossary.md"},
        "sc_qam": {"DOCSIS-Glossary.md", "Features-Glossary.md"},
        "ofdm": {"DOCSIS-Glossary.md", "Features-Glossary.md"},
        "ofdma": {"DOCSIS-Glossary.md", "Features-Glossary.md"},
        "t3_t4_timeout": {"DOCSIS-Glossary.md"},
        "remote_phy": {"DOCSIS-Glossary.md"},
        "return_path_interference": {"DOCSIS-Glossary.md"},
        "mixed_mode": {"DOCSIS-Glossary.md"},
        "health_status": {"DOCSIS-Glossary.md"},
        "qpsk": {"DOCSIS-Glossary.md"},
        "vcmts": {"DOCSIS-Glossary.md"},
        "gaming_index": {"Features-Glossary.md", "Features-Gaming-Quality.md"},
        "dashboard": {"Features-Dashboard.md"},
        "in_app_glossary": {"Features-Glossary.md"},
    }

    for term_id, source_pages in expected.items():
        term = terms[term_id]
        assert source_pages.issubset(set(term["source_pages"]))
        assert term["tags"]
        assert term["ui_contexts"]

    alias_index = {
        alias
        for term in terms.values()
        for alias in term["aliases"]
    }
    for alias in {
        "DS Power",
        "US Power",
        "Errors",
        "Channels",
        "Virtual CMTS",
        "R-PHY",
        "T3 timeout",
        "T4 timeout",
        "Good",
        "Marginal",
        "Poor",
        "Gaming Quality Index",
    }:
        assert alias in alias_index


def test_glossary_aliases_do_not_duplicate_other_term_titles_or_aliases():
    seen = {}
    for term in get_glossary_terms("en"):
        for value in (term["title"], *term["aliases"]):
            normalized = value.casefold()
            previous = seen.setdefault(normalized, term["id"])
            assert previous == term["id"], f"{term['id']} duplicates alias/title {value!r} from {previous}"
