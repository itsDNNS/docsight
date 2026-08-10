"""Durable static contracts for API-backed DOM rendering."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bnetz_table_uses_dom_nodes_for_api_data_and_actions():
    source = (ROOT / "app/static/js/integrations.js").read_text(encoding="utf-8")

    assert ".innerHTML" not in source
    assert "javascript:" not in source.lower()
    assert "document.createElement('td')" in source
    assert ".textContent" in source
    assert "addEventListener('click'" in source


def test_smokeping_cards_and_error_fallback_use_dom_nodes():
    source = (ROOT / "app/modules/smokeping/static/main.js").read_text(
        encoding="utf-8"
    )

    assert ".innerHTML" not in source
    assert "headerLabel.textContent = target" in source
    assert "fallback.textContent" in source
