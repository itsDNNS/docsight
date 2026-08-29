"""Contracts for the verbatim German TKG appendix in the glossary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

import app.glossary as glossary_module
from app.glossary import (
    get_glossary_localization_languages,
    get_glossary_term,
    validate_glossary_catalog,
)
from app.glossary_legal_texts import TKG_57_ABS_4, TKG_58, TKG_LEGAL_REVIEW_DATE
from app.modules.de_tkg_compensation.rules_data import RULESET_DE_TKG58


def _digest(paragraphs):
    normalized = "\n".join(" ".join(paragraph.split()) for paragraph in paragraphs)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _legal_term(**changes):
    base = replace(
        glossary_module._TERMS[0],
        id="legal_contract",
        aliases={"en": ("Legal contract",)},
        related=(),
        legal_texts=(TKG_58,),
        legal_review_date=TKG_LEGAL_REVIEW_DATE,
    )
    return replace(base, **changes)


def test_tkg_statutory_text_shape_and_pinned_hashes():
    assert TKG_58["label"] == "§ 58 Entstörung"
    assert TKG_58["excerpt"] is False
    assert len(TKG_58["paragraphs"]) == 5
    assert TKG_58["paragraphs"][0].startswith("(1)")
    assert "Entschädigung" in " ".join(TKG_58["paragraphs"])
    assert "the consumer" not in " ".join(TKG_58["paragraphs"]).casefold()

    assert TKG_57_ABS_4["label"] == "§ 57 Vertragsänderung, Minderung und außerordentliche Kündigung"
    assert TKG_57_ABS_4["excerpt"] is True
    assert len(TKG_57_ABS_4["paragraphs"]) == 1
    assert TKG_57_ABS_4["paragraphs"][0].startswith("(4) Im Falle von 1.")
    assert " 2. anhaltenden" in TKG_57_ABS_4["paragraphs"][0]

    assert _digest(TKG_58["paragraphs"]) == "8c01ff7e856d336a8e2cf73df0d4cebea9cdb7a4f4432dfbddae32370bfbc8cc", (
        "TKG § 58 drifted; re-verify the official page and update the text, hash, "
        "and TKG_LEGAL_REVIEW_DATE together"
    )
    assert _digest(TKG_57_ABS_4["paragraphs"]) == "506db487fcc1ff154e5f9474aa545040e05c80e3ee68ee2b2f36c5025f53441f", (
        "TKG § 57 Abs. 4 drifted; re-verify the official page and update the text, "
        "hash, and TKG_LEGAL_REVIEW_DATE together"
    )
    assert TKG_LEGAL_REVIEW_DATE == "2026-08-29"
    assert TKG_LEGAL_REVIEW_DATE >= RULESET_DE_TKG58.review_date
    assert {TKG_58["source_url"], TKG_57_ABS_4["source_url"]}.issubset(
        {source.url for source in RULESET_DE_TKG58.sources}
    )


def test_tkg_statutory_text_is_immutable_german_across_every_locale():
    english = get_glossary_term("tkg_rights_de", "en")
    assert english is not None
    assert english["source_pages"] == ["Features-TKG-Compensation.md"]
    assert english["legal_texts"] == [dict(TKG_58), dict(TKG_57_ABS_4)]
    assert english["legal_review_date"] == TKG_LEGAL_REVIEW_DATE

    for lang in ("de", "fr", *get_glossary_localization_languages()):
        localized = get_glossary_term("tkg_rights_de", lang)
        assert localized is not None
        assert localized["legal_texts"] == english["legal_texts"]
        assert localized["legal_review_date"] == english["legal_review_date"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"legal_review_date": ""}, "requires legal review date"),
        ({"legal_review_date": "29-08-2026"}, "invalid legal review date"),
        ({"legal_texts": (), "legal_review_date": "2026-08-29"}, "orphan legal review date"),
        ({"legal_texts": ({**TKG_58, "source_url": "http://www.gesetze-im-internet.de/tkg_2021/__58.html"},)}, "official HTTPS source"),
        ({"legal_texts": ({**TKG_58, "source_url": "https://evil.example/__58.html"},)}, "official HTTPS source"),
        ({"legal_texts": ({**TKG_58, "paragraphs": ()},)}, "non-empty paragraphs"),
        ({"legal_texts": ({**TKG_58, "paragraphs": ("",)},)}, "non-empty paragraph 0"),
        ({"legal_texts": ({**TKG_58, "excerpt": "false"},)}, "excerpt must be a bool"),
    ],
)
def test_legal_text_schema_rejects_unsafe_or_incomplete_data(changes, message):
    assert any(message in error for error in validate_glossary_catalog([_legal_term(**changes)]))


def test_glossary_localization_catalog_cannot_override_legal_text(monkeypatch, tmp_path):
    (tmp_path / "de.json").write_text(
        json.dumps({"terms": [{"id": "tkg_rights_de", "legal_texts": []}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(glossary_module, "_GLOSSARY_I18N_DIR", tmp_path)
    glossary_module._load_glossary_localizations.cache_clear()
    try:
        with pytest.raises(ValueError, match="must not localize legal_texts"):
            glossary_module._load_glossary_localizations()
    finally:
        glossary_module._load_glossary_localizations.cache_clear()
