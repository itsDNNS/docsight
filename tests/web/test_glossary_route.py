"""Tests for glossary app-shell routing."""

import re

from app.glossary import get_glossary_terms
from app.web import update_state


def test_glossary_route_redirects_to_in_app_glossary(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=sc_qam&level=basic")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/?lang=en#glossary?term=sc_qam&level=basic"


def test_glossary_route_drops_invalid_deep_link_values(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/glossary?lang=en&term=https://evil.example/&level=invalid")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/?lang=en#glossary"


def test_index_renders_glossary_inside_app_shell(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/?lang=en&term=docsis")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="sidebar"' in html
    assert 'data-view="glossary"' in html
    assert 'id="view-glossary" class="view glossary-app-view"' in html
    assert 'href="/glossary?lang=en"' not in html
    assert "DOCSIS" in html
    assert "SC-QAM" in html
    assert "Gaming Index" in html
    assert "DSL vs. cable" not in html


def test_index_glossary_renders_simple_summary_and_explanation(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/?lang=en&term=sc_qam")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Quick summary" in html
    assert "Explanation" in html
    assert 'id="glossary-level-selector"' not in html
    assert 'data-glossary-level' not in html
    assert "SC-QAM is the classic narrow DOCSIS channel type" in html
    assert "SC-QAM channels are traditional DOCSIS 3.0-style channels" in html
    active_article = html.split('class="glossary-term-article" data-glossary-article data-term-id="sc_qam"', 1)[1].split('class="glossary-term-article" data-glossary-article', 1)[0]
    assert '<p class="eyebrow">' not in active_article
    assert "DOCSIS terms" not in active_article
    assert "Also searched as" in active_article
    assert 'data-glossary-detail-level="advanced"' in html
    assert 'data-glossary-detail-level="technician"' in html
    assert 'class="glossary-media-card"' not in html


def test_index_glossary_exposes_wiki_source_search_metadata(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/?lang=en&term=docsis")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="glossary-search"' in html
    assert 'id="glossary-mobile-search"' in html
    assert 'data-category-filter=' not in html
    assert 'data-source-pages="DOCSIS-Glossary.md Features-Glossary.md"' in html
    assert 'data-tags="signal ds-power us-power dbmv wiki-term"' in html
    assert 'data-ui-contexts="dashboard_signal_cards channel_tables"' in html
    assert 'data-search="CMTS cmts DOCSIS terms' in html
    assert 'vCMTS' in html
    assert '/static/js/glossary-page.js?v=' in html


def test_index_glossary_lists_terms_alphabetically(client, sample_analysis):
    update_state(analysis=sample_analysis)

    resp = client.get("/?lang=en&term=docsis")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    desktop = html.split('id="glossary-desktop-terms"', 1)[1].split("</nav>", 1)[0]
    desktop_terms = re.findall(r'class="glossary-term-link[^"]*"[^>]*>\s*([^<]+?)\s*</a>', desktop)
    assert desktop_terms == sorted(desktop_terms, key=str.casefold)
    assert desktop_terms[:3] == ["Before/After Comparison", "BNetzA measurement", "BQM"]


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
