"""The command palette ships the same sources on the dashboard and in settings."""

import json
import re

import pytest

from app.glossary import get_glossary_terms


def _palette_data(html):
    match = re.search(r'<script type="application/json" id="command-palette-data">(.*?)</script>', html, re.S)
    assert match, "palette data missing"
    return json.loads(match.group(1))


@pytest.mark.parametrize("path", ["/", "/settings"])
def test_palette_lists_settings_sections_and_glossary_terms(client, path):
    html = client.get(path).get_data(as_text=True)

    assert 'id="command-palette-open"' in html
    assert 'id="command-palette"' in html
    data = _palette_data(html)
    assert [section[0] for section in data["settings"]] == [
        "connection", "sources", "notifications", "evidence", "data", "appearance", "access", "extensions", "about",
    ]
    assert [term[0] for term in data["glossary"]] == [term["id"] for term in get_glossary_terms("en")]
    assert [key for key, _target in data["shortcuts"]] == ["o", "s", "c", "e", "v"]


def test_settings_index_comes_from_the_shared_sections(client):
    html = client.get("/settings").get_data(as_text=True)
    sections = re.findall(r'class="settings-index-item[^"]*" data-section="([a-z]+)"', html)

    assert sections == [section[0] for section in _palette_data(html)["settings"]]
