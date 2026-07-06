"""Tests for the standalone glossary route."""

from app.glossary import GLOSSARY_LEVELS
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
