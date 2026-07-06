"""Tests for the standalone glossary route."""

import re

from app.glossary import GLOSSARY_LEVELS, get_glossary_terms
from app.web import update_state


def test_glossary_route_renders_canonical_terms(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Glossary" in html
    assert "Cable/DOCSIS basics" in html
    assert "DOCSIS" in html
    assert "SC-QAM" in html
    assert "Capacity vs. speedtest" in html
    assert "docsis" in html


def test_glossary_route_supports_all_explanation_levels(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=sc_qam&level=technician")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for label in ("ELI5", "Basic", "Advanced", "Technician"):
        assert label in html
    assert "aria-current=\"true\"" in html
    assert "Layer-1 estimates" in html or "gross Layer-1 estimates" in html


def test_glossary_route_falls_back_from_invalid_term_and_level(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=missing&level=invalid")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Basic" in html
    assert any(level in html for level in GLOSSARY_LEVELS)
    assert "No glossary term selected" not in html


def test_dashboard_links_to_standalone_glossary(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/?lang=en")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'href="/glossary?lang=en"' in html
    assert "Glossary" in html
    assert 'data-glossary-term-id="docsis" data-glossary-term-level="basic"' in html


def test_glossary_route_exposes_search_and_category_filter_metadata(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=docsis")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="glossary-search"' in html
    assert 'data-category-filter="signal_quality"' in html
    assert 'data-glossary-term data-category="capacity_throughput"' in html
    assert 'data-search="CMTS cmts Cable/DOCSIS basics' in html
    assert '/static/js/glossary-page.js?v=' in html


def test_contextual_glossary_links_target_existing_terms(client, sample_analysis):
    docsis31_analysis = {
        **sample_analysis,
        "ds_channels": [
            *sample_analysis["ds_channels"],
            {**sample_analysis["ds_channels"][0], "channel_id": 32, "docsis_version": "3.1", "modulation": "OFDM"},
        ],
        "us_channels": [
            *sample_analysis["us_channels"],
            {
                **sample_analysis["us_channels"][0],
                "channel_id": 5,
                "docsis_version": "3.1",
                "multiplex": "OFDMA",
                "modulation": "OFDMA",
            },
        ],
    }
    update_state(analysis=docsis31_analysis)
    valid_terms = {term["id"] for term in get_glossary_terms("en")}

    resp = client.get("/?lang=en")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    ids = re.findall(r'data-glossary-term-id="([^"]+)"', html)
    assert ids
    targeted_terms = set()
    for term in ids:
        assert term in valid_terms
        targeted_terms.add(term)

    assert {"docsis", "power_level", "snr_mer", "uncorrectable_errors", "ofdm", "ofdma", "sc_qam"}.issubset(targeted_terms)
