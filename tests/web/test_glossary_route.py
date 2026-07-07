"""Tests for the standalone glossary route."""

import re

from app.glossary import get_glossary_terms
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


def test_glossary_route_renders_simple_summary_and_explanation(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=sc_qam&level=technician")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Quick summary" in html
    assert "Explanation" in html
    assert "All explanation levels" not in html
    assert "Technician" not in html
    assert "SC-QAM is one kind of cable channel" in html
    assert "SC-QAM channels are traditional DOCSIS channels" in html


def test_glossary_route_falls_back_from_invalid_term_and_level(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=missing&level=invalid")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Quick summary" in html
    assert "Explanation" in html
    assert "No glossary term selected" not in html


def test_dashboard_links_to_standalone_glossary(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/?lang=en")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'href="/glossary?lang=en"' in html
    assert "Glossary" in html
    assert 'data-glossary-term-id="docsis" data-glossary-term-level="basic"' in html


def test_glossary_route_exposes_simple_search_metadata(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=docsis")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="glossary-search"' in html
    assert 'id="glossary-mobile-search"' in html
    assert 'data-glossary-term data-category="capacity_throughput"' in html
    assert 'data-category-filter=' not in html
    assert 'data-search="CMTS cmts Cable/DOCSIS basics' in html
    assert '/static/js/glossary-page.js?v=' in html


def test_glossary_route_lists_terms_alphabetically(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=docsis")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    desktop_terms = re.findall(r'class="glossary-term-link[^"]*"[^>]*>\s*([^<]+?)\s*</a>', html)
    assert desktop_terms[:3] == ["Attenuation", "Bootfile/config file", "Cable modem/router"]


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
